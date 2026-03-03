#!/usr/bin/env python3
"""
Step 2: 淘股吧6位高手深度分析 + 融合策略回测
读取 Step 1 生成的 tgb_全部高手_交易汇总.xlsx，做全维度分析
"""
import os, sys, glob, warnings
import pandas as pd
import numpy as np
from collections import defaultdict

warnings.filterwarnings('ignore')

PROJECT_ROOT = '/Users/tq/PycharmProjects/stocks_analysis'
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, 'output')
KLINE_DIR    = '/Users/tq/Documents/quant_data/miniqmt_data/1d'

# ─── 加载数据 ─────────────────────────────────────────
print("加载交易汇总数据...")
all_df = pd.read_excel(os.path.join(OUTPUT_DIR, 'tgb_全部高手_交易汇总.xlsx'))
print(f"总计 {len(all_df)} 笔交易, 列: {list(all_df.columns)}")

# 也加载各高手收益明细（获取仓位/持股数等）
BATCH_DIR = os.path.join(OUTPUT_DIR, 'tgb_batch')
rev_data = {}
for name, mid in [('天牌','802'),('低调内敛的朋','802'),('忘忧阁主','802'),('独行侠令狐冲','802'),('龙年大叔','858')]:
    rev = pd.read_csv(os.path.join(BATCH_DIR, f'{name}_比赛{mid}_收益明细.csv'), encoding='utf-8-sig')
    rev_data[name] = rev
