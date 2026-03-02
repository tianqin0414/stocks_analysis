#!/usr/bin/env python3
"""Re-analyze with ACTUAL executable buy point: buying at the 14% breakthrough price."""

import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 400)

df = pd.read_excel('/Users/tq/PycharmProjects/stocks_analysis/output/dec2025_surge_14pct_joined.xlsx')

# === KEY COLUMNS ===
# 首次达标价格 = price at 14% breakthrough (THIS IS THE BUY PRICE)
# preClose = previous close price
# 价格 = closing price on the data day
# 第2天收盘价 = next day close
# 第2天最高价 = next day high
# 昨收 = previous close (another column)

# Calculate ACTUAL returns from buying at 14% breakthrough price
df['buy_price'] = df['首次达标价格']  # this is the real buy price

# Return if sold at close same day
df['same_day_return'] = (df['价格'] - df['buy_price']) / df['buy_price'] * 100

# Return if sold at next day close
df['nextday_close_ret'] = (df['第2天收盘价'] - df['buy_price']) / df['buy_price'] * 100

# Return if sold at next day high
df['nextday_high_ret'] = (df['第2天最高价'] - df['buy_price']) / df['buy_price'] * 100

# Multi-day returns from buy price
# 第2天价格变动 % 1天 is return from 价格 (close), not from buy_price
# We need to reconstruct: if close = 价格, day2 close = 价格 * (1 + 第2天价格变动/100)
for d, col in [(2, '第2天价格变动 % 1天'), (3, '第3天价格变动 % 1天'), (4, '第4天价格变动 % 1天'), (5, '第5天价格变动 % 1天'), (6, '第6天价格变动 % 1天')]:
    if col in df.columns:
        day_price = df['价格'] * (1 + df[col] / 100)
        df[f'day{d}_from_buy'] = (day_price - df['buy_price']) / df['buy_price'] * 100

print("=" * 80)
print("ACTUAL RETURNS FROM BUYING AT 14% BREAKTHROUGH PRICE")
print("=" * 80)
print(f"Total records: {len(df)}")
print()

# Overall stats
print("=== If buy at 14% point ===")
for col, label in [
    ('same_day_return', '当天收盘卖出'),
    ('nextday_close_ret', '次日收盘卖出'),
    ('nextday_high_ret', '次日最高价卖出'),
    ('day2_from_buy', '第2天收盘卖出'),
    ('day3_from_buy', '第3天收盘卖出'),
    ('day4_from_buy', '第4天收盘卖出'),
    ('day5_from_buy', '第5天收盘卖出'),
    ('day6_from_buy', '第6天收盘卖出'),
]:
    if col in df.columns:
        v = df[col].dropna()
        print(f"  {label}: mean={v.mean():.2f}%, median={v.median():.2f}%, "
              f"win={(v>0).mean()*100:.1f}%, n={len(v)}")

print()
print("同天收盘卖出收益分布:")
bins = [-100, -10, -5, -3, -1, 0, 1, 3, 5, 10, 20, 100]
print(pd.cut(df['same_day_return'], bins=bins).value_counts().sort_index().to_string())

# Helper
def grp(name, subset):
    n = len(subset)
    if n < 2: return None
    sd = subset['same_day_return'].dropna()
    nc = subset['nextday_close_ret'].dropna()
    nh = subset['nextday_high_ret'].dropna()
    d3 = subset['day3_from_buy'].dropna() if 'day3_from_buy' in subset.columns else pd.Series([])
    return {
        'name': name, 'n': n,
        'sameday': sd.mean() if len(sd)>0 else np.nan,
        'sameday_win': (sd>0).mean()*100 if len(sd)>0 else np.nan,
        'nextclose': nc.mean() if len(nc)>0 else np.nan,
        'nextclose_win': (nc>0).mean()*100 if len(nc)>0 else np.nan,
        'nexthigh': nh.mean() if len(nh)>0 else np.nan,
        'day3': d3.mean() if len(d3)>0 else np.nan,
    }

def pgrp(r):
    if r: print(f"  {r['name']:<38} n={r['n']:>4} | 当天close={r['sameday']:>6.2f}% win={r['sameday_win']:>5.1f}% | 次日close={r['nextclose']:>6.2f}% win={r['nextclose_win']:>5.1f}% | 次日high={r['nexthigh']:>6.2f}%")

