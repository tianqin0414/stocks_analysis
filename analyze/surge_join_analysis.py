"""
analyze/surge_join_analysis.py — 将 dec2025_surge_14pct.xlsx 与上一交易日的
merged_analysis 数据做左连接，用于分析买入策略利润最大化。

逻辑：
  1. 读取 surge 数据（output/dec2025_surge_14pct.xlsx）
  2. 对每条记录的 '日期' 找上一个交易日
  3. 加载该交易日的 merged_analysis 文件
  4. 按股票代码做左连接
  5. 输出合并后的 Excel

用法:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 analyze/surge_join_analysis.py
"""
from __future__ import annotations

import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from config import OUTPUT_DIR

# ============================================================
# 路径
# ============================================================
SURGE_PATH = os.path.join(OUTPUT_DIR, 'dec2025_surge_14pct.xlsx')
MERGED_DIR = '/Users/tq/PycharmProjects/stocks_v2/output'
MERGED_PATTERN = '{date}_merged_analysis.xlsx'  # date = 2025-12-10


# ============================================================
# 辅助：构建交易日历 & 找上一个交易日
# ============================================================
def build_trading_calendar() -> list[str]:
    """从 merged_analysis 文件名构建已有交易日历表（YYYY-MM-DD 格式，排序）。"""
    files = glob.glob(os.path.join(MERGED_DIR, '*_merged_analysis.xlsx'))
    dates = []
    for f in files:
        bn = os.path.basename(f)
        # 2025-12-10_merged_analysis.xlsx → 2025-12-10
        date_str = bn.replace('_merged_analysis.xlsx', '')
        dates.append(date_str)
    return sorted(dates)


def find_prev_trading_day(date_yyyymmdd: str, calendar: list[str]) -> str | None:
    """给定 '20251210' 格式的日期，找日历中严格小于它的最近一天。"""
    # 转成 YYYY-MM-DD
    target = f'{date_yyyymmdd[:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:]}'
    # 严格小于 target 的最大日期
    prev = None
    for d in calendar:
        if d < target:
            prev = d
        else:
            break
    return prev


# ============================================================
# 辅助：加载 merged_analysis 并缓存
# ============================================================
_merged_cache: dict[str, pd.DataFrame | None] = {}


def load_merged_analysis(date_str: str) -> pd.DataFrame | None:
    """读取某日 merged_analysis, 仅保留需要的列, 缓存结果。"""
    if date_str in _merged_cache:
        return _merged_cache[date_str]

    path = os.path.join(MERGED_DIR, f'{date_str}_merged_analysis.xlsx')
    if not os.path.exists(path):
        print(f'  ⚠️  文件不存在: {path}')
        _merged_cache[date_str] = None
        return None

    try:
        df = pd.read_excel(path)
    except Exception as e:
        print(f'  ⚠️  读取失败 {path}: {e}')
        _merged_cache[date_str] = None
        return None

    # 提取纯数字代码用于 join
    df['股票代码_join'] = df['证券代码'].astype(str).str.split('.').str[0]

    _merged_cache[date_str] = df
    return df


# ============================================================
# 主流程
# ============================================================
def main():
    print('📂 读取 surge 数据...')
    surge_df = pd.read_excel(SURGE_PATH)
    surge_df['股票代码'] = surge_df['股票代码'].astype(str).str.strip()
    print(f'  总行数: {len(surge_df)}, 日期范围: {sorted(surge_df["日期"].unique())}')

    # 构建交易日历
    calendar = build_trading_calendar()
    print(f'  merged_analysis 日历: {len(calendar)} 个交易日')

    # 为每行找上一个交易日
    surge_df['日期_str'] = surge_df['日期'].astype(str)
    surge_df['上一交易日'] = surge_df['日期_str'].apply(
        lambda d: find_prev_trading_day(d, calendar)
    )

    # 统计
    has_prev = surge_df['上一交易日'].notna()
    print(f'  能找到上一交易日: {has_prev.sum()}/{len(surge_df)}')
    missing_dates = surge_df[~has_prev]['日期_str'].unique()
    if len(missing_dates) > 0:
        print(f'  ⚠️  以下日期无法找到上一交易日: {missing_dates}')

    # 按 '上一交易日' 分组处理
    merged_rows = []
    no_match_count = 0

    for prev_date, group in surge_df.groupby('上一交易日', dropna=True):
        ma_df = load_merged_analysis(prev_date)
        if ma_df is None:
            print(f'  ⚠️  跳过 {prev_date}: merged_analysis 不可用')
            # 这些行加入 merged_rows 但没有 merge 数据
            for _, row in group.iterrows():
                merged_rows.append(row.to_dict())
            no_match_count += len(group)
            continue

        # 左连接
        joined = group.merge(
            ma_df,
            left_on='股票代码',
            right_on='股票代码_join',
            how='left',
            suffixes=('', '_ma')
        )

        # 统计未匹配
        unmatched = joined['证券代码'].isna().sum()
        if unmatched > 0:
            no_match_count += unmatched

        for _, row in joined.iterrows():
            merged_rows.append(row.to_dict())

    # 没有上一交易日的行直接加入
    no_prev = surge_df[~has_prev]
    for _, row in no_prev.iterrows():
        merged_rows.append(row.to_dict())
    no_match_count += len(no_prev)

    result_df = pd.DataFrame(merged_rows)

    # 清理辅助列
    drop_cols = ['日期_str', '股票代码_join']
    result_df.drop(columns=[c for c in drop_cols if c in result_df.columns],
                   inplace=True)

    # 排序
    result_df = result_df.sort_values(['日期', '峰值涨幅(%)'],
                                      ascending=[True, False]).reset_index(drop=True)

    # 保存
    out_path = os.path.join(OUTPUT_DIR, 'dec2025_surge_14pct_joined.xlsx')
    result_df.to_excel(out_path, index=False)

    print(f'\n✅ 完成! 共 {len(result_df)} 条')
    print(f'  未匹配上一交易日数据: {no_match_count} 条')
    print(f'  输出列数: {len(result_df.columns)}')
    print(f'💾 已保存: {out_path}')

    # 简要汇总一些合并来的关键字段
    if '总分' in result_df.columns:
        valid_score = result_df['总分'].dropna()
        if len(valid_score) > 0:
            print(f'\n📊 关联数据预览:')
            print(f'  总分  均值={valid_score.mean():.2f}  中位={valid_score.median():.2f}')
    if 'to13' in result_df.columns:
        valid_to13 = result_df['to13'].dropna()
        if len(valid_to13) > 0:
            print(f'  to13  均值={valid_to13.mean():.2f}  中位={valid_to13.median():.2f}')


if __name__ == '__main__':
    main()
