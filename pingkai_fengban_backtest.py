#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全A回测：平开封板策略（来自淘股吧高手买点分析）

策略逻辑：
  买入条件：
    1. 10%涨跌幅限制股票（非创业板/科创板）
    2. 当天开盘涨幅在 -1% ~ +1%（平开）
    3. 当天收盘涨停（收盘涨幅 >= 9.5%，考虑四舍五入放宽一点）
    4. 非ST股（名称不含ST）
    5. 非新股（上市超过20个交易日）
  
  买入时机：收盘确认封板后，集合竞价或次日开盘买入
  实际买入价 = 次日开盘价（T+1日的open）
  
  卖出策略（T+2日，即买入后的第二天）：
    S1: 次日收盘卖（T+2收盘价）
    S2: 次日开盘卖（T+2开盘价）
    S3: 持2天后收盘卖（T+3收盘价）
    S4: 3%止盈 或 收盘卖（T+2日最高>=买入价*1.03则按+3%算，否则收盘卖）
  
  收益计算：(卖出价 - 买入价) / 买入价 * 100
  手续费：买卖各0.05% + 卖出印花税0.05% = 共0.15%
"""

import os
import glob
import pandas as pd
import numpy as np
from collections import defaultdict

DATA_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d/'
COMMISSION = 0.0015  # 总手续费0.15%

def is_10pct_board(code):
    """判断是否10%涨跌幅限制"""
    return not code.startswith('3') and not code.startswith('688')

def load_stock_data(code):
    """加载单只股票的日线数据"""
    pattern = f"{DATA_DIR}{code}_*.csv"
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            dfs.append(df)
        except:
            continue
    
    if not dfs:
        return None
    
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
    
    # 基本过滤
    df = df[df['volume'] > 0]  # 排除停牌
    
    return df

def scan_signals():
    """扫描所有10%板股票，找平开封板信号"""
    
    # 获取所有10%板股票
    all_files = glob.glob(f"{DATA_DIR}*_*.csv")
    codes = set()
    for f in all_files:
        code = os.path.basename(f).split('_')[0]
        if is_10pct_board(code):
            codes.add(code)
    
    codes = sorted(codes)
    print(f"扫描 {len(codes)} 只10%板股票...")
    
    all_signals = []
    processed = 0
    
    for code in codes:
        processed += 1
        if processed % 500 == 0:
            print(f"  已处理 {processed}/{len(codes)} 只...")
        
        df = load_stock_data(code)
        if df is None or len(df) < 25:
            continue
        
        # 计算涨跌幅
        df['open_pct'] = (df['open'] / df['preClose'] - 1) * 100
        df['close_pct'] = (df['close'] / df['preClose'] - 1) * 100
        df['high_pct'] = (df['high'] / df['preClose'] - 1) * 100
        
        # 遍历每天
        for i in range(20, len(df) - 3):  # 留3天给卖出
            row = df.iloc[i]
            
            # 跳过2025年之前的数据
            if row['date'] < 20250101:
                continue
            
            # 条件1: 平开 (-1% ~ +1%)
            if not (-1 <= row['open_pct'] <= 1):
                continue
            
            # 条件2: 收盘涨停 (>=9.5%)
            if row['close_pct'] < 9.5:
                continue
            
            # 条件3: 非一字板（开盘就涨停的不算，因为买不到）
            if row['open_pct'] >= 9.5:
                continue
            
            # T+1日（买入日）
            t1 = df.iloc[i+1]
            # T+2日（卖出日选项1）
            t2 = df.iloc[i+2]
            # T+3日（卖出日选项2）
            t3 = df.iloc[i+3] if i+3 < len(df) else None
            
            # 买入价 = T+1开盘价
            buy_price = t1['open']
            if buy_price <= 0:
                continue
            
            # 如果T+1也是一字涨停（开盘就涨停），买不到
            t1_open_pct = (t1['open'] / t1['preClose'] - 1) * 100
            if t1_open_pct >= 9.5:
                continue  # 一字板买不进
            
            # 计算各种卖出收益
            # S1: T+1收盘卖（买入当天收盘，但T+1制度不能当天卖！）
            # 修正: S1 = T+2收盘卖
            s1_ret = (t2['close'] / buy_price - 1) * 100 - COMMISSION * 100
            
            # S2: T+2开盘卖
            s2_ret = (t2['open'] / buy_price - 1) * 100 - COMMISSION * 100
            
            # S3: T+3收盘卖
            s3_ret = (t3['close'] / buy_price - 1) * 100 - COMMISSION * 100 if t3 is not None else None
            
            # S4: T+2日 3%止盈 或 收盘卖
            t2_high_pct = (t2['high'] / buy_price - 1) * 100
            if t2_high_pct >= 3:
                s4_ret = 3.0 - COMMISSION * 100
            else:
                s4_ret = s1_ret  # 没到3%就收盘卖
            
            # S5: T+2日 5%止盈 或 收盘卖
            if t2_high_pct >= 5:
                s5_ret = 5.0 - COMMISSION * 100
            else:
                s5_ret = s1_ret
            
            # 前日涨幅
            prev_close_pct = (row['preClose'] / df.iloc[i-1]['preClose'] - 1) * 100 if i > 0 else 0
            
            signal = {
                'date': int(row['date']),  # 信号日（封板日）
                'code': code,
                'open_pct': round(row['open_pct'], 2),
                'close_pct': round(row['close_pct'], 2),
                'buy_price': round(buy_price, 3),
                'buy_date': int(t1['date']),
                't1_open_pct': round(t1_open_pct, 2),
                's1_ret': round(s1_ret, 2),  # T+2收盘
                's2_ret': round(s2_ret, 2),  # T+2开盘
                's3_ret': round(s3_ret, 2) if s3_ret is not None else None,  # T+3收盘
                's4_ret': round(s4_ret, 2),  # 3%止盈/收盘
                's5_ret': round(s5_ret, 2),  # 5%止盈/收盘
            }
            all_signals.append(signal)
    
    return pd.DataFrame(all_signals)

# ═══════════════════════════════════════════
# 执行扫描
# ═══════════════════════════════════════════
print("=" * 72)
print("全A回测：平开封板策略")
print("条件: 10%板 + 开盘-1~+1% + 收盘涨停(>=9.5%)")
print("买入: 次日(T+1)开盘价")
print("=" * 72)

signals = scan_signals()
print(f"\n总信号数: {len(signals)}")
print(f"时间范围: {signals['date'].min()} ~ {signals['date'].max()}")
print()

# ═══════════════════════════════════════════
# 各卖出策略对比
# ═══════════════════════════════════════════
print("=" * 72)
print("卖出策略对比")
print("=" * 72)
print()

for strategy, col in [
    ('S1: T+2收盘卖', 's1_ret'),
    ('S2: T+2开盘卖', 's2_ret'),
    ('S3: T+3收盘卖', 's3_ret'),
    ('S4: 3%止盈/收盘卖', 's4_ret'),
    ('S5: 5%止盈/收盘卖', 's5_ret'),
]:
    valid = signals[col].dropna()
    avg = valid.mean()
    med = valid.median()
    win = (valid > 0).mean() * 100
    total = valid.sum()
    max_loss = valid.min()
    max_win = valid.max()
    print(f"  {strategy:<22} {len(valid):>5}笔  均值{avg:>+6.2f}%  中位{med:>+6.2f}%  胜率{win:>4.0f}%  总和{total:>+8.1f}%  最大亏{max_loss:>+6.1f}%  最大赚{max_win:>+6.1f}%")

# ═══════════════════════════════════════════
# 最优策略的月度明细
# ═══════════════════════════════════════════
# 选出均值最高的策略
best_col = max(['s1_ret','s2_ret','s4_ret','s5_ret'], key=lambda c: signals[c].dropna().mean())
print(f"\n最优策略: {best_col}")

print("\n" + "=" * 72)
print("各策略月度明细")
print("=" * 72)

signals['month'] = signals['date'] // 100

for strategy, col in [
    ('S1: T+2收盘卖', 's1_ret'),
    ('S4: 3%止盈/收盘', 's4_ret'),
    ('S5: 5%止盈/收盘', 's5_ret'),
]:
    print(f"\n【{strategy}】")
    print(f"  {'月份':<8} {'笔数':>5} {'均值':>7} {'中位':>7} {'胜率':>5} {'利润和':>8}")
    
    months = sorted(signals['month'].unique())
    pos_months = 0
    total_months = 0
    for m in months:
        msub = signals[signals['month'] == m][col].dropna()
        if len(msub) > 0:
            avg = msub.mean()
            med = msub.median()
            win = (msub > 0).mean() * 100
            total = msub.sum()
            total_months += 1
            if total > 0:
                pos_months += 1
            marker = '✅' if total > 0 else '❌'
            print(f"  {m:<8} {len(msub):>4}笔 {avg:>+6.2f}% {med:>+6.2f}% {win:>4.0f}% {total:>+7.1f}% {marker}")
    
    valid = signals[col].dropna()
    print(f"  {'合计':<8} {len(valid):>4}笔 {valid.mean():>+6.2f}% {valid.median():>+6.2f}% {(valid>0).mean()*100:>4.0f}% {valid.sum():>+7.1f}%")
    print(f"  月度一致性: {pos_months}/{total_months}月正收益 ({pos_months/total_months*100:.0f}%)")

# ═══════════════════════════════════════════
# 细分：T+1开盘涨幅对收益的影响
# ═══════════════════════════════════════════
print("\n" + "=" * 72)
print("T+1日（买入日）开盘涨幅对收益影响")
print("=" * 72)

for strategy, col in [('S1: T+2收盘', 's1_ret'), ('S4: 3%止盈', 's4_ret')]:
    print(f"\n【{strategy}】")
    bins = [(-999,-3),(-3,0),(0,3),(3,5),(5,8),(8,10)]
    labels = ['低开<-3%','低开-3~0%','平开0~3%','高开3~5%','高开5~8%','涨停开8~10%']
    for (lo,hi), label in zip(bins, labels):
        sub = signals[(signals['t1_open_pct']>=lo) & (signals['t1_open_pct']<hi)]
        if len(sub) >= 5:
            avg = sub[col].mean()
            win = (sub[col]>0).mean()*100
            print(f"  {label:<14} {len(sub):>5}笔  均值{avg:>+6.2f}%  胜率{win:>4.0f}%")

# ═══════════════════════════════════════════
# 复利模拟
# ═══════════════════════════════════════════
print("\n" + "=" * 72)
print("复利模拟（每天只做第1笔信号）")
print("=" * 72)

for strategy, col in [('S1: T+2收盘', 's1_ret'), ('S4: 3%止盈', 's4_ret')]:
    # 每天只取第一笔
    daily_first = signals.sort_values(['date','code']).groupby('date').first().reset_index()
    
    # 全仓复利
    capital_full = 100000
    capital_half = 100000
    
    for _, row in daily_first.iterrows():
        ret = row[col]
        if pd.notna(ret):
            capital_full *= (1 + ret/100)
            capital_half *= (1 + ret/100 * 0.5)  # 半仓
    
    full_ret = (capital_full / 100000 - 1) * 100
    half_ret = (capital_half / 100000 - 1) * 100
    
    print(f"\n{strategy} (每天仅1笔, 共{len(daily_first)}个交易日):")
    print(f"  全仓复利: 10万 → {capital_full/10000:.1f}万 ({full_ret:+.1f}%)")
    print(f"  半仓复利: 10万 → {capital_half/10000:.1f}万 ({half_ret:+.1f}%)")

# 保存信号明细
out_path = '/Users/tq/PycharmProjects/stocks_analysis/output/平开封板_全A回测信号.csv'
signals.to_csv(out_path, index=False, encoding='utf-8-sig')
print(f"\n信号明细已保存: {out_path}")

print("\n" + "=" * 72)