# KEY: only use filters available AT the 14% breakthrough moment
# Available at breakthrough:
#   - 首次达标时间 (what time we hit 14%)
#   - 开盘涨幅(%) (known from market open)
#   - 上一日收跌幅(%) (known from yesterday)
#   - 前1天最高涨幅, 前2天最高涨幅 (known from history)
#   - RSI, MACD, SMA, 波动率 (calculated from prior data)
#   - 市值, 流通比例, 散户数量, 分析师评级, 公司性质 (fundamental)
#   - 量比 at that moment (partially knowable)
#   - 总分, 总分b (calculated scores)
# NOT available at breakthrough (hindsight):
#   - 收盘涨幅(%) ← we don't know if it will close at 19%+
#   - 峰值涨幅(%) ← we might not know the final peak
#   - 回撤18%时涨幅(%) ← future data

print("\n" + "=" * 80)
print("STRATEGIES USING ONLY INFORMATION AVAILABLE AT 14% BREAKTHROUGH")
print("=" * 80)

rsi_col = '相对强弱指标（RSI） (14) 1天'
rv = '相对成交量(Relative Vol) 1天'
df['hour'] = df['首次达标时间'].astype(str).str.split(':').str[0].astype(float)
df['散户n'] = pd.to_numeric(df['散户数量'], errors='coerce')

# === 1. BY TIME ===
print("\n--- 1. 按首次达标时间 ---")
for h in sorted(df['hour'].dropna().unique()):
    pgrp(grp(f'{int(h)}时', df[df['hour'] == h]))

print("\nSummary:")
df['tg'] = 'other'
df.loc[df['hour'] <= 10, 'tg'] = '早盘(9-10时)'
df.loc[(df['hour'] >= 11) & (df['hour'] <= 13), 'tg'] = '午盘(11-13时)'
df.loc[df['hour'] >= 14, 'tg'] = '尾盘(14-15时)'
for t in ['早盘(9-10时)', '午盘(11-13时)', '尾盘(14-15时)']:
    pgrp(grp(t, df[df['tg'] == t]))

# === 2. BY OPENING GAP ===
print("\n--- 2. 按开盘涨幅(%) ---")
df['ogap'] = pd.cut(df['开盘涨幅(%)'], bins=[-20, -5, 0, 3, 5, 8, 10, 20, 100])
for b, g in df.groupby('ogap', observed=True):
    r = grp(f'开盘涨幅 {b}', g)
    if r and r['n'] >= 3: pgrp(r)

# === 3. BY PREV DAY GAIN ===
print("\n--- 3. 按上一日收跌幅(%) ---")
df['prevd'] = pd.cut(df['上一日收跌幅(%)'], bins=[-20, -5, 0, 3, 5, 10, 20, 100])
for b, g in df.groupby('prevd', observed=True):
    r = grp(f'上一日 {b}', g)
    if r and r['n'] >= 3: pgrp(r)

# === 4. BY 前1天最高涨幅 ===
print("\n--- 4. 按前1天最高涨幅 (首板 vs 连板) ---")
df['p1'] = pd.cut(df['前1天最高涨幅'], bins=[-20, 0, 3, 5, 10, 15, 25])
for b, g in df.groupby('p1', observed=True):
    r = grp(f'前1天涨幅 {b}', g)
    if r and r['n'] >= 3: pgrp(r)

# === 5. BY RSI ===
print("\n--- 5. 按RSI(14) ---")
df['rbin'] = pd.cut(df[rsi_col], bins=[0, 30, 40, 50, 60, 70, 80, 100])
for b, g in df.groupby('rbin', observed=True):
    r = grp(f'RSI {b}', g)
    if r and r['n'] >= 3: pgrp(r)

# === 6. BY MARKET CAP ===
print("\n--- 6. 按市值 ---")
df['mc'] = pd.cut(df['市值']/1e8, bins=[0, 20, 30, 50, 100, 200, 500, 10000],
                   labels=['<20亿', '20-30亿', '30-50亿', '50-100亿', '100-200亿', '200-500亿', '>500亿'])
for b, g in df.groupby('mc', observed=True):
    pgrp(grp(str(b), g))

