#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
只核大学生 - 平均持仓天数统计
数据来源：淘股吧交易记录
"""

import pandas as pd
import numpy as np

# ── 加载数据 ──
trades = pd.read_csv('/Users/tq/PycharmProjects/stocks_analysis/output/tgb_zhihedaxuesheng_买卖记录.csv')

# 只看卖出记录（有持仓天数）
sells = trades[trades['操作'] == '卖出'].copy()
sells['持仓天数'] = pd.to_numeric(sells['持仓天数'], errors='coerce')
sells = sells.dropna(subset=['持仓天数'])
sells['持仓天数'] = sells['持仓天数'].astype(int)

print("=" * 60)
print("只核大学生 持仓天数统计")
print("=" * 60)
print(f"统计样本：{len(sells)} 笔卖出交易")
print(f"时间范围：{sells['买入日期'].min()} ~ {sells['日期'].max()}")
print()

# ── 基本统计 ──
print("【基本统计】")
print(f"  平均持仓天数：{sells['持仓天数'].mean():.2f} 天")
print(f"  中位数持仓：  {sells['持仓天数'].median():.1f} 天")
print(f"  最短持仓：    {sells['持仓天数'].min()} 天")
print(f"  最长持仓：    {sells['持仓天数'].max()} 天")
print(f"  标准差：      {sells['持仓天数'].std():.2f} 天")
print()

# ── 持仓天数分布 ──
print("【持仓天数分布】")
bins = [0, 1, 2, 3, 5, 10, 20, 50, 100, 999]
labels = ['T+1(1天)', 'T+2(2天)', 'T+3(3天)', '4-5天', '6-10天', '11-20天', '21-50天', '51-100天', '100天+']
sells['持仓区间'] = pd.cut(sells['持仓天数'], bins=bins, labels=labels, right=True)

dist = sells['持仓区间'].value_counts().sort_index()
total = len(sells)
print(f"  {'区间':<12} {'笔数':>6} {'占比':>8} {'累计':>8}")
print(f"  {'-'*40}")
cumsum = 0
for label in labels:
    count = dist.get(label, 0)
    pct = count / total * 100
    cumsum += pct
    bar = '█' * int(pct / 2)
    print(f"  {label:<12} {count:>6} {pct:>7.1f}% {cumsum:>7.1f}% {bar}")
print()

# ── 按月统计平均持仓 ──
sells['卖出月'] = pd.to_datetime(sells['日期']).dt.strftime('%Y-%m')
monthly = sells.groupby('卖出月').agg(
    笔数=('持仓天数', 'count'),
    平均持仓=('持仓天数', 'mean'),
    中位数=('持仓天数', 'median'),
    最长=('持仓天数', 'max'),
).reset_index()

print("【按月统计】")
print(f"  {'月份':<10} {'笔数':>5} {'平均':>7} {'中位数':>7} {'最长':>5}")
print(f"  {'-'*40}")
for _, row in monthly.iterrows():
    print(f"  {row['卖出月']:<10} {row['笔数']:>5} {row['平均持仓']:>6.1f}天 {row['中位数']:>6.1f}天 {row['最长']:>4}天")
print(f"  {'-'*40}")
print(f"  {'全期合计':<10} {len(sells):>5} {sells['持仓天数'].mean():>6.1f}天 {sells['持仓天数'].median():>6.1f}天 {sells['持仓天数'].max():>4}天")
print()

# ── 最长持仓 TOP10 ──
print("【最长持仓 TOP10】")
top10 = sells.nlargest(10, '持仓天数')[['买入日期', '日期', '股票代码', '股票名称', '持仓天数']]
for i, (_, row) in enumerate(top10.iterrows(), 1):
    print(f"  {i:>2}. {row['股票名称']:<8} {row['持仓天数']:>3}天  ({row['买入日期']} → {row['日期']})")
print()

# ── T+1 vs 隔夜持仓 ──
t1_count = (sells['持仓天数'] == 1).sum()
overnight_count = (sells['持仓天数'] >= 2).sum()
print("【T+1 vs 隔夜】")
print(f"  T+1（当天买次日卖）：{t1_count} 笔 ({t1_count/total*100:.1f}%)")
print(f"  隔夜持仓（≥2天）：  {overnight_count} 笔 ({overnight_count/total*100:.1f}%)")
print(f"  T+1平均占比超半 → {'是' if t1_count > total/2 else '否'}，风格偏{'短线' if sells['持仓天数'].mean() <= 3 else '波段'}")
print()
print("=" * 60)
