"""
analyze/sector.py — 板块/概念分析

用法:
    python analyze/sector.py --date 2026-02-13        # 板块强弱排名
    python analyze/sector.py --concept '新能源'       # 查找某概念股
    python analyze/sector.py --limit-up               # 涨停板块统计
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config import last_trading_day, OUTPUT_DIR
from data_loader import load_snapshot


def sector_strength(date_str: str, group_col: str = '板块') -> pd.DataFrame:
    """
    按行业/板块统计当日平均涨跌幅、涨跌比、平均总分。

    参数:
        date_str:  'YYYY-MM-DD'
        group_col: 分组列名，'所属行业' | '同花顺概念' | '省份'

    返回:
        按平均涨幅降序的 DataFrame
    """
    df = load_snapshot(date_str)
    if df is None:
        return pd.DataFrame()

    if group_col not in df.columns:
        print(f"  ⚠️  列不存在: {group_col}  可用: {list(df.columns[:30])}")
        return pd.DataFrame()

    num_cols = ['价格变动 % 1天', '最高涨幅', '总分']
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    def _pct_change(s):
        return '价格变动 % 1天' in df.columns and s.name == '价格变动 % 1天'

    agg = {}
    if '价格变动 % 1天' in df.columns:
        agg['平均涨幅%']  = ('价格变动 % 1天', 'mean')
        agg['中位涨幅%']  = ('价格变动 % 1天', 'median')
        agg['涨跌比']     = ('价格变动 % 1天', lambda x: f"{(x > 0).sum()}/{(x < 0).sum()}")
    if '总分' in df.columns:
        agg['平均总分']   = ('总分', 'mean')
    if '最高涨幅' in df.columns:
        agg['最高涨幅%']  = ('最高涨幅', 'max')
    agg['股票数']         = ('证券代码', 'count')

    grouped = df.groupby(group_col).agg(**agg).reset_index()
    if '平均涨幅%' in grouped.columns:
        grouped['平均涨幅%'] = grouped['平均涨幅%'].round(2)
        grouped['中位涨幅%'] = grouped['中位涨幅%'].round(2)
        grouped = grouped.sort_values('平均涨幅%', ascending=False)

    return grouped.reset_index(drop=True)


def find_by_concept(date_str: str, keyword: str) -> pd.DataFrame:
    """查找快照中包含关键词的概念/行业股票。"""
    df = load_snapshot(date_str)
    if df is None:
        return pd.DataFrame()

    search_cols = ['同花顺概念', '所属行业', '细分行业', '描述']
    mask = pd.Series(False, index=df.index)
    for col in search_cols:
        if col in df.columns:
            mask |= df[col].astype(str).str.contains(keyword, na=False)

    result = df[mask].copy()
    if '价格变动 % 1天' in result.columns:
        result['价格变动 % 1天'] = pd.to_numeric(result['价格变动 % 1天'], errors='coerce')
        result = result.sort_values('价格变动 % 1天', ascending=False)

    return result.reset_index(drop=True)


def limit_up_stats(date_str: str) -> pd.DataFrame:
    """
    统计当日涨停板分布（按行业）。

    涨停判断：主板 价格变动%≥9.8%，创业板/科创板≥19.5%。
    """
    df = load_snapshot(date_str)
    if df is None:
        return pd.DataFrame()

    if '价格变动 % 1天' not in df.columns or '证券代码' not in df.columns:
        return pd.DataFrame()

    df['价格变动 % 1天'] = pd.to_numeric(df['价格变动 % 1天'], errors='coerce')

    def is_limit_up(row):
        code = str(row['证券代码'])
        pct = row['价格变动 % 1天']
        if pd.isna(pct):
            return False
        threshold = 19.5 if code.startswith('3') or code.startswith('68') else 9.8
        return pct >= threshold

    df['涨停'] = df.apply(is_limit_up, axis=1)
    limit_df = df[df['涨停']].copy()

    print(f"\n  🚀 {date_str} 涨停股票: {len(limit_df)} 只")

    if '所属行业' in limit_df.columns:
        sector_cnt = (limit_df.groupby('所属行业')['证券代码']
                      .count()
                      .sort_values(ascending=False)
                      .reset_index()
                      .rename(columns={'证券代码': '涨停数量'}))
        print(sector_cnt.head(20).to_string(index=False))

    return limit_df.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description='板块/概念分析')
    parser.add_argument('--date', '-d', default=None, help='日期 (YYYY-MM-DD)')
    parser.add_argument('--group', '-g', default='板块',
                        help='分组列 (默认: 板块)')
    parser.add_argument('--concept', '-c', default=None,
                        help='搜索概念关键词')
    parser.add_argument('--limit-up', '-l', action='store_true',
                        help='涨停板统计')
    parser.add_argument('--top', '-n', type=int, default=30,
                        help='显示前 N 个板块（默认 30）')
    parser.add_argument('--save', '-s', action='store_true')
    args = parser.parse_args()

    date_str = args.date or last_trading_day()
    print(f"📅 分析日期: {date_str}")
    print('=' * 55)

    if args.limit_up:
        result = limit_up_stats(date_str)
    elif args.concept:
        print(f"🔍 搜索概念/行业: {args.concept}")
        result = find_by_concept(date_str, args.concept)
        print(f"  找到 {len(result)} 只相关股票")
        cols = ['证券代码', '描述', '所属行业', '同花顺概念', '价格变动 % 1天', '总分']
        cols = [c for c in cols if c in result.columns]
        print(result[cols].head(args.top).to_string(index=False))
    else:
        print(f"📊 板块强弱排名 (按 {args.group} 分组):")
        result = sector_strength(date_str, args.group)
        print(result.head(args.top).to_string(index=False))

    if args.save and len(result) > 0:
        tag = 'limit_up' if args.limit_up else ('concept_' + args.concept if args.concept else 'sector')
        path = os.path.join(OUTPUT_DIR, f'{date_str}_{tag}.xlsx')
        result.to_excel(path, index=False)
        print(f"\n  💾 已保存: {path}")


if __name__ == '__main__':
    main()
