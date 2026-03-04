#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
淘股吧高手 - 最优买点策略挖掘
目标：找到利润最大化的买入条件组合
方法：多维度条件网格搜索 + 持仓天数优化
"""

import pandas as pd
import numpy as np
from itertools import product

# ── 加载全部交易数据 ──
xlsx_files = {
    '天牌': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_天牌_交易明细.xlsx',
    '独行侠令狐冲': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_独行侠令狐冲_交易明细.xlsx',
    '忘忧阁主': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_忘忧阁主_交易明细.xlsx',
    '低调内敛的朋': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_低调内敛的朋_交易明细.xlsx',
    '龙年大叔': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_龙年大叔_交易明细.xlsx',
}

all_trades = []
for name, f in xlsx_files.items():
    df = pd.read_excel(f)
    for col in ['持仓天数','单笔收益%','买入日开盘涨幅%','买入日最高涨幅%','买入日收盘涨幅%','前一日涨幅%']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    all_trades.append(df)

all_df = pd.concat(all_trades, ignore_index=True)

# 数据清洗：排除异常值(收益>100%或<-50%的大概率是OCR错误)
raw_count = len(all_df)
all_df = all_df[all_df['单笔收益%'].between(-50, 100)]
all_df = all_df.dropna(subset=['单笔收益%','买入日开盘涨幅%','前一日涨幅%','持仓天数'])
print(f"数据清洗: {raw_count}笔 → {len(all_df)}笔 (排除异常值和缺失)")
print(f"时间范围: {all_df['买入日期'].min()} ~ {all_df['卖出日期'].max()}")
print()

# ═══════════════════════════════════════════
# STEP 1: 单因子扫描 — 哪些因子对收益影响最大
# ═══════════════════════════════════════════
print("=" * 72)
print("STEP 1: 单因子扫描 — 什么条件买入收益最好？")
print("=" * 72)

def analyze_factor(df, col, bins, labels, min_n=15):
    """按分组统计收益"""
    results = []
    df['_group'] = pd.cut(df[col], bins=bins, labels=labels, right=True)
    for label in labels:
        sub = df[df['_group'] == label]
        if len(sub) >= min_n:
            results.append({
                '条件': label,
                '笔数': len(sub),
                '均值': sub['单笔收益%'].mean(),
                '中位': sub['单笔收益%'].median(),
                '胜率': (sub['单笔收益%']>0).mean()*100,
                '赚钱总和': sub[sub['单笔收益%']>0]['单笔收益%'].sum(),
                '亏钱总和': sub[sub['单笔收益%']<0]['单笔收益%'].sum(),
            })
    df.drop('_group', axis=1, inplace=True)
    return pd.DataFrame(results)

# 1.1 前一日涨幅
print("\n【前一日涨幅】")
r = analyze_factor(all_df, '前一日涨幅%', 
    [-999,-5,-2,0,2,5,8,10,999],
    ['<-5%', '-5~-2%', '-2~0%', '0~2%', '2~5%', '5~8%', '8~10%(涨停)', '>10%'])
for _, row in r.iterrows():
    print(f"  {row['条件']:<16} {row['笔数']:>4}笔  均值{row['均值']:>+6.2f}%  中位{row['中位']:>+6.2f}%  胜率{row['胜率']:>4.0f}%")

# 1.2 开盘涨幅
print("\n【买入日开盘涨幅】")
r = analyze_factor(all_df, '买入日开盘涨幅%',
    [-999,-3,-1,0,1,3,5,10,999],
    ['<-3%', '-3~-1%', '-1~0%', '0~1%', '1~3%', '3~5%', '5~10%', '>10%'])
for _, row in r.iterrows():
    print(f"  {row['条件']:<16} {row['笔数']:>4}笔  均值{row['均值']:>+6.2f}%  中位{row['中位']:>+6.2f}%  胜率{row['胜率']:>4.0f}%")

# 1.3 买入日内最高涨幅
print("\n【买入日内最高涨幅】")
r = analyze_factor(all_df, '买入日最高涨幅%',
    [-999,3,5,8,10,15,20,999],
    ['<3%', '3~5%', '5~8%', '8~10%', '10~15%', '15~20%', '>20%'])
for _, row in r.iterrows():
    print(f"  {row['条件']:<16} {row['笔数']:>4}笔  均值{row['均值']:>+6.2f}%  中位{row['中位']:>+6.2f}%  胜率{row['胜率']:>4.0f}%")

# 1.4 买入日收盘涨幅
print("\n【买入日收盘涨幅】")
r = analyze_factor(all_df, '买入日收盘涨幅%',
    [-999,-3,0,3,5,8,10,15,20,999],
    ['<-3%', '-3~0%', '0~3%', '3~5%', '5~8%', '8~10%(封板)', '10~15%', '15~20%(封板)', '>20%'])
for _, row in r.iterrows():
    print(f"  {row['条件']:<16} {row['笔数']:>4}笔  均值{row['均值']:>+6.2f}%  中位{row['中位']:>+6.2f}%  胜率{row['胜率']:>4.0f}%")

# 1.5 板块
print("\n【板块】")
for board in ['10%板', '20%板']:
    sub = all_df[all_df['板块']==board]
    print(f"  {board:<16} {len(sub):>4}笔  均值{sub['单笔收益%'].mean():>+6.2f}%  中位{sub['单笔收益%'].median():>+6.2f}%  胜率{(sub['单笔收益%']>0).mean()*100:>4.0f}%")

# 1.6 持仓天数
print("\n【持仓天数】")
r = analyze_factor(all_df, '持仓天数',
    [0,1,2,3,5,10,999],
    ['1天', '2天', '3天', '4-5天', '6-10天', '>10天'])
for _, row in r.iterrows():
    print(f"  {row['条件']:<16} {row['笔数']:>4}笔  均值{row['均值']:>+6.2f}%  中位{row['中位']:>+6.2f}%  胜率{row['胜率']:>4.0f}%")

# ═══════════════════════════════════════════
# STEP 2: 双因子交叉 — 找最佳组合
# ═══════════════════════════════════════════
print("\n" + "=" * 72)
print("STEP 2: 双因子交叉 — 最赚钱的条件组合")
print("=" * 72)

# 定义条件组
prev_day_bins = {
    '昨跌(<0%)': (all_df['前一日涨幅%'] < 0),
    '昨微涨(0~5%)': (all_df['前一日涨幅%'] >= 0) & (all_df['前一日涨幅%'] < 5),
    '昨大涨(>5%)': (all_df['前一日涨幅%'] >= 5),
}

open_bins = {
    '低开(<0%)': (all_df['买入日开盘涨幅%'] < 0),
    '平开(0~2%)': (all_df['买入日开盘涨幅%'] >= 0) & (all_df['买入日开盘涨幅%'] < 2),
    '高开(>2%)': (all_df['买入日开盘涨幅%'] >= 2),
}

board_bins = {
    '10%板': (all_df['板块'] == '10%板'),
    '20%板': (all_df['板块'] == '20%板'),
}

close_bins = {
    '收盘<5%': (all_df['买入日收盘涨幅%'] < 5),
    '收盘5~10%': (all_df['买入日收盘涨幅%'] >= 5) & (all_df['买入日收盘涨幅%'] < 10),
    '封板(>=10%)': (all_df['买入日收盘涨幅%'] >= 10),  # 近似封板
}

print("\n【前日涨幅 × 开盘涨幅】")
combo_results = []
for prev_name, prev_cond in prev_day_bins.items():
    for open_name, open_cond in open_bins.items():
        sub = all_df[prev_cond & open_cond]
        if len(sub) >= 15:
            avg = sub['单笔收益%'].mean()
            med = sub['单笔收益%'].median()
            win = (sub['单笔收益%']>0).mean()*100
            combo_results.append({
                '组合': f"{prev_name} + {open_name}",
                '笔数': len(sub), '均值': avg, '中位': med, '胜率': win,
            })

combo_results.sort(key=lambda x: x['均值'], reverse=True)
for r in combo_results:
    marker = ' ★' if r['均值'] > 2 else ''
    print(f"  {r['组合']:<30} {r['笔数']:>4}笔  均值{r['均值']:>+6.2f}%  中位{r['中位']:>+6.2f}%  胜率{r['胜率']:>4.0f}%{marker}")

print("\n【前日涨幅 × 收盘涨幅】")
combo_results2 = []
for prev_name, prev_cond in prev_day_bins.items():
    for close_name, close_cond in close_bins.items():
        sub = all_df[prev_cond & close_cond]
        if len(sub) >= 15:
            avg = sub['单笔收益%'].mean()
            med = sub['单笔收益%'].median()
            win = (sub['单笔收益%']>0).mean()*100
            combo_results2.append({
                '组合': f"{prev_name} + {close_name}",
                '笔数': len(sub), '均值': avg, '中位': med, '胜率': win,
            })

combo_results2.sort(key=lambda x: x['均值'], reverse=True)
for r in combo_results2:
    marker = ' ★' if r['均值'] > 2 else ''
    print(f"  {r['组合']:<30} {r['笔数']:>4}笔  均值{r['均值']:>+6.2f}%  中位{r['中位']:>+6.2f}%  胜率{r['胜率']:>4.0f}%{marker}")

# ═══════════════════════════════════════════
# STEP 3: 全量网格搜索 — 最优多条件组合
# ═══════════════════════════════════════════
print("\n" + "=" * 72)
print("STEP 3: 全量网格搜索 — TOP20最优买入条件组合")
print("=" * 72)

# 更精细的条件
prev_conditions = {
    '昨跌(<-2%)': all_df['前一日涨幅%'] < -2,
    '昨微跌(-2~0%)': (all_df['前一日涨幅%'] >= -2) & (all_df['前一日涨幅%'] < 0),
    '昨微涨(0~3%)': (all_df['前一日涨幅%'] >= 0) & (all_df['前一日涨幅%'] < 3),
    '昨涨(3~8%)': (all_df['前一日涨幅%'] >= 3) & (all_df['前一日涨幅%'] < 8),
    '昨涨停(>8%)': all_df['前一日涨幅%'] >= 8,
    '不限': pd.Series(True, index=all_df.index),
}

open_conditions = {
    '低开(<-1%)': all_df['买入日开盘涨幅%'] < -1,
    '平开(-1~1%)': (all_df['买入日开盘涨幅%'] >= -1) & (all_df['买入日开盘涨幅%'] < 1),
    '小高开(1~3%)': (all_df['买入日开盘涨幅%'] >= 1) & (all_df['买入日开盘涨幅%'] < 3),
    '高开(>3%)': all_df['买入日开盘涨幅%'] >= 3,
    '不限': pd.Series(True, index=all_df.index),
}

close_conditions = {
    '收盘<5%': all_df['买入日收盘涨幅%'] < 5,
    '收涨5~10%': (all_df['买入日收盘涨幅%'] >= 5) & (all_df['买入日收盘涨幅%'] < 10),
    '封板(≥10%)': all_df['买入日收盘涨幅%'] >= 10,
    '不限': pd.Series(True, index=all_df.index),
}

board_conditions = {
    '10%板': all_df['板块'] == '10%板',
    '20%板': all_df['板块'] == '20%板',
    '不限': pd.Series(True, index=all_df.index),
}

MIN_SAMPLES = 20  # 最少样本量

all_combos = []
for prev_name, prev_cond in prev_conditions.items():
    for open_name, open_cond in open_conditions.items():
        for close_name, close_cond in close_conditions.items():
            for board_name, board_cond in board_conditions.items():
                # 跳过全部"不限"的
                if prev_name == '不限' and open_name == '不限' and close_name == '不限' and board_name == '不限':
                    continue
                
                mask = prev_cond & open_cond & close_cond & board_cond
                sub = all_df[mask]
                
                if len(sub) >= MIN_SAMPLES:
                    avg = sub['单笔收益%'].mean()
                    med = sub['单笔收益%'].median()
                    win = (sub['单笔收益%']>0).mean()*100
                    total_profit = sub['单笔收益%'].sum()
                    
                    # 计算 "利润分" = 均值 × sqrt(笔数)，平衡收益率和样本量
                    profit_score = avg * np.sqrt(len(sub))
                    
                    conds = []
                    if prev_name != '不限': conds.append(prev_name)
                    if open_name != '不限': conds.append(open_name)
                    if close_name != '不限': conds.append(close_name)
                    if board_name != '不限': conds.append(board_name)
                    
                    all_combos.append({
                        '条件': ' + '.join(conds),
                        '笔数': len(sub),
                        '均值': avg,
                        '中位': med,
                        '胜率': win,
                        '利润总和': total_profit,
                        '利润分': profit_score,
                    })

# 按利润分排序（平衡收益率和样本量）
all_combos.sort(key=lambda x: x['利润分'], reverse=True)

print(f"\n共搜索 {len(all_combos)} 种有效组合（≥{MIN_SAMPLES}笔）")
print(f"\n{'排名':>3} {'利润分':>7} {'笔数':>5} {'均值':>7} {'中位':>7} {'胜率':>5} {'利润和':>8}  条件")
print(f"{'-'*90}")
for i, r in enumerate(all_combos[:25], 1):
    print(f"  {i:>2}. {r['利润分']:>6.1f} {r['笔数']:>4}笔 {r['均值']:>+6.2f}% {r['中位']:>+6.2f}% {r['胜率']:>4.0f}% {r['利润总和']:>+7.1f}%  {r['条件']}")

# ═══════════════════════════════════════════
# STEP 4: TOP策略详细分析 + 月度一致性
# ═══════════════════════════════════════════
print("\n" + "=" * 72)
print("STEP 4: TOP5策略月度一致性检验")
print("=" * 72)

all_df['买入月'] = all_df['买入日期'].astype(str).str[:6]
months = sorted(all_df['买入月'].unique())

# 按利润分取TOP5
top5_combos = all_combos[:5]

for i, combo in enumerate(top5_combos, 1):
    print(f"\n{'─'*60}")
    print(f"TOP{i}: {combo['条件']}")
    print(f"总计: {combo['笔数']}笔  均值{combo['均值']:+.2f}%  胜率{combo['胜率']:.0f}%  利润和{combo['利润总和']:+.1f}%")
    print(f"{'─'*60}")
    
    # 重新筛选数据
    # 需要重建条件...用名称反查比较麻烦，换个方式
    # 直接用排名对应的mask重新算月度
    cond_parts = combo['条件'].split(' + ')
    mask = pd.Series(True, index=all_df.index)
    
    all_named_conds = {}
    all_named_conds.update(prev_conditions)
    all_named_conds.update(open_conditions)
    all_named_conds.update(close_conditions)
    all_named_conds.update(board_conditions)
    
    for part in cond_parts:
        if part in all_named_conds:
            mask = mask & all_named_conds[part]
    
    sub = all_df[mask]
    
    positive_months = 0
    total_months = 0
    print(f"  {'月份':<8} {'笔数':>4} {'均值':>7} {'中位':>7} {'胜率':>5} {'利润和':>8}")
    for m in months:
        msub = sub[sub['买入月'] == m]
        if len(msub) > 0:
            avg = msub['单笔收益%'].mean()
            med = msub['单笔收益%'].median()
            win = (msub['单笔收益%']>0).mean()*100
            total = msub['单笔收益%'].sum()
            total_months += 1
            if total > 0:
                positive_months += 1
            marker = '✅' if total > 0 else '❌'
            print(f"  {m:<8} {len(msub):>3}笔 {avg:>+6.2f}% {med:>+6.2f}% {win:>4.0f}% {total:>+7.1f}% {marker}")
    
    print(f"  月度一致性: {positive_months}/{total_months}月正收益 ({positive_months/total_months*100:.0f}%)")

# ═══════════════════════════════════════════
# STEP 5: 最终结论
# ═══════════════════════════════════════════
print("\n" + "=" * 72)
print("STEP 5: 最终推荐策略")  
print("=" * 72)

# 找 利润分>20 且 月度一致性好的
print("\n筛选标准: 利润分>15 + 均值>1.5% + 笔数≥25 + 胜率≥45%")
print()

qualified = [c for c in all_combos if c['均值'] > 1.5 and c['笔数'] >= 25 and c['胜率'] >= 45 and c['利润分'] > 15]
qualified.sort(key=lambda x: x['利润分'], reverse=True)

print(f"符合条件的策略: {len(qualified)}个")
print(f"\n{'排名':>3} {'利润分':>7} {'笔数':>5} {'均值':>7} {'胜率':>5} {'利润和':>8}  条件")
for i, r in enumerate(qualified[:15], 1):
    print(f"  {i:>2}. {r['利润分']:>6.1f} {r['笔数']:>4}笔 {r['均值']:>+6.2f}% {r['胜率']:>4.0f}% {r['利润总和']:>+7.1f}%  {r['条件']}")

print("\n" + "=" * 72)