# === 7. BY 流通比例 ===
print("\n--- 7. 按流通比例 ---")
df['fb'] = pd.cut(df['流通比例'], bins=[0, 0.3, 0.5, 0.7, 0.9, 1.01])
for b, g in df.groupby('fb', observed=True):
    pgrp(grp(str(b), g))

# === 8. BY 散户数量 ===
print("\n--- 8. 按散户数量变化 ---")
df['rb'] = pd.cut(df['散户n'], bins=[-300, -50, -20, -10, 0, 50, 200, 10000])
for b, g in df.groupby('rb', observed=True):
    r = grp(f'散户 {b}', g)
    if r and r['n'] >= 3: pgrp(r)

# === 9. BY MACD / 总分 ===
print("\n--- 9. 按MACD/总分b ---")
for v, g in df.groupby('macd'):
    r = grp(f'MACD={v}', g)
    if r and r['n'] >= 3: pgrp(r)

for v in sorted(df['总分b'].dropna().unique()):
    r = grp(f'总分b={v}', df[df['总分b'] == v])
    if r and r['n'] >= 3: pgrp(r)

# === 10. MARKET TYPE ===
print("\n--- 10. 按市场类型 ---")
for mt, g in df.groupby('市场类型'):
    pgrp(grp(mt, g))

# === 11. IF STOCK IS UNDER INVESTIGATION ===
print("\n--- 11. 是否立案 ---")
for v, g in df.groupby('是否立案'):
    pgrp(grp(v, g))

# === 12. COMBINED STRATEGIES (ALL USING AVAILABLE-AT-BUY-TIME INFO) ===
print("\n" + "=" * 80)
print("COMBINED STRATEGIES (only information available at buy time)")
print("=" * 80)

