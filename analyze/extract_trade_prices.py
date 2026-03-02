"""
analyze/extract_trade_prices.py — 提取只核大学生每笔交易的买入/卖出价格

数据来源:
  - output/tgb_zhihedaxuesheng_买卖记录.csv   (操作日期、股票代码/名称)
  - output/tgb_zhihedaxuesheng_OCR持仓数据.csv (成本价、现价)

逻辑:
  买入价格 → OCR持仓中"成本价"（买入当天或之后最近持仓记录）
  卖出价格 → OCR持仓中"现价"（卖出当天"已清仓"记录的现价，或前一天持仓的现价）

用法:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 analyze/extract_trade_prices.py
"""
from __future__ import annotations

import os
import sys
import re
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

# ============================================================
# 路径
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

TRADE_CSV = os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_买卖记录.csv')
OCR_CSV   = os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_OCR持仓数据.csv')
OUT_XLSX  = os.path.join(OUTPUT_DIR, 'tgb_只核大学生_交易价格明细.xlsx')


# ============================================================
# 辅助：规范化股票名称（去除OCR噪音）
# ============================================================
# OCR 中名称可能与买卖记录中不完全一致，需要模糊匹配
_NOISE_NAMES = {
    '持仓管理', '持仓资讯', '淘特仓资讯', '海限吧', '淘限吧', '淘阳吧',
    '淘批量买入', '汽量买入', '汽批量实入', '行情愛', '方修淘股吧',
    '市值今', '市值合', '持仓分时', '合答理', '海灣過', '海我滥买入',
    '白立併日', '涵行壮夂', '海頭吧', '图股', '淘胞', '淘服吧',
    '溷胞', '溜股', '溷股', '酱灣', '海級翻可台', '渝肪', '密肪',
}


def normalize_name(name: str) -> str:
    """规范化股票名称：去掉 *ST 前缀、空格等"""
    if not isinstance(name, str):
        return ''
    name = name.strip()
    # 去掉 *ST / ST 前缀
    name = re.sub(r'^\*?ST\s*', '', name)
    # 去掉一些OCR后缀噪音
    for suffix in ['科技', '股份', '新材', '科', '新能源']:
        pass  # 不裁剪，保持原名
    return name


def is_noise(name: str) -> bool:
    """判断是否是OCR噪音行"""
    if not isinstance(name, str):
        return True
    name = name.strip()
    if name in _NOISE_NAMES:
        return True
    if len(name) <= 1:
        return True
    return False


# ============================================================
# 名称匹配：OCR名称 → 买卖记录名称
# ============================================================
def build_name_mapping(trade_names: set, ocr_names: set) -> dict:
    """
    构建 OCR股票名称 → 买卖记录股票名称 的映射。
    优先精确匹配，然后尝试模糊匹配。
    """
    mapping = {}

    # 精确匹配
    for oname in ocr_names:
        if oname in trade_names:
            mapping[oname] = oname

    # 处理 *ST / ST 差异
    trade_norm = {}
    for tname in trade_names:
        norm = re.sub(r'^\*?ST\s*', '', tname)
        trade_norm[norm] = tname

    for oname in ocr_names:
        if oname in mapping:
            continue
        onorm = re.sub(r'^\*?ST\s*', '', oname)
        if onorm in trade_norm:
            mapping[oname] = trade_norm[onorm]

    # OCR 可能截断或有后缀差异，尝试包含匹配
    for oname in ocr_names:
        if oname in mapping or is_noise(oname):
            continue
        # OCR名称包含在交易名称中 或 反过来
        for tname in trade_names:
            if len(oname) >= 2 and (oname in tname or tname in oname):
                mapping[oname] = tname
                break
        # 特殊映射
        special = {
            '海南金盘智': '金盘科技',
            '华海诚科新': '华海诚科',
            '芯原微电子': '芯原股份',
            '微导纳米科': '微导纳米',
            '中微半导体': '中微公司',
            '华虹半导体': '华虹公司',
            '厦钨新能源': '厦钨新能',
            '上海硅产业': '沪硅产业',
            '新光光电科': '新光光电',
            '南方模式生': '南方泵业',  # OCR可能误读
            '航天环宇科': '航天环宇',
            '云天励飞股': '云天励飞',
            '开普云信息': '开普云',
            '通润装备': '通润装备',
        }
        if oname in special and special[oname] in trade_names:
            mapping[oname] = special[oname]

    return mapping


