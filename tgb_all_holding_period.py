#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
淘股吧高手 - 平均持仓天数统计（全部6人对比）
"""

import pandas as pd
import numpy as np

# ── 加载数据 ──
# 只核大学生用买卖记录CSV（卖出行有持仓天数）
zhihe = pd.read_csv('/Users/tq/PycharmProjects/stocks_analysis/output/tgb_zhihedaxuesheng_买卖记录.csv')
zhihe = zhihe[zhihe['操作'] == '卖出'].copy()
zhihe['持仓天数'] = pd.to_numeric(zhihe['持仓天数'], errors='coerce')
zhihe = zhihe.dropna(subset=['持仓天数'])
zhihe = zhihe[['日期', '股票代码', '股票名称', '持仓天数', '买入日期']].copy()
zhihe.insert(0, '高手名', '只核大学生')
zhihe.rename(columns={'买入日期': '买入日期_raw', '日期': '卖出日期_raw'}, inplace=True)

# 其他5人用交易明细xlsx
others = {}
xlsx_files = {
    '天牌': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_天牌_交易明细.xlsx',
    '独行侠令狐冲': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_独行侠令狐冲_交易明细.xlsx',
    '忘忧阁主': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_忘忧阁主_交易明细.xlsx',
    '低调内敛的朋': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_低调内敛的朋_交易明细.xlsx',
    '龙年大叔': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_龙年大叔_交易明细.xlsx',
}

all_data = {}

# 处理只核大学生
zhihe['持仓天数'] = zhihe['持仓天数'].astype(int)
all_data['只核大学生'] = zhihe['持仓天数'].values

# 处理其他5人
for name, f in xlsx_files.items():
    df = pd.read_excel(f)
    df['持仓天数'] = pd.to_numeric(df['持仓天数'], errors='coerce')
    df = df.dropna(subset=['持仓天数'])
    df['持仓天数'] = df['持仓天数'].astype(int)
    all_data[name] = df['持仓天数'].values

# ── 总览对比 ──
print("=" * 72)
print("淘股吧高手 持仓天数对比统计")
print("=" * 72)

print()
print(f"{'高手':<10} {'笔数':>5} {'平均':>7} {'中位':>5} {'最短':>4} {'最长':>4} {'标准差':>6} {'≤2天%':>7} {'≤3天%':>7}")
print(f"{'-'*66}")

# 按平均持仓排序
sorted_names = sorted(all_data.keys(), key=lambda n: np.mean(all_data[n]))

for name in sorted_names:
    days = all_data[name]
    n = len(days)
    avg = np.mean(days)
    med = np.median(days)
    mn = np.min(days)
    mx = np.max(days)
    std = np.std(days)
    pct_le2 = (days <= 2).sum() / n * 100
    pct_le3 = (days <= 3).sum() / n * 100
    print(f"  {name:<10} {n:>4} {avg:>6.1f}天 {med:>4.0f}天 {mn:>3}天 {mx:>3}天 {std:>5.1f}天 {pct_le2:>6.1f}% {pct_le3:>6.1f}%")

print()

# ── 每人详细分布 ──
bins = [0, 1, 2, 3, 5, 10, 20, 50, 100, 999]
labels = ['T+1(1天)', 'T+2(2天)', 'T+3(3天)', '4-5天', '6-10天', '11-20天', '21-50天', '51-100天', '100天+']

for name in sorted_names:
    days = all_data[name]
    total = len(days)
    
    print(f"{'─'*50}")
    print(f"【{name}】 {total}笔  平均{np.mean(days):.1f}天  中位{np.median(days):.0f}天")
    print(f"{'─'*50}")
    
    cats = pd.cut(days, bins=bins, labels=labels, right=True)
    dist = pd.Series(cats).value_counts()
    
    cumsum = 0
    for label in labels:
        count = dist.get(label, 0)
        if count == 0:
            continue
        pct = count / total * 100
        cumsum += pct
        bar = '█' * int(pct / 2)
        print(f"  {label:<12} {count:>5} {pct:>6.1f}% {cumsum:>7.1f}% {bar}")
    print()

# ── 风格分类 ──
print("=" * 72)
print("【风格分类总结】")
print("=" * 72)
for name in sorted_names:
    days = all_data[name]
    avg = np.mean(days)
    med = np.median(days)
    t1_pct = (days == 1).sum() / len(days) * 100
    t2_pct = (days == 2).sum() / len(days) * 100
    le3_pct = (days <= 3).sum() / len(days) * 100
    gt10_pct = (days > 10).sum() / len(days) * 100
    
    if avg <= 2.5 and le3_pct > 85:
        style = "⚡ 极致超短(T+2为主)"
    elif avg <= 4 and le3_pct > 60:
        style = "🔥 超短线(1-3天)"
    elif avg <= 7:
        style = "📊 短线波段(3-7天)"
    elif avg <= 15:
        style = "📈 波段(1-2周)"
    else:
        style = "🏢 中线(2周+)"
    
    print(f"  {name:<12} 均{avg:.1f}天 中位{med:.0f}天  {style}")
    
    # 核心持仓区间
    mode_day = pd.Series(days).mode()[0]
    print(f"    {'':>12} 最常见持仓={mode_day}天  T+1={t1_pct:.0f}%  T+2={t2_pct:.0f}%  ≤3天={le3_pct:.0f}%  ＞10天={gt10_pct:.0f}%")
    print()

print("=" * 72)