combos = {
    'ALL(基线)':                      df,
    # Time-based
    '早盘(≤10时)':                    df[df['hour'] <= 10],
    '9时30分前':                      df[df['hour'] <= 9],
    # Time + fundamentals
    '早盘+小盘<100亿':                df[(df['hour'] <= 10) & (df['市值'] < 100e8)],
    '早盘+小盘<50亿':                 df[(df['hour'] <= 10) & (df['市值'] < 50e8)],
    '早盘+20-100亿':                  df[(df['hour'] <= 10) & (df['市值'] >= 20e8) & (df['市值'] < 100e8)],
    # Time + prior day
    '早盘+首板(前1天<3%)':            df[(df['hour'] <= 10) & (df['前1天最高涨幅'] < 3)],
    '早盘+连板(前1天>5%)':            df[(df['hour'] <= 10) & (df['前1天最高涨幅'] > 5)],
    '早盘+上一日涨(0-3%)':            df[(df['hour'] <= 10) & (df['上一日收跌幅(%)'] > 0) & (df['上一日收跌幅(%)'] <= 3)],
    '早盘+上一日涨(5-10%)':           df[(df['hour'] <= 10) & (df['上一日收跌幅(%)'] > 5) & (df['上一日收跌幅(%)'] <= 10)],
    '早盘+上一日涨(>10%)':            df[(df['hour'] <= 10) & (df['上一日收跌幅(%)'] > 10)],
    # Time + opening
    '早盘+低开(<0%)':                 df[(df['hour'] <= 10) & (df['开盘涨幅(%)'] < 0)],
    '早盘+平开(0-3%)':               df[(df['hour'] <= 10) & (df['开盘涨幅(%)'] >= 0) & (df['开盘涨幅(%)'] < 3)],
    '早盘+高开(3-5%)':               df[(df['hour'] <= 10) & (df['开盘涨幅(%)'] >= 3) & (df['开盘涨幅(%)'] < 5)],
    '早盘+高开(5%+)':                df[(df['hour'] <= 10) & (df['开盘涨幅(%)'] >= 5)],
    # Time + technicals
    '早盘+RSI<50':                   df[(df['hour'] <= 10) & (df[rsi_col] < 50)],
    '早盘+RSI 50-70':                df[(df['hour'] <= 10) & (df[rsi_col] >= 50) & (df[rsi_col] < 70)],
    '早盘+RSI 30-60':                df[(df['hour'] <= 10) & (df[rsi_col] >= 30) & (df[rsi_col] < 60)],
    '早盘+MACD金叉':                  df[(df['hour'] <= 10) & (df['macd'] == 1)],
    # Time + volume
    '早盘+散户减(-20↓)':              df[(df['hour'] <= 10) & (df['散户n'] < -20)],
    '早盘+散户减(-50↓)':              df[(df['hour'] <= 10) & (df['散户n'] < -50)],
    # Time + 流通
    '早盘+流通0.5-0.7':              df[(df['hour'] <= 10) & (df['流通比例'] >= 0.5) & (df['流通比例'] < 0.7)],
    # Multi-condition
    '早盘+小盘+首板':                 df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3)],
    '早盘+小盘+连板':                 df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] > 5)],
    '早盘+小盘+低开':                 df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['开盘涨幅(%)'] < 0)],
    '早盘+小盘+RSI50-70':            df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df[rsi_col] >= 50) & (df[rsi_col] < 70)],
    '早盘+首板+低开':                 df[(df['hour'] <= 10) & (df['前1天最高涨幅'] < 3) & (df['开盘涨幅(%)'] < 0)],
    '早盘+首板+散户减':               df[(df['hour'] <= 10) & (df['前1天最高涨幅'] < 3) & (df['散户n'] < -20)],
    '早盘+首板+RSI50-70':            df[(df['hour'] <= 10) & (df['前1天最高涨幅'] < 3) & (df[rsi_col] >= 50) & (df[rsi_col] < 70)],
    '早盘+低开+散户减':               df[(df['hour'] <= 10) & (df['开盘涨幅(%)'] < 0) & (df['散户n'] < -20)],
    '早+小盘+首板+低开':              df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3) & (df['开盘涨幅(%)'] < 0)],
    '早+小盘+首板+RSI50-70':         df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3) & (df[rsi_col] >= 50) & (df[rsi_col] < 70)],
    '早+小盘+低开+散户减':            df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['开盘涨幅(%)'] < 0) & (df['散户n'] < -20)],
    '早+20-100亿+首板':              df[(df['hour'] <= 10) & (df['市值'] >= 20e8) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3)],
    '早+20-100亿+首板+低开':         df[(df['hour'] <= 10) & (df['市值'] >= 20e8) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3) & (df['开盘涨幅(%)'] < 0)],
    '早+20-100亿+连板':              df[(df['hour'] <= 10) & (df['市值'] >= 20e8) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] > 5)],
    '早+上一日涨>5+小盘':             df[(df['hour'] <= 10) & (df['上一日收跌幅(%)'] > 5) & (df['市值'] < 100e8)],
    '早+上一日涨>10+小盘':            df[(df['hour'] <= 10) & (df['上一日收跌幅(%)'] > 10) & (df['市值'] < 100e8)],
    # 总分b >=3
    '早盘+总分b≥3':                   df[(df['hour'] <= 10) & (df['总分b'] >= 3)],
    '早盘+总分b≥4':                   df[(df['hour'] <= 10) & (df['总分b'] >= 4)],
    '早+小盘+总分b≥3':               df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['总分b'] >= 3)],
    # Non-early
    '午盘(11-13时)':                  df[(df['hour'] >= 11) & (df['hour'] <= 13)],
    '下午1点':                        df[df['hour'] == 13],
}

print(f"{'Strategy':<35} {'N':>4} | {'当天收盘':>7} {'胜率':>5} | {'次日收盘':>8} {'胜率':>5} | {'次日最高':>8} | {'第3天':>6}")
print("-" * 100)
all_r = []
for name, subset in combos.items():
    r = grp(name, subset)
    if r:
        all_r.append(r)
        d3 = f"{r['day3']:.2f}" if not np.isnan(r.get('day3', np.nan)) else 'N/A'
        print(f"{r['name']:<35} {r['n']:>4} | {r['sameday']:>7.2f}% {r['sameday_win']:>4.1f}% | {r['nextclose']:>7.2f}% {r['nextclose_win']:>4.1f}% | {r['nexthigh']:>7.2f}% | {d3:>6}%")