# ============================================================
# 主逻辑
# ============================================================
def main():
    print("📖 读取买卖记录...")
    df_trade = pd.read_csv(TRADE_CSV)
    print("  {} 条记录".format(len(df_trade)))

    print("📖 读取OCR持仓数据...")
    df_ocr = pd.read_csv(OCR_CSV)
    print("  {} 条记录".format(len(df_ocr)))

    # 规范化日期格式：都转为 YYYY-MM-DD
    df_trade['日期'] = pd.to_datetime(df_trade['日期']).dt.strftime('%Y-%m-%d')

    # OCR日期可能是 YYYYMMDD 或 YYYY-MM-DD
    df_ocr['日期'] = pd.to_datetime(df_ocr['日期'].astype(str), format='mixed').dt.strftime('%Y-%m-%d')

    # 过滤OCR噪音行
    df_ocr = df_ocr[~df_ocr['股票名称'].apply(is_noise)].copy()
    print("  过滤噪音后: {} 条OCR记录".format(len(df_ocr)))

    # 数值列
    for col in ['成本价', '现价']:
        df_ocr[col] = pd.to_numeric(df_ocr[col], errors='coerce')

    # 构建名称映射
    trade_names = set(df_trade['股票名称'].dropna().unique())
    ocr_names   = set(df_ocr['股票名称'].dropna().unique())
    name_map    = build_name_mapping(trade_names, ocr_names)

    # 将OCR名称映射到交易名称
    df_ocr['匹配名称'] = df_ocr['股票名称'].map(name_map)

    # 打印未匹配的OCR名称
    unmatched = df_ocr[df_ocr['匹配名称'].isna()]['股票名称'].unique()
    if len(unmatched) > 0:
        print("\n  ⚠️  以下OCR股票名称未匹配到交易记录:")
        for n in sorted(unmatched):
            print("    - {}".format(n))
    print()

    # -----------------------------------------------------------
    # 构建查询结构：(日期, 匹配名称) → OCR记录列表
    # -----------------------------------------------------------
    ocr_index = {}
    for _, row in df_ocr.iterrows():
        key = (row['日期'], row['匹配名称'])
        if pd.notna(row['匹配名称']):
            ocr_index.setdefault(key, []).append(row)

    # 获取所有OCR日期（排序）
    ocr_dates = sorted(df_ocr['日期'].unique())

    def find_nearby_dates(target_date: str, direction: str = 'forward', n: int = 5) -> list:
        """查找目标日期前后的OCR日期"""
        dates = []
        if direction == 'forward':
            dates = [d for d in ocr_dates if d >= target_date][:n]
        else:
            dates = [d for d in ocr_dates if d <= target_date][-n:]
            dates.reverse()
        return dates

    # -----------------------------------------------------------
    # 为每笔交易匹配价格
    # -----------------------------------------------------------
    results = []
    buy_matched = 0
    sell_matched = 0
    buy_total = 0
    sell_total = 0

    for _, trade in df_trade.iterrows():
        op   = trade['操作']
        date = trade['日期']
        code = trade['股票代码']
        name = trade['股票名称']

        if not isinstance(name, str) or not isinstance(op, str):
            continue

        rec = {
            '操作':       op,
            '日期':       date,
            '股票代码':   code,
            '股票名称':   name,
            '买入日期':   trade.get('买入日期', ''),
            '持仓天数':   trade.get('持仓天数', ''),
            '操作后总资产(万)': trade.get('操作后总资产(万)', ''),
            '当日收益(%)': trade.get('当日收益(%)', ''),
            '累计收益(%)': trade.get('累计收益(%)', ''),
            '仓位(%)':    trade.get('仓位(%)', ''),
            '买入价格':   None,
            '卖出价格':   None,
            '价格来源':   '',
        }

        if op == '买入':
            buy_total += 1
            # 在买入当天或之后的OCR记录中找"成本价"
            for try_date in find_nearby_dates(date, 'forward', 10):
                key = (try_date, name)
                if key in ocr_index:
                    for ocr_row in ocr_index[key]:
                        cost = ocr_row.get('成本价')
                        if pd.notna(cost) and cost > 0:
                            rec['买入价格'] = round(cost, 3)
                            rec['价格来源'] = 'OCR成本价({})'.format(try_date)
                            buy_matched += 1
                            break
                    if rec['买入价格'] is not None:
                        break

        elif op == '卖出':
            sell_total += 1
            # 方法1：卖出当天的"已清仓"记录的"现价"
            key = (date, name)
            if key in ocr_index:
                for ocr_row in ocr_index[key]:
                    status = str(ocr_row.get('状态', ''))
                    price  = ocr_row.get('现价')
                    if '清仓' in status and pd.notna(price) and price > 0:
                        rec['卖出价格'] = round(price, 3)
                        rec['价格来源'] = 'OCR已清仓现价({})'.format(date)
                        sell_matched += 1
                        break

            # 方法2：如果没找到，在前一天的持仓记录中找"现价"
            if rec['卖出价格'] is None:
                for try_date in find_nearby_dates(date, 'backward', 5):
                    if try_date == date:
                        # 也尝试当天持仓中的现价
                        key2 = (try_date, name)
                        if key2 in ocr_index:
                            for ocr_row in ocr_index[key2]:
                                price = ocr_row.get('现价')
                                if pd.notna(price) and price > 0:
                                    rec['卖出价格'] = round(price, 3)
                                    rec['价格来源'] = 'OCR持仓现价({})'.format(try_date)
                                    sell_matched += 1
                                    break
                    else:
                        key2 = (try_date, name)
                        if key2 in ocr_index:
                            for ocr_row in ocr_index[key2]:
                                price = ocr_row.get('现价')
                                if pd.notna(price) and price > 0:
                                    rec['卖出价格'] = round(price, 3)
                                    rec['价格来源'] = 'OCR前日现价({})'.format(try_date)
                                    sell_matched += 1
                                    break
                    if rec['卖出价格'] is not None:
                        break

        results.append(rec)

    # -----------------------------------------------------------
    # 配对买卖：把卖出记录的买入价格也填上
    # -----------------------------------------------------------
    # 构建买入价格索引：(股票名称, 买入日期) → 买入价格
    buy_prices = {}
    for r in results:
        if r['操作'] == '买入' and r['买入价格'] is not None:
            buy_prices[(r['股票名称'], r['日期'])] = r['买入价格']

    for r in results:
        if r['操作'] == '卖出':
            buy_date = r.get('买入日期', '')
            if isinstance(buy_date, str) and buy_date:
                key = (r['股票名称'], buy_date)
                if key in buy_prices:
                    r['买入价格'] = buy_prices[key]

    # -----------------------------------------------------------
    # 计算盈亏
    # -----------------------------------------------------------
    for r in results:
        if r['操作'] == '卖出' and r['买入价格'] and r['卖出价格']:
            bp = r['买入价格']
            sp = r['卖出价格']
            if bp > 0:
                r['单笔盈亏(%)'] = round((sp - bp) / bp * 100, 2)
            else:
                r['单笔盈亏(%)'] = None
        else:
            r['单笔盈亏(%)'] = None

    # -----------------------------------------------------------
    # 输出
    # -----------------------------------------------------------
    result_df = pd.DataFrame(results)

    print("=" * 70)
    print("📊 匹配结果统计:")
    print("  买入记录: {}/{} 匹配到价格 ({:.1f}%)".format(
        buy_matched, buy_total, buy_matched / max(buy_total, 1) * 100))
    print("  卖出记录: {}/{} 匹配到价格 ({:.1f}%)".format(
        sell_matched, sell_total, sell_matched / max(sell_total, 1) * 100))

    # 统计有完整买卖价格的卖出记录
    complete = result_df[
        (result_df['操作'] == '卖出') &
        result_df['买入价格'].notna() &
        result_df['卖出价格'].notna()
    ]
    print("  完整配对（有买入+卖出价格）: {} 笔".format(len(complete)))

    if len(complete) > 0:
        pnl = complete['单笔盈亏(%)']
        print("\n📈 盈亏统计（完整配对）:")
        print("  平均盈亏: {:.2f}%".format(pnl.mean()))
        print("  胜率: {:.1f}%".format((pnl > 0).mean() * 100))
        print("  最大盈利: {:.2f}%".format(pnl.max()))
        print("  最大亏损: {:.2f}%".format(pnl.min()))

    # 保存
    # 调整列顺序
    col_order = [
        '操作', '日期', '股票代码', '股票名称', '买入日期', '持仓天数',
        '买入价格', '卖出价格', '单笔盈亏(%)',
        '操作后总资产(万)', '当日收益(%)', '累计收益(%)', '仓位(%)',
        '价格来源',
    ]
    for c in col_order:
        if c not in result_df.columns:
            result_df[c] = None
    result_df = result_df[col_order]

    result_df.to_excel(OUT_XLSX, index=False)
    print("\n💾 已保存: {}".format(OUT_XLSX))

    # 控制台预览
    print("\n📋 卖出记录预览（前30条）:")
    sell_df = result_df[result_df['操作'] == '卖出'][
        ['日期', '股票名称', '买入日期', '持仓天数', '买入价格', '卖出价格', '单笔盈亏(%)']
    ].head(30)
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.width', 200)
    print(sell_df.to_string(index=False))


if __name__ == '__main__':
    main()