# 只核大学生
zh_rev = pd.read_csv(os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_收益明细.csv'), encoding='utf-8-sig')
rev_data['只核大学生'] = zh_rev

def is_gem(code):
    c = str(code)
    return c.startswith('300') or c.startswith('688') or c.startswith('301')

# ─── 分析每位高手 ─────────────────────────────────────
def analyze_master(name, df, rev):
    """全维度分析一位高手，返回markdown字符串"""
    r = []
    valid = df.dropna(subset=['单笔收益%'])
    n = len(valid)
    if n == 0:
        return f"无有效交易数据\n"
    
    # ──────── 概览 ────────
    avg_ret  = valid['单笔收益%'].mean()
    med_ret  = valid['单笔收益%'].median()
    win_rate = (valid['单笔收益%'] > 0).mean() * 100
    winners  = valid[valid['单笔收益%'] > 0]
    losers   = valid[valid['单笔收益%'] <= 0]
    pl_ratio = abs(winners['单笔收益%'].mean() / losers['单笔收益%'].mean()) if len(losers) > 0 and losers['单笔收益%'].mean() != 0 else float('inf')
    total_ret = valid['单笔收益%'].sum()
    
    r.append(f"**概览**: {n}笔交易, 单笔均值 **{avg_ret:+.2f}%**, 中位数 {med_ret:+.2f}%, 胜率 **{win_rate:.1f}%**, 盈亏比 **{pl_ratio:.2f}**, 简单加总 {total_ret:+.1f}%\n")
    
    # ──────── A. 选股特征 ────────
    r.append("### A. 选股特征\n")
    
    # A1. 前一日涨幅
    prev = valid.dropna(subset=['前一日涨幅%'])
    if len(prev) > 0:
        r.append("#### A1. 前一日涨幅分布\n")
        bins = [
            ('涨停追板(>8%)',  prev['前一日涨幅%'] > 8),
            ('追大涨(5~8%)',   (prev['前一日涨幅%'] > 5) & (prev['前一日涨幅%'] <= 8)),
            ('小涨(0~5%)',     (prev['前一日涨幅%'] >= 0) & (prev['前一日涨幅%'] <= 5)),
            ('低吸(<0%)',      prev['前一日涨幅%'] < 0),
        ]
        r.append("| 类型 | 笔数 | 占比 | 该类平均收益% | 该类胜率 |")
        r.append("|------|------|------|-------------|---------|")
        for label, mask in bins:
            sub = prev[mask]
            cnt = len(sub)
            pct = cnt / len(prev) * 100
            sub_ret = sub['单笔收益%'].mean() if cnt > 0 else 0
            sub_wr  = (sub['单笔收益%'] > 0).mean() * 100 if cnt > 0 else 0
            r.append(f"| {label} | {cnt} | {pct:.1f}% | {sub_ret:+.2f}% | {sub_wr:.1f}% |")
        r.append(f"\n前日涨幅均值: **{prev['前一日涨幅%'].mean():.2f}%**, 中位数: {prev['前一日涨幅%'].median():.2f}%\n")
    
    # A2. 买入日开盘涨幅
    opn = valid.dropna(subset=['买入日开盘涨幅%'])
    if len(opn) > 0:
        r.append("#### A2. 买入日开盘涨幅\n")
        bins2 = [
            ('一字板(>8%)',     opn['买入日开盘涨幅%'] > 8),
            ('中幅高开(3~8%)', (opn['买入日开盘涨幅%'] > 3) & (opn['买入日开盘涨幅%'] <= 8)),
            ('小幅高开(0~3%)', (opn['买入日开盘涨幅%'] >= 0) & (opn['买入日开盘涨幅%'] <= 3)),
            ('低开(<0%)',      opn['买入日开盘涨幅%'] < 0),
        ]
        r.append("| 类型 | 笔数 | 占比 | 该类平均收益% | 该类胜率 |")
        r.append("|------|------|------|-------------|---------|")
        for label, mask in bins2:
            sub = opn[mask]
            cnt = len(sub)
            pct = cnt / len(opn) * 100
            sub_ret = sub['单笔收益%'].mean() if cnt > 0 else 0
            sub_wr  = (sub['单笔收益%'] > 0).mean() * 100 if cnt > 0 else 0
            r.append(f"| {label} | {cnt} | {pct:.1f}% | {sub_ret:+.2f}% | {sub_wr:.1f}% |")
        r.append(f"\n开盘涨幅均值: **{opn['买入日开盘涨幅%'].mean():.2f}%**, 中位数: {opn['买入日开盘涨幅%'].median():.2f}%\n")
    
    # A3. 买入日最高涨幅
    hi = valid.dropna(subset=['买入日最高涨幅%'])
    if len(hi) > 0:
        r.append("#### A3. 买入日盘中最高涨幅\n")
        d14 = (hi['买入日最高涨幅%'] >= 14).sum()
        d10 = ((hi['买入日最高涨幅%'] >= 10) & (hi['买入日最高涨幅%'] < 14)).sum()
        d5  = ((hi['买入日最高涨幅%'] >= 5)  & (hi['买入日最高涨幅%'] < 10)).sum()
        dlt5 = (hi['买入日最高涨幅%'] < 5).sum()
        tot = len(hi)
        r.append("| 类型 | 笔数 | 占比 |")
        r.append("|------|------|------|")
        r.append(f"| D14+(≥14%) | {d14} | {d14/tot*100:.1f}% |")
        r.append(f"| D10-14(10~14%) | {d10} | {d10/tot*100:.1f}% |")
        r.append(f"| D5-10(5~10%) | {d5} | {d5/tot*100:.1f}% |")
        r.append(f"| <5% | {dlt5} | {dlt5/tot*100:.1f}% |")
        r.append(f"\n最高涨幅均值: **{hi['买入日最高涨幅%'].mean():.2f}%**\n")
    
    # A4. 板块
    r.append("#### A4. 板块偏好\n")
    if '板块' in valid.columns:
        bc = valid['板块'].value_counts()
        tot = len(valid)
        r.append("| 板块 | 笔数 | 占比 | 平均收益% |")
        r.append("|------|------|------|----------|")
        for k, v in bc.items():
            sub_ret = valid[valid['板块'] == k]['单笔收益%'].mean()
            r.append(f"| {k} | {v} | {v/tot*100:.1f}% | {sub_ret:+.2f}% |")
    
    # A5. 个股集中度
    r.append("\n#### A5. 个股集中度 (Top10)\n")
    sc = valid.groupby(['股票代码','股票名称']).agg(次数=('单笔收益%','count'), 平均收益=('单笔收益%','mean')).sort_values('次数', ascending=False).head(10)
    r.append("| 排名 | 股票 | 次数 | 平均收益% |")
    r.append("|------|------|------|----------|")
    for i, ((code, name_s), row) in enumerate(sc.iterrows(), 1):
        r.append(f"| {i} | {name_s}({code}) | {int(row['次数'])} | {row['平均收益']:+.2f}% |")
    unique_cnt = valid['股票代码'].nunique()
    r.append(f"\n共 **{unique_cnt}** 只不同股票, 重复交易率 {(n-unique_cnt)/n*100:.1f}%\n")
    
    # ──────── B. 持仓策略 ────────
    r.append("### B. 持仓策略\n")
    
    # B1. 持仓天数
    hold = valid.dropna(subset=['持仓天数'])
    if len(hold) > 0:
        r.append("#### B1. 持仓天数分布\n")
        hbins = [
            ('T+1(1天)',   hold['持仓天数'] == 1),
            ('T+2(2天)',   hold['持仓天数'] == 2),
            ('3-5天',      (hold['持仓天数'] >= 3) & (hold['持仓天数'] <= 5)),
            ('6-10天',     (hold['持仓天数'] >= 6) & (hold['持仓天数'] <= 10)),
            ('10天+',      hold['持仓天数'] > 10),
        ]
        r.append("| 持仓 | 笔数 | 占比 | 平均收益% | 胜率 |")
        r.append("|------|------|------|----------|------|")
        for label, mask in hbins:
            sub = hold[mask]
            cnt = len(sub)
            if cnt == 0: continue
            r.append(f"| {label} | {cnt} | {cnt/len(hold)*100:.1f}% | {sub['单笔收益%'].mean():+.2f}% | {(sub['单笔收益%']>0).mean()*100:.1f}% |")
        r.append(f"\n持仓天数均值: **{hold['持仓天数'].mean():.1f}天**, 中位数: {hold['持仓天数'].median():.0f}天\n")
    
    # B2. 同时持股数 & 仓位
    if '持股数' in rev.columns:
        active = rev[rev['持股数'] > 0]
        if len(active) > 0:
            r.append("#### B2. 同时持股 & 仓位\n")
            r.append(f"- 日均持股: **{active['持股数'].mean():.1f}只**, 最多: {int(active['持股数'].max())}只\n")
    if '仓位(%)' in rev.columns:
        active2 = rev[rev['仓位(%)'] > 0]
        if len(active2) > 0:
            r.append(f"- 平均仓位: **{active2['仓位(%)'].mean():.0f}%**, 满仓(>90%)占比: {(active2['仓位(%)']>90).mean()*100:.1f}%\n")
    
    # ──────── C. 卖出时机 ────────
    r.append("### C. 卖出时机\n")
    
    r.append("#### C1. 收益分布\n")
    ret_bins = [
        ('大赚(>10%)',    valid['单笔收益%'] > 10),
        ('中赚(5~10%)',   (valid['单笔收益%'] > 5)  & (valid['单笔收益%'] <= 10)),
        ('小赚(0~5%)',    (valid['单笔收益%'] > 0)  & (valid['单笔收益%'] <= 5)),
        ('小亏(0~-5%)',   (valid['单笔收益%'] <= 0) & (valid['单笔收益%'] > -5)),
        ('中亏(-5~-10%)', (valid['单笔收益%'] <= -5) & (valid['单笔收益%'] > -10)),
        ('大亏(<-10%)',   valid['单笔收益%'] <= -10),
    ]
    r.append("| 区间 | 笔数 | 占比 |")
    r.append("|------|------|------|")
    for label, mask in ret_bins:
        cnt = mask.sum()
        r.append(f"| {label} | {cnt} | {cnt/n*100:.1f}% |")
    
    # C2. 盈亏票持仓差异
    if len(winners) > 0 and len(losers) > 0 and '持仓天数' in valid.columns:
        w_hold = winners['持仓天数'].dropna().mean()
        l_hold = losers['持仓天数'].dropna().mean()
        r.append(f"\n盈利票平均持仓 **{w_hold:.1f}天** vs 亏损票 **{l_hold:.1f}天**")
        if w_hold > l_hold:
            r.append(" → 让利润奔跑 ✅\n")
        else:
            r.append(" → 亏损票拿更久 ⚠️\n")
    
    # ──────── D. 收益归因 ────────
    r.append("### D. 收益归因\n")
    
    # D1. 大赚
    big_w = valid[valid['单笔收益%'] > 10].sort_values('单笔收益%', ascending=False)
    if len(big_w) > 0:
        r.append(f"#### D1. 大赚交易(>10%): {len(big_w)}笔, 平均 +{big_w['单笔收益%'].mean():.1f}%\n")
        r.append("| 股票 | 买入日 | 持仓天 | 收益% | 前日涨幅% | 开盘涨幅% | 板块 |")
        r.append("|------|--------|-------|-------|----------|----------|------|")
        for _, row in big_w.head(10).iterrows():
            r.append(f"| {row.get('股票名称','')}({row['股票代码']}) | {row['买入日期']} | {row.get('持仓天数','')} | +{row['单笔收益%']:.1f}% | {row.get('前一日涨幅%',''):} | {row.get('买入日开盘涨幅%',''):} | {row.get('板块','')} |")
    
    # D2. 大亏
    big_l = valid[valid['单笔收益%'] < -10].sort_values('单笔收益%')
    if len(big_l) > 0:
        r.append(f"\n#### D2. 大亏交易(<-10%): {len(big_l)}笔, 平均 {big_l['单笔收益%'].mean():.1f}%\n")
        r.append("| 股票 | 买入日 | 持仓天 | 收益% | 前日涨幅% | 板块 |")
        r.append("|------|--------|-------|-------|----------|------|")
        for _, row in big_l.head(8).iterrows():
            r.append(f"| {row.get('股票名称','')}({row['股票代码']}) | {row['买入日期']} | {row.get('持仓天数','')} | {row['单笔收益%']:.1f}% | {row.get('前一日涨幅%',''):} | {row.get('板块','')} |")
    else:
        r.append("#### D2. 无大亏(>-10%)交易 ✅\n")
    
    # D3. 月度分析
    r.append("\n#### D3. 按月收益\n")
    valid_c = valid.copy()
    valid_c['月份'] = valid_c['卖出日期'].astype(str).str[:6]
    monthly = valid_c.groupby('月份').agg(笔数=('单笔收益%','count'), 均值=('单笔收益%','mean'), 胜率=('单笔收益%', lambda x: (x>0).mean()*100), 总和=('单笔收益%','sum')).round(2)
    r.append("| 月份 | 笔数 | 均值% | 胜率% | 总和% |")
    r.append("|------|------|-------|-------|-------|")
    for m, row in monthly.iterrows():
        r.append(f"| {m} | {int(row['笔数'])} | {row['均值']:+.2f}% | {row['胜率']:.0f}% | {row['总和']:+.1f}% |")
    
    return '\n'.join(r)


# ─── 生成报告 ─────────────────────────────────────────
report_lines = []

report_lines.append("# 淘股吧6位高手交易策略深度研究\n")
report_lines.append(f"生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
report_lines.append("---\n")

# 总览表
report_lines.append("## 零、六位高手总览\n")
report_lines.append("| 高手 | 笔数 | 单笔均值% | 中位数% | 胜率% | 盈亏比 | 简单加总% | 持仓天数中位 | 20%板占比 |")
report_lines.append("|------|------|----------|--------|-------|--------|----------|------------|----------|")

master_order = ['只核大学生', '天牌', '低调内敛的朋', '独行侠令狐冲', '忘忧阁主', '龙年大叔']
for name in master_order:
    sub = all_df[all_df['高手名'] == name].dropna(subset=['单笔收益%'])
    n = len(sub)
    if n == 0: continue
    avg = sub['单笔收益%'].mean()
    med = sub['单笔收益%'].median()
    wr  = (sub['单笔收益%'] > 0).mean() * 100
    w   = sub[sub['单笔收益%'] > 0]
    l   = sub[sub['单笔收益%'] <= 0]
    plr = abs(w['单笔收益%'].mean() / l['单笔收益%'].mean()) if len(l) > 0 and l['单笔收益%'].mean() != 0 else 999
    tot = sub['单笔收益%'].sum()
    hld = sub['持仓天数'].dropna().median()
    gem = (sub['板块'] == '20%板').mean() * 100
    report_lines.append(f"| {name} | {n} | {avg:+.2f}% | {med:+.2f}% | {wr:.1f}% | {plr:.2f} | {tot:+.0f}% | {hld:.0f} | {gem:.0f}% |")

report_lines.append(f"\n> D14黄金稳健版参考: 57笔, +3.15%/笔, 胜率72%, 总+180%\n")
report_lines.append("---\n")

# 逐个高手详细分析
rank_info = {
    '只核大学生': ('一', '+794%, 冠军'),
    '天牌': ('二', '+631%'),
    '低调内敛的朋': ('三', '+470%'),
    '独行侠令狐冲': ('四', '+229%'),
    '忘忧阁主': ('五', '+162%'),
    '龙年大叔': ('六', '+90%'),
}

for name in master_order:
    ch, info = rank_info[name]
    print(f"分析: {name}...")
    sub = all_df[all_df['高手名'] == name]
    rev = rev_data.get(name, pd.DataFrame())
    
    report_lines.append(f"## {ch}、{name} ({info})\n")
    section = analyze_master(name, sub, rev)
    report_lines.append(section)
    report_lines.append("\n---\n")

# ──────── 共同赚钱模式分析 ────────
print("分析共同赚钱模式...")
report_lines.append("## 七、六位高手共同赚钱模式\n")

# 所有有效交易
all_valid = all_df.dropna(subset=['单笔收益%'])

# 1. 各前日涨幅区间的表现（跨高手汇总）
report_lines.append("### 1. 前一日涨幅 vs 收益（全部高手汇总）\n")
prev_valid = all_valid.dropna(subset=['前一日涨幅%'])
prev_bins = [
    ('涨停(>8%)',   prev_valid['前一日涨幅%'] > 8),
    ('大涨(5~8%)',  (prev_valid['前一日涨幅%'] > 5) & (prev_valid['前一日涨幅%'] <= 8)),
    ('小涨(0~5%)', (prev_valid['前一日涨幅%'] >= 0) & (prev_valid['前一日涨幅%'] <= 5)),
    ('小跌(0~-3%)', (prev_valid['前一日涨幅%'] < 0) & (prev_valid['前一日涨幅%'] >= -3)),
    ('大跌(<-3%)', prev_valid['前一日涨幅%'] < -3),
]
report_lines.append("| 前日涨幅 | 笔数 | 占比 | 平均收益% | 胜率 | 大赚>10%占比 |")
report_lines.append("|---------|------|------|----------|------|------------|")
for label, mask in prev_bins:
    sub = prev_valid[mask]
    cnt = len(sub)
    if cnt == 0: continue
    pct = cnt / len(prev_valid) * 100
    ret = sub['单笔收益%'].mean()
    wr  = (sub['单笔收益%'] > 0).mean() * 100
    big = (sub['单笔收益%'] > 10).mean() * 100
    report_lines.append(f"| {label} | {cnt} | {pct:.1f}% | {ret:+.2f}% | {wr:.1f}% | {big:.1f}% |")

# 2. 开盘涨幅 vs 收益
report_lines.append("\n### 2. 买入日开盘涨幅 vs 收益（全部高手汇总）\n")
open_valid = all_valid.dropna(subset=['买入日开盘涨幅%'])
open_bins = [
    ('一字(>8%)',    open_valid['买入日开盘涨幅%'] > 8),
    ('高开(3~8%)',  (open_valid['买入日开盘涨幅%'] > 3) & (open_valid['买入日开盘涨幅%'] <= 8)),
    ('小高(0~3%)', (open_valid['买入日开盘涨幅%'] >= 0) & (open_valid['买入日开盘涨幅%'] <= 3)),
    ('低开(-3~0%)', (open_valid['买入日开盘涨幅%'] < 0) & (open_valid['买入日开盘涨幅%'] >= -3)),
    ('大低(<-3%)', open_valid['买入日开盘涨幅%'] < -3),
]
report_lines.append("| 开盘涨幅 | 笔数 | 占比 | 平均收益% | 胜率 | 大赚>10%占比 |")
report_lines.append("|---------|------|------|----------|------|------------|")
for label, mask in open_bins:
    sub = open_valid[mask]
    cnt = len(sub)
    if cnt == 0: continue
    pct = cnt / len(open_valid) * 100
    ret = sub['单笔收益%'].mean()
    wr  = (sub['单笔收益%'] > 0).mean() * 100
    big = (sub['单笔收益%'] > 10).mean() * 100
    report_lines.append(f"| {label} | {cnt} | {pct:.1f}% | {ret:+.2f}% | {wr:.1f}% | {big:.1f}% |")

# 3. 持仓天数 vs 收益
report_lines.append("\n### 3. 持仓天数 vs 收益（全部高手汇总）\n")
hold_valid = all_valid.dropna(subset=['持仓天数'])
hold_bins = [
    ('1天', hold_valid['持仓天数'] == 1),
    ('2天', hold_valid['持仓天数'] == 2),
    ('3-5天', (hold_valid['持仓天数'] >= 3) & (hold_valid['持仓天数'] <= 5)),
    ('6-10天', (hold_valid['持仓天数'] >= 6) & (hold_valid['持仓天数'] <= 10)),
    ('10天+', hold_valid['持仓天数'] > 10),
]
report_lines.append("| 持仓天数 | 笔数 | 占比 | 平均收益% | 胜率 | 大赚>10%占比 |")
report_lines.append("|---------|------|------|----------|------|------------|")
for label, mask in hold_bins:
    sub = hold_valid[mask]
    cnt = len(sub)
    if cnt == 0: continue
    pct = cnt / len(hold_valid) * 100
    ret = sub['单笔收益%'].mean()
    wr  = (sub['单笔收益%'] > 0).mean() * 100
    big = (sub['单笔收益%'] > 10).mean() * 100
    report_lines.append(f"| {label} | {cnt} | {pct:.1f}% | {ret:+.2f}% | {wr:.1f}% | {big:.1f}% |")

# 4. 10% vs 20%板
report_lines.append("\n### 4. 板块偏好（汇总）\n")
board_valid = all_valid.dropna(subset=['板块'])
for board in ['10%板', '20%板']:
    sub = board_valid[board_valid['板块'] == board]
    if len(sub) > 0:
        ret = sub['单笔收益%'].mean()
        wr  = (sub['单笔收益%'] > 0).mean() * 100
        big = (sub['单笔收益%'] > 10).mean() * 100
        report_lines.append(f"- **{board}**: {len(sub)}笔, 均值{ret:+.2f}%, 胜率{wr:.1f}%, 大赚占{big:.1f}%")

# 5. 核心发现
report_lines.append("\n### 5. 核心发现\n")
report_lines.append("根据以上数据，高手们的**共同赚钱模式**：\n")

# 动态生成核心发现
# 按前日涨幅找最赚钱分区
prev_ret_by_bin = {}
for label, mask in prev_bins:
    sub = prev_valid[mask]
    if len(sub) >= 5:
        prev_ret_by_bin[label] = sub['单笔收益%'].mean()

best_prev = max(prev_ret_by_bin, key=prev_ret_by_bin.get) if prev_ret_by_bin else ''
report_lines.append(f"1. **前日涨幅**: 最赚钱的前日涨幅区间是 **{best_prev}**（均值{prev_ret_by_bin.get(best_prev,0):+.2f}%）")

# 最佳开盘
open_ret_by_bin = {}
for label, mask in open_bins:
    sub = open_valid[mask]
    if len(sub) >= 5:
        open_ret_by_bin[label] = sub['单笔收益%'].mean()
best_open = max(open_ret_by_bin, key=open_ret_by_bin.get) if open_ret_by_bin else ''
report_lines.append(f"2. **开盘涨幅**: 最赚钱的开盘区间是 **{best_open}**（均值{open_ret_by_bin.get(best_open,0):+.2f}%）")

# 最佳持仓天数
hold_ret_by_bin = {}
for label, mask in hold_bins:
    sub = hold_valid[mask]
    if len(sub) >= 5:
        hold_ret_by_bin[label] = sub['单笔收益%'].mean()
best_hold = max(hold_ret_by_bin, key=hold_ret_by_bin.get) if hold_ret_by_bin else ''
report_lines.append(f"3. **持仓天数**: 持 **{best_hold}** 收益最高（均值{hold_ret_by_bin.get(best_hold,0):+.2f}%）")

# 板块
for board in ['10%板', '20%板']:
    sub = board_valid[board_valid['板块'] == board]
    if len(sub) > 0:
        ret = sub['单笔收益%'].mean()
        if board == '20%板':
            report_lines.append(f"4. **板块**: 20%板(创业板/科创板)平均收益{ret:+.2f}%")

report_lines.append("")

# 写临时报告（回测部分单独脚本做）
report_path = os.path.join(OUTPUT_DIR, '淘股吧高手策略深度研究.md')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))

print(f"\n✅ 分析报告已保存: {report_path}")
print("接下来运行回测脚本添加回测结果...")
