#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
淘股吧高手 - 买点深度分析
分析：什么时候买、买什么样的票、开盘涨幅、前日表现
"""

import pandas as pd
import numpy as np

# ── 加载数据 ──
xlsx_files = {
    '天牌': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_天牌_交易明细.xlsx',
    '独行侠令狐冲': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_独行侠令狐冲_交易明细.xlsx',
    '忘忧阁主': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_忘忧阁主_交易明细.xlsx',
    '低调内敛的朋': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_低调内敛的朋_交易明细.xlsx',
    '龙年大叔': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_龙年大叔_交易明细.xlsx',
}

# columns: 高手名,买入日期,卖出日期,股票代码,股票名称,持仓天数,
#           买入价(收盘),卖出价(收盘),单笔收益%,
#           买入日开盘涨幅%,买入日最高涨幅%,买入日收盘涨幅%,前一日涨幅%,板块

all_trades = []
for name, f in xlsx_files.items():
    df = pd.read_excel(f)
    for col in ['持仓天数','单笔收益%','买入日开盘涨幅%','买入日最高涨幅%','买入日收盘涨幅%','前一日涨幅%']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    all_trades.append(df)

all_df = pd.concat(all_trades, ignore_index=True)

# 只核大学生 - 数据格式不同，需要对齐
zhihe_detail = pd.read_excel(
    '/Users/tq/PycharmProjects/stocks_analysis/output/2_淘股吧高手/交易明细/只核大学生_250笔_冠军+794%.xlsx',
    header=1
)
# 只看卖出（有完整买卖信息）
zhihe_sells = zhihe_detail[zhihe_detail['操作']=='卖出'].copy()
for col in ['持仓天数','单笔盈亏(%)']:
    zhihe_sells[col] = pd.to_numeric(zhihe_sells[col], errors='coerce')

print("=" * 72)
print("淘股吧高手 买点深度分析")
print("=" * 72)

# ═══════════════════════════════════════════
# 1. 开盘涨幅分析 — 他们买的票开盘涨多少？
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("一、开盘涨幅分布 — 高手买在开盘涨多少的票？")
print("═" * 72)

names_sorted = ['天牌', '忘忧阁主', '低调内敛的朋', '龙年大叔', '独行侠令狐冲']

for name in names_sorted:
    sub = all_df[all_df['高手名']==name].dropna(subset=['买入日开盘涨幅%'])
    if len(sub) == 0:
        continue
    
    open_pct = sub['买入日开盘涨幅%']
    print(f"\n【{name}】{len(sub)}笔")
    
    bins = [(-999,-3), (-3,0), (0,2), (2,5), (5,10), (10,999)]
    labels = ['低开<-3%', '小低开-3~0%', '平开0~2%', '小高开2~5%', '高开5~10%', '大高开>10%']
    
    for (lo,hi), label in zip(bins, labels):
        s = sub[(open_pct>=lo) & (open_pct<hi)]
        if len(s) > 0:
            pct = len(s)/len(sub)*100
            avg_ret = s['单笔收益%'].mean()
            win = (s['单笔收益%']>0).mean()*100
            bar = '█' * int(pct/2)
            print(f"  {label:<14} {len(s):>4}笔 {pct:>5.1f}%  收益{avg_ret:>+6.2f}% 胜率{win:>4.0f}%  {bar}")

# ═══════════════════════════════════════════
# 2. 前一日涨幅分析 — 追涨还是抄底？
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("二、前一日涨幅 — 追涨停还是捡跌的？")
print("═" * 72)

for name in names_sorted:
    sub = all_df[all_df['高手名']==name].dropna(subset=['前一日涨幅%'])
    if len(sub) == 0:
        continue
    
    prev = sub['前一日涨幅%']
    print(f"\n【{name}】{len(sub)}笔  前日涨幅均值{prev.mean():+.1f}%  中位{prev.median():+.1f}%")
    
    bins = [(-999,-5), (-5,-2), (-2,0), (0,2), (2,5), (5,10), (10,999)]
    labels = ['大跌<-5%', '跌-5~-2%', '微跌-2~0%', '微涨0~2%', '涨2~5%', '涨5~10%', '大涨>10%']
    
    for (lo,hi), label in zip(bins, labels):
        s = sub[(prev>=lo) & (prev<hi)]
        if len(s) > 0:
            pct = len(s)/len(sub)*100
            avg_ret = s['单笔收益%'].mean()
            win = (s['单笔收益%']>0).mean()*100
            bar = '█' * int(pct/2)
            print(f"  {label:<14} {len(s):>4}笔 {pct:>5.1f}%  收益{avg_ret:>+6.2f}% 胜率{win:>4.0f}%  {bar}")

# ═══════════════════════════════════════════
# 3. 买入日内位置 — 买在日内什么位置？
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("三、买入当天K线位置 — 买在日内哪里？")
print("═" * 72)

for name in names_sorted:
    sub = all_df[all_df['高手名']==name].dropna(subset=['买入日开盘涨幅%','买入日最高涨幅%','买入日收盘涨幅%'])
    if len(sub) == 0:
        continue

    # 买入价(收盘) 说明他们用收盘价衡量买入——但买价应该在开盘和最高之间
    # 日内位置 = (收盘-开盘)/(最高-开盘)
    open_p = sub['买入日开盘涨幅%']
    high_p = sub['买入日最高涨幅%']
    close_p = sub['买入日收盘涨幅%']
    
    # 买入当天是涨还是跌？
    up_day = (close_p > open_p).sum()
    down_day = (close_p < open_p).sum()
    flat_day = (close_p == open_p).sum()
    
    # 当天最高涨幅 - 看日内波动空间
    print(f"\n【{name}】{len(sub)}笔")
    print(f"  开盘均值: {open_p.mean():+.1f}%   最高均值: {high_p.mean():+.1f}%   收盘均值: {close_p.mean():+.1f}%")
    print(f"  当天收涨: {up_day}笔({up_day/len(sub)*100:.0f}%)  收跌: {down_day}笔({down_day/len(sub)*100:.0f}%)")
    print(f"  日内最高涨幅分布:")
    
    high_bins = [(0,3), (3,5), (5,10), (10,15), (15,20), (20,999)]
    high_labels = ['<3%', '3~5%', '5~10%', '10~15%', '15~20%', '>20%']
    for (lo,hi), label in zip(high_bins, high_labels):
        s = sub[(high_p>=lo) & (high_p<hi)]
        if len(s) > 0:
            pct = len(s)/len(sub)*100
            avg_ret = s['单笔收益%'].mean()
            print(f"    最高{label:<8} {len(s):>4}笔 {pct:>5.1f}%  次日收益{avg_ret:>+6.2f}%")

# ═══════════════════════════════════════════
# 4. 板块偏好 — 10%板还是20%板？
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("四、板块偏好")
print("═" * 72)

for name in names_sorted:
    sub = all_df[all_df['高手名']==name]
    if len(sub) == 0:
        continue
    
    board = sub['板块'].value_counts()
    print(f"\n【{name}】{len(sub)}笔")
    for b in board.index:
        s = sub[sub['板块']==b]
        pct = len(s)/len(sub)*100
        avg_ret = s['单笔收益%'].mean()
        win = (s['单笔收益%']>0).mean()*100
        print(f"  {b:<8} {len(s):>4}笔 {pct:>5.1f}%  收益{avg_ret:>+6.2f}% 胜率{win:>4.0f}%")

# ═══════════════════════════════════════════
# 5. 最赚钱的买入画像 — 各高手赚钱笔 vs 亏钱笔
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("五、赚钱笔 vs 亏钱笔 — 买点有什么不同？")
print("═" * 72)

for name in names_sorted:
    sub = all_df[all_df['高手名']==name].dropna(subset=['单笔收益%','买入日开盘涨幅%','前一日涨幅%'])
    if len(sub) < 10:
        continue
    
    win = sub[sub['单笔收益%'] > 0]
    lose = sub[sub['单笔收益%'] <= 0]
    
    print(f"\n【{name}】 赚{len(win)}笔 vs 亏{len(lose)}笔")
    print(f"  {'':>20} {'赚钱笔':>10} {'亏钱笔':>10} {'差异':>10}")
    
    metrics = [
        ('前一日涨幅%', '前日涨幅'),
        ('买入日开盘涨幅%', '开盘涨幅'),
        ('买入日最高涨幅%', '最高涨幅'),
        ('买入日收盘涨幅%', '收盘涨幅'),
    ]
    for col, label in metrics:
        if col in win.columns and col in lose.columns:
            w = win[col].mean()
            l = lose[col].mean()
            print(f"  {label:<20} {w:>+9.2f}% {l:>+9.2f}% {w-l:>+9.2f}%")
    
    # 持仓天数
    w_days = win['持仓天数'].mean()
    l_days = lose['持仓天数'].mean()
    print(f"  {'持仓天数':<20} {w_days:>9.1f}天 {l_days:>9.1f}天 {w_days-l_days:>+9.1f}天")

# ═══════════════════════════════════════════
# 6. 高频买入的个股 — TOP10
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("六、最爱买的股票 TOP10（全部高手）")
print("═" * 72)

stock_stats = all_df.groupby('股票名称').agg(
    笔数=('单笔收益%', 'count'),
    均值=('单笔收益%', 'mean'),
    胜率=('单笔收益%', lambda x: (x>0).mean()*100),
    买手数=('高手名', 'nunique'),
).reset_index()
stock_stats = stock_stats[stock_stats['笔数']>=3].sort_values('笔数', ascending=False)

print(f"{'排名':>3} {'股票名称':<8} {'笔数':>4} {'买手数':>4} {'均值':>7} {'胜率':>5}")
for i, (_, row) in enumerate(stock_stats.head(15).iterrows(), 1):
    print(f"  {i:>2}. {row['股票名称']:<8} {row['笔数']:>3}笔 {row['买手数']:>3}人 {row['均值']:>+6.2f}% {row['胜率']:>4.0f}%")

# ═══════════════════════════════════════════
# 7. 总结：各高手买点画像
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("七、各高手买点画像总结")
print("═" * 72)

for name in names_sorted:
    sub = all_df[all_df['高手名']==name].dropna(subset=['买入日开盘涨幅%','前一日涨幅%'])
    if len(sub) < 5:
        continue
    
    open_med = sub['买入日开盘涨幅%'].median()
    prev_med = sub['前一日涨幅%'].median()
    high_med = sub['买入日最高涨幅%'].median()
    
    chase_pct = (sub['前一日涨幅%'] > 5).mean() * 100
    dip_pct = (sub['前一日涨幅%'] < -2).mean() * 100
    
    low_open = (sub['买入日开盘涨幅%'] < 0).mean() * 100
    high_open = (sub['买入日开盘涨幅%'] > 5).mean() * 100
    
    board_main = sub['板块'].mode()[0] if len(sub['板块'].mode()) > 0 else '?'
    
    avg_ret = sub['单笔收益%'].mean()
    win_rate = (sub['单笔收益%']>0).mean()*100
    
    print(f"\n【{name}】{len(sub)}笔  均值{avg_ret:+.2f}%  胜率{win_rate:.0f}%")
    print(f"  前日: 中位{prev_med:+.1f}%  追涨(>5%){chase_pct:.0f}%  抄底(<-2%){dip_pct:.0f}%")
    print(f"  开盘: 中位{open_med:+.1f}%  低开{low_open:.0f}%  高开>5%{high_open:.0f}%")
    print(f"  日内: 最高中位{high_med:+.1f}%")
    print(f"  板块: 主要{board_main}")

print("\n" + "=" * 72)