# === RANKED ===
print("\n=== 按「当天收盘卖出」均值排名 (n>=5) ===")
valid = [r for r in all_r if r['n'] >= 5 and not np.isnan(r['sameday'])]
print(f"{'Strategy':<35} {'N':>4} | {'当天收盘':>7} {'胜率':>5} | {'次日收盘':>8} {'胜率':>5}")
print("-" * 75)
for r in sorted(valid, key=lambda x: x['sameday'], reverse=True)[:20]:
    print(f"{r['name']:<35} {r['n']:>4} | {r['sameday']:>7.2f}% {r['sameday_win']:>4.1f}% | {r['nextclose']:>7.2f}% {r['nextclose_win']:>4.1f}%")

print("\n=== 按「当天收盘」胜率排名 (n>=5) ===")
print(f"{'Strategy':<35} {'N':>4} | {'当天收盘':>7} {'胜率':>5} | {'次日收盘':>8} {'胜率':>5}")
print("-" * 75)
for r in sorted(valid, key=lambda x: x['sameday_win'], reverse=True)[:20]:
    print(f"{r['name']:<35} {r['n']:>4} | {r['sameday']:>7.2f}% {r['sameday_win']:>4.1f}% | {r['nextclose']:>7.2f}% {r['nextclose_win']:>4.1f}%")

print("\n=== 按「次日收盘」均值排名 (n>=5) ===")
valid2 = [r for r in all_r if r['n'] >= 5 and not np.isnan(r['nextclose'])]
print(f"{'Strategy':<35} {'N':>4} | {'当天收盘':>7} {'胜率':>5} | {'次日收盘':>8} {'胜率':>5} | {'次日最高':>8}")
print("-" * 90)
for r in sorted(valid2, key=lambda x: x['nextclose'], reverse=True)[:20]:
    print(f"{r['name']:<35} {r['n']:>4} | {r['sameday']:>7.2f}% {r['sameday_win']:>4.1f}% | {r['nextclose']:>7.2f}% {r['nextclose_win']:>4.1f}% | {r['nexthigh']:>7.2f}%")

# === HOLDING PERIOD ANALYSIS FOR BEST STRATEGIES ===
print("\n" + "=" * 80)
print("BEST STRATEGIES - MULTI-DAY HOLDING (from buy at 14%)")
print("=" * 80)
best = {
    'ALL(基线)':         df,
    '早盘(≤10时)':       df[df['hour'] <= 10],
    '早盘+小盘<100亿':   df[(df['hour'] <= 10) & (df['市值'] < 100e8)],
    '早盘+首板':         df[(df['hour'] <= 10) & (df['前1天最高涨幅'] < 3)],
    '早盘+低开':         df[(df['hour'] <= 10) & (df['开盘涨幅(%)'] < 0)],
    '早+小盘+首板':      df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3)],
    '早+小盘+低开':      df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['开盘涨幅(%)'] < 0)],
    '早+小盘+首板+低开':  df[(df['hour'] <= 10) & (df['市值'] < 100e8) & (df['前1天最高涨幅'] < 3) & (df['开盘涨幅(%)'] < 0)],
}

for name, subset in best.items():
    if len(subset) >= 2:
        line = f"  {name:<25} (n={len(subset):>3}): "
        for col, label in [('same_day_return', '当天'), ('nextday_close_ret', '次日'), ('day3_from_buy', 'D3'), ('day4_from_buy', 'D4'), ('day5_from_buy', 'D5'), ('day6_from_buy', 'D6')]:
            if col in subset.columns:
                v = subset[col].dropna()
                if len(v) > 0:
                    line += f"{label}={v.mean():.1f}%(win {(v>0).mean()*100:.0f}%) "
        print(line)

# === BEST/WORST stocks ===
print("\n" + "=" * 80)
print("TOP 15 当天收盘盈利最高 (from 14% buy)")
print("=" * 80)
show = ['股票代码', '名称', '日期', '首次达标时间', '首次达标价格', '价格', '开盘涨幅(%)', '上一日收跌幅(%)', '前1天最高涨幅', 'same_day_return']
print(df.nlargest(15, 'same_day_return')[show].to_string())

print("\n" + "=" * 80)
print("TOP 15 当天收盘亏损最大 (from 14% buy)")
print("=" * 80)
print(df.nsmallest(15, 'same_day_return')[show].to_string())
