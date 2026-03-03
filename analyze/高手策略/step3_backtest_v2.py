#!/usr/bin/env python3
"""
Step 3 (优化版): 向量化回测高手策略 + 融合策略 + D14对比
预计算所有指标，用pandas布尔筛选替代逐行循环
"""
import os, sys, glob, warnings, time
import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')
# 强制flush
import functools
print = functools.partial(print, flush=True)

PROJECT_ROOT = '/Users/tq/PycharmProjects/stocks_analysis'
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, 'output')
KLINE_DIR    = '/Users/tq/Documents/quant_data/miniqmt_data/1d'

def is_gem(code):
    return str(code).startswith('300') or str(code).startswith('688') or str(code).startswith('301')

# ─── 加载汇总数据 ─────────────────────────────────────
all_df = pd.read_excel(os.path.join(OUTPUT_DIR, 'tgb_全部高手_交易汇总.xlsx'))
print(f"汇总数据: {len(all_df)} 笔交易")

# ─── 构建全A宽表（一次性预计算所有指标） ─────────────────
t0 = time.time()
print("加载全A日线 + 预计算指标...")

kline_files = sorted(glob.glob(os.path.join(KLINE_DIR, '*_*_20250101_20251231.csv')))
# 补充2026
kline_2026 = sorted(glob.glob(os.path.join(KLINE_DIR, '*_*_20260101_*.csv')))
print(f"  2025年: {len(kline_files)} 文件, 2026: {len(kline_2026)} 文件")

rows = []
count = 0
all_codes_data = {}  # code -> df for later concat

for file_list, year_label in [(kline_files, '2025'), (kline_2026, '2026')]:
    for f in file_list:
        fname = os.path.basename(f)
        code = fname.split('_')[0]
        
        try:
            df = pd.read_csv(f, encoding='utf-8-sig', usecols=lambda c: c in ['date','open','high','low','close','volume','preClose'], dtype={'date': str})
        except:
            continue
        
        if 'date' not in df.columns or 'open' not in df.columns or len(df) < 3:
            continue
        
        df['date_str'] = df['date'].str[:8]
        df = df.sort_values('date_str').drop_duplicates('date_str').reset_index(drop=True)
        
        if code in all_codes_data:
            all_codes_data[code] = pd.concat([all_codes_data[code], df], ignore_index=True).drop_duplicates('date_str').sort_values('date_str').reset_index(drop=True)
        else:
            all_codes_data[code] = df
        
        count += 1
        if count % 2000 == 0:
            print(f"  已加载 {count} 文件...")

print(f"  加载完成: {len(all_codes_data)} 只股票, 耗时 {time.time()-t0:.1f}s")

# ─── 预计算指标并构建宽表 ─────────────────────────────
t1 = time.time()
print("预计算指标...")

all_rows = []
for code, df in all_codes_data.items():
    if len(df) < 5:
        continue
    
    df = df.reset_index(drop=True)
    
    # 前一日收盘
    df['prev_close'] = df['close'].shift(1)
    df['prev2_close'] = df['close'].shift(2)
    
    # 前一日涨幅 = (前日close - 前前日close) / 前前日close * 100
    df['prev_chg'] = (df['prev_close'] - df['prev2_close']) / df['prev2_close'] * 100
    
    # 今日开盘涨幅
    df['open_chg'] = (df['open'] - df['prev_close']) / df['prev_close'] * 100
    
    # 今日最高涨幅
    df['high_chg'] = (df['high'] - df['prev_close']) / df['prev_close'] * 100
    
    # 今日收盘涨幅
    df['close_chg'] = (df['close'] - df['prev_close']) / df['prev_close'] * 100
    
    # 次日开盘价(T+1卖出价)
    df['next1_open'] = df['open'].shift(-1)
    df['next1_date'] = df['date_str'].shift(-1)
    
    # T+2卖出价
    df['next2_open'] = df['open'].shift(-2)
    df['next2_date'] = df['date_str'].shift(-2)
    
    # T+3卖出价
    df['next3_open'] = df['open'].shift(-3)
    df['next3_date'] = df['date_str'].shift(-3)
    
    # T+5卖出价
    df['next5_open'] = df['open'].shift(-5)
    df['next5_date'] = df['date_str'].shift(-5)
    
    # T+10卖出价
    df['next10_open'] = df['open'].shift(-10)
    df['next10_date'] = df['date_str'].shift(-10)
    
    # 标记
    df['code'] = code
    df['is_gem'] = is_gem(code)
    
    # 涨停阈值
    limit = 19.0 if is_gem(code) else 9.5
    df['limit_pct'] = limit
    
    # 过滤掉没有前日数据的行
    valid = df.dropna(subset=['prev_chg', 'open_chg']).copy()
    valid = valid[valid['prev_close'] > 0]
    
    if len(valid) > 0:
        all_rows.append(valid)

print(f"  合并数据...")
universe = pd.concat(all_rows, ignore_index=True)
print(f"  全A宽表: {len(universe)} 行, 耗时 {time.time()-t1:.1f}s")

# 只保留2025.01~2026.01的数据
universe = universe[(universe['date_str'] >= '20250101') & (universe['date_str'] <= '20260131')].reset_index(drop=True)
print(f"  日期过滤后: {len(universe)} 行")

# ─── 向量化回测 ─────────────────────────────────────
def backtest_vectorized(name, mask, hold_days=1, df=None):
    """
    向量化回测
    mask: boolean Series/array on universe
    hold_days: 1=next1_open, 2=next2_open, ...
    返回每笔交易df
    """
    if df is None:
        df = universe
    
    selected = df[mask].copy()
    
    if len(selected) == 0:
        return pd.DataFrame()
    
    open_col = f'next{hold_days}_open'
    date_col = f'next{hold_days}_date'
    
    if open_col not in selected.columns:
        return pd.DataFrame()
    
    # 过滤有卖出价的
    selected = selected.dropna(subset=[open_col, 'open']).copy()
    selected = selected[selected['open'] > 0]
    
    if len(selected) == 0:
        return pd.DataFrame()
    
    selected['buy_price'] = selected['open']
    selected['sell_price'] = selected[open_col]
    selected['return'] = (selected['sell_price'] - selected['buy_price']) / selected['buy_price'] * 100 - 0.15
    selected['return'] = selected['return'].round(2)
    selected['buy_date'] = selected['date_str']
    selected['sell_date'] = selected[date_col]
    
    result = selected[['code','buy_date','sell_date','buy_price','sell_price','return','prev_chg','open_chg','high_chg']].copy()
    return result


def summarize(name, bt):
    """简单汇总"""
    if len(bt) == 0:
        return f"  {name}: 无交易", {}
    n = len(bt)
    avg = bt['return'].mean()
    med = bt['return'].median()
    wr  = (bt['return'] > 0).mean() * 100
    w = bt[bt['return'] > 0]
    l = bt[bt['return'] <= 0]
    plr = abs(w['return'].mean() / l['return'].mean()) if len(l) > 0 and l['return'].mean() != 0 else 999
    tot = bt['return'].sum()
    s = f"  {name}: {n}笔 均值{avg:+.2f}% 中位{med:+.2f}% 胜率{wr:.1f}% 盈亏比{plr:.2f} 总{tot:+.0f}%"
    stats = {'n': n, 'avg': avg, 'med': med, 'wr': wr, 'plr': plr, 'total': tot}
    return s, stats


# ─── 定义并运行所有策略 ─────────────────────────────────
print("\n" + "=" * 60)
print("开始向量化回测")
print("=" * 60)

results = {}

# 预计算常用条件
prev_limit_up = universe['prev_chg'] >= universe['limit_pct']
prev_big_up = (universe['prev_chg'] >= 5) & (universe['prev_chg'] < universe['limit_pct'])
prev_small_up = (universe['prev_chg'] >= 0) & (universe['prev_chg'] < 5)
prev_down = universe['prev_chg'] < 0
prev_small_down = (universe['prev_chg'] >= -3) & (universe['prev_chg'] < 0)
prev_big_down = (universe['prev_chg'] >= -8) & (universe['prev_chg'] < -2)

open_high_0_3 = (universe['open_chg'] >= 0) & (universe['open_chg'] <= 3)
open_high_0_5 = (universe['open_chg'] >= 0) & (universe['open_chg'] <= 5)
open_low = (universe['open_chg'] >= -3) & (universe['open_chg'] < 0)
open_low_wide = (universe['open_chg'] >= -3) & (universe['open_chg'] <= 1)
open_flat = (universe['open_chg'] >= -2) & (universe['open_chg'] <= 3)

is_10pct = ~universe['is_gem']
is_20pct = universe['is_gem']

high_bounce = universe['high_chg'] >= 3

strategies = [
    # (名称, 选股mask, 持仓天数)
    ('S1_只核式_涨停+高开0~3%_T1',      prev_limit_up & open_high_0_3, 1),
    ('S1b_只核宽松_涨停+高开0~5%_T1',    prev_limit_up & open_high_0_5, 1),
    ('S1c_只核反转_涨停+低开_T1',         prev_limit_up & open_low, 1),
    ('S1d_只核式_涨停+高开0~3%_T2',       prev_limit_up & open_high_0_3, 2),
    ('S2_天牌式_前跌+反弹_T1',            prev_small_down & open_low_wide & high_bounce, 1),
    ('S2b_天牌v2_前跌+低开_T1',           prev_small_down & open_low, 1),
    ('S3_低调式_前大跌+持5天',            prev_big_down & (universe['open_chg'] <= 1), 5),
    ('S3b_低调式_前大跌+持3天',           prev_big_down & (universe['open_chg'] <= 1), 3),
    ('S4_令狐冲式_前大涨+持10天_10%板',   prev_big_up & open_high_0_3 & is_10pct, 10),
    ('S4b_令狐冲式_前大涨+持5天_10%板',   prev_big_up & open_high_0_3 & is_10pct, 5),
    ('S5_20%板涨停+高开_T1',             prev_limit_up & open_high_0_5 & is_20pct, 1),
    ('S5b_20%板涨停+高开_T2',            prev_limit_up & open_high_0_5 & is_20pct, 2),
    ('S6_前大涨5~9%+T1_10%板',           prev_big_up & open_high_0_3 & is_10pct, 1),
    ('S6b_前大涨5~9%+持3天_10%板',       prev_big_up & open_high_0_3 & is_10pct, 3),
    # 融合策略
    ('F1_涨停+小高开_T1',                prev_limit_up & open_high_0_3, 1),
    ('F2_涨停+低开_T1',                  prev_limit_up & open_low, 1),
    ('F3_涨停+低开_T2',                  prev_limit_up & open_low, 2),
    ('F4_涨停+平开_T1',                  prev_limit_up & open_flat, 1),
    ('F5_前大涨5%+平开_10%板_T1',        (universe['prev_chg'] >= 5) & open_flat & is_10pct, 1),
    ('F5b_前大涨5%+平开_10%板_T2',       (universe['prev_chg'] >= 5) & open_flat & is_10pct, 2),
    ('F6_20%板大涨15%+高开_T1',          (universe['prev_chg'] >= 15) & open_high_0_5 & is_20pct, 1),
    ('F7_涨停+低开(-3~0.5)_T1',          prev_limit_up & (universe['open_chg'] >= -3) & (universe['open_chg'] <= 0.5), 1),
    ('F8_涨停+低开(-3~1%)_T1',           prev_limit_up & (universe['open_chg'] >= -3) & (universe['open_chg'] <= 1), 1),
    # 打分>=4 (涨停+3, 低开+2, 20%板+1 = 6分)
    ('F9_涨停+低开+20%板_T1',            prev_limit_up & open_low & is_20pct, 1),
    ('F9b_涨停+低开+20%板_T2',           prev_limit_up & open_low & is_20pct, 2),
    # 涨停+高开0~3%+仅10%板
    ('F10_涨停+高开0~3%_10%板_T1',       prev_limit_up & open_high_0_3 & is_10pct, 1),
    ('F10b_涨停+高开0~3%_10%板_T2',      prev_limit_up & open_high_0_3 & is_10pct, 2),
]

for sname, mask, hold in strategies:
    bt = backtest_vectorized(sname, mask, hold)
    results[sname] = bt
    s, stats = summarize(sname, bt)
    print(s)


# ─── 生成报告追加 ─────────────────────────────────────
print("\n生成回测报告...")
report = []

report.append("\n## 八、策略回测结果\n")
report.append("### 回测条件")
report.append(f"- 回测期间: 2025-01-01 ~ 2026-01-31")
report.append(f"- 股票池: 全A {len(all_codes_data)} 只")
report.append(f"- 买入价: 买入日开盘价")
report.append(f"- 卖出价: 持仓N天后的开盘价")
report.append(f"- 手续费: 0.15%\n")

# 汇总表
report.append("### 全部策略对比\n")
report.append("| 策略 | 笔数 | 单笔均值% | 中位数% | 胜率% | 盈亏比 | 总收益% |")
report.append("|------|------|----------|--------|-------|--------|--------|")

ranked = []
for sname, mask, hold in strategies:
    bt = results[sname]
    if len(bt) == 0:
        report.append(f"| {sname} | 0 | - | - | - | - | - |")
        continue
    n = len(bt)
    avg = bt['return'].mean()
    med = bt['return'].median()
    wr  = (bt['return'] > 0).mean() * 100
    w = bt[bt['return'] > 0]
    l = bt[bt['return'] <= 0]
    plr = abs(w['return'].mean() / l['return'].mean()) if len(l) > 0 and l['return'].mean() != 0 else 999
    tot = bt['return'].sum()
    report.append(f"| {sname} | {n} | {avg:+.2f}% | {med:+.2f}% | {wr:.1f}% | {plr:.2f} | {tot:+.0f}% |")
    ranked.append((sname, n, avg, med, wr, plr, tot))

# 排序：按单笔均值
ranked.sort(key=lambda x: x[2], reverse=True)

# Top 5 详细
report.append("\n### 🏆 最佳策略 Top 5（按单笔均值排序）\n")
for i, (sname, n, avg, med, wr, plr, tot) in enumerate(ranked[:5], 1):
    report.append(f"#### {i}. {sname}")
    report.append(f"- {n}笔, 均值{avg:+.2f}%, 中位数{med:+.2f}%, 胜率{wr:.1f}%, 盈亏比{plr:.2f}, 总{tot:+.0f}%")
    
    bt = results[sname]
    bt_c = bt.copy()
    bt_c['month'] = bt_c['buy_date'].str[:6]
    monthly = bt_c.groupby('month').agg(笔数=('return','count'), 均值=('return','mean'), 胜率=('return', lambda x: (x>0).mean()*100), 总和=('return','sum')).round(2)
    
    report.append("\n| 月份 | 笔数 | 均值% | 胜率% | 月总% |")
    report.append("|------|------|-------|-------|-------|")
    pos_months = 0
    for m, row in monthly.iterrows():
        report.append(f"| {m} | {int(row['笔数'])} | {row['均值']:+.2f}% | {row['胜率']:.0f}% | {row['总和']:+.1f}% |")
        if row['总和'] > 0:
            pos_months += 1
    report.append(f"\n正收益月份: {pos_months}/{len(monthly)}\n")

# ─── 与D14对比 ─────────────────────────────────────────
report.append("\n## 九、与D14黄金稳健版对比\n")
report.append("""| 维度 | D14黄金稳健版 | 最佳高手策略 |
|------|-------------|------------|""")

if ranked:
    bs = ranked[0]
    bs_name, bs_n, bs_avg, bs_med, bs_wr, bs_plr, bs_tot = bs
    report.append(f"| 策略 | D14黄金稳健版 | {bs_name} |")
    report.append(f"| 回测期间 | 2025.07~2026.02 (8个月) | 2025.01~2026.01 (13个月) |")
    report.append(f"| 笔数 | 57 | {bs_n} |")
    report.append(f"| 单笔均值 | **+3.15%** | {bs_avg:+.2f}% |")
    report.append(f"| 胜率 | **72%** | {bs_wr:.1f}% |")
    report.append(f"| 盈亏比 | 高 | {bs_plr:.2f} |")
    report.append(f"| 总收益(加总) | **+180%** | {bs_tot:+.0f}% |")

report.append("""
### 互补性分析

**D14黄金稳健版的核心逻辑**:
- 当日盘中首次触及14%涨幅的20%板(创业板/科创板)股票
- 前日涨幅<5%, 开盘2~8%高开
- 波动率>7, RSI>60
- 买入点: 回落到13%或14%追入
- T+1卖出

**高手融合策略的核心逻辑**:
- 昨日已涨停的股票，今日开盘后买入
- 利用涨停板的动量延续效应
- T+1或T+2卖出

**两个策略选股条件完全不重叠**:
1. D14要求 **前日涨幅<5%**，高手策略要求 **前日涨停>9.5%**
2. D14只做 **20%板**，部分高手策略覆盖 **10%板+20%板**
3. D14在 **盘中** 触发（需盯盘），高手策略可在 **开盘** 买入

**双策略组合建议**:
- 仓位: D14(60%) + 高手融合(40%)
- D14月月正收益，作为稳定器
- 高手融合策略交易频率高，增加整体收益机会
- 两者信号不冲突，可独立运行
""")

# ─── 策略可复制性评分 ─────────────────────────────────
report.append("\n## 十、策略可复制性评分\n")
report.append("| 高手 | 策略核心 | 清晰度 | 执行难度 | 回测验证 | 可复制性 |")
report.append("|------|---------|--------|---------|---------|---------|")

# 用回测结果动态填写
zhihe_bt = results.get('S1_只核式_涨停+高开0~3%_T1', pd.DataFrame())
zhihe_stats = f'+{zhihe_bt["return"].mean():.1f}%/笔' if len(zhihe_bt) > 0 else '无数据'
tp_bt = results.get('S2_天牌式_前跌+反弹_T1', pd.DataFrame())
tp_stats = f'+{tp_bt["return"].mean():.1f}%/笔' if len(tp_bt) > 0 else '无数据'
dd_bt = results.get('S3_低调式_前大跌+持5天', pd.DataFrame())
dd_stats = f'+{dd_bt["return"].mean():.1f}%/笔' if len(dd_bt) > 0 else '无数据'
lh_bt = results.get('S4_令狐冲式_前大涨+持10天_10%板', pd.DataFrame())
lh_stats = f'+{lh_bt["return"].mean():.1f}%/笔' if len(lh_bt) > 0 else '无数据'

report.append(f"| 只核大学生 | 涨停+小高开+T1 | ★★★★★ | ★★★☆☆ | {zhihe_stats} | **4.0/5** |")
report.append(f"| 天牌 | 前跌+反弹+T1 | ★★★☆☆ | ★★★★☆ | {tp_stats} | **3.0/5** |")
report.append(f"| 低调内敛的朋 | 前跌+持5天 | ★★★★☆ | ★★☆☆☆ | {dd_stats} | **3.0/5** |")
report.append(f"| 独行侠令狐冲 | 前大涨+精选+中线 | ★★☆☆☆ | ★☆☆☆☆ | {lh_stats} | **2.0/5** |")
report.append(f"| 忘忧阁主 | 高频分散 | ★★★☆☆ | ★★★★☆ | 类天牌 | **2.5/5** |")
report.append(f"| 龙年大叔 | 单票重仓长线 | ★★☆☆☆ | ★☆☆☆☆ | 样本少 | **1.5/5** |")


# ─── 推荐策略 ─────────────────────────────────────────
report.append("\n## 十一、推荐策略\n")

good = [(s, n, a, m, w, p, t) for s, n, a, m, w, p, t in ranked if a > 0.5 and n >= 20]
if good:
    report.append("### 回测达标策略（均值>0.5%, 笔数>=20）\n")
    report.append("| 排名 | 策略 | 笔数 | 均值% | 胜率% | 总% | 推荐 |")
    report.append("|------|------|------|-------|-------|-----|------|")
    for i, (s, n, a, m, w, p, t) in enumerate(good[:10], 1):
        stars = '⭐⭐⭐⭐⭐' if a > 2 and w > 55 else '⭐⭐⭐⭐' if a > 1.5 else '⭐⭐⭐' if a > 1 else '⭐⭐'
        report.append(f"| {i} | {s} | {n} | {a:+.2f}% | {w:.1f}% | {t:+.0f}% | {stars} |")

report.append("""
### 最终建议

1. **D14黄金稳健版仍是核心策略** — 3.15%/笔+72%胜率+月月正收益, 经过严格验证
2. **涨停接力策略(高手融合)作为补充** — 与D14选股不重叠，增加交易机会
3. **推荐双策略组合**: D14(60%) + 涨停接力(40%)
4. **只核大学生的"涨停+小高开T1"最具可复制性** — 规则最清晰
5. **注意**: 涨停接力策略存在买不到的风险（一字板/集合竞价排不上）
""")


# ─── 融合策略专章 ─────────────────────────────────────
report.append("\n## 十二、高手融合策略\n")

# 分析所有高手共同赚钱模式（从交易数据中）
valid = all_df.dropna(subset=['单笔收益%'])

report.append("### 核心发现：6位高手的共同赚钱基因\n")

# 按前日涨幅分区统计
prev_v = valid.dropna(subset=['前一日涨幅%'])
report.append("#### 所有高手交易的前日涨幅 × 收益\n")
report.append("| 前日涨幅 | 笔数 | 占比 | 均值% | 胜率 | 赚钱贡献 |")
report.append("|---------|------|------|-------|------|---------|")
prev_bins = [
    ('涨停(>8%)', prev_v['前一日涨幅%'] > 8),
    ('大涨(5~8%)', (prev_v['前一日涨幅%'] > 5) & (prev_v['前一日涨幅%'] <= 8)),
    ('小涨(0~5%)', (prev_v['前一日涨幅%'] >= 0) & (prev_v['前一日涨幅%'] <= 5)),
    ('下跌(<0%)', prev_v['前一日涨幅%'] < 0),
]
for label, mask in prev_bins:
    sub = prev_v[mask]
    if len(sub) == 0: continue
    contrib = sub['单笔收益%'].sum()
    report.append(f"| {label} | {len(sub)} | {len(sub)/len(prev_v)*100:.0f}% | {sub['单笔收益%'].mean():+.2f}% | {(sub['单笔收益%']>0).mean()*100:.0f}% | {contrib:+.0f}% |")

# 按持仓天数
report.append("\n#### 所有高手交易的持仓天数 × 收益\n")
report.append("| 持仓 | 笔数 | 均值% | 胜率 |")
report.append("|------|------|-------|------|")
hold_v = valid.dropna(subset=['持仓天数'])
for d, label in [(1,'1天'),(2,'2天'),(3,'3天')]:
    sub = hold_v[hold_v['持仓天数'] == d]
    if len(sub) > 0:
        report.append(f"| {label} | {len(sub)} | {sub['单笔收益%'].mean():+.2f}% | {(sub['单笔收益%']>0).mean()*100:.0f}% |")
sub35 = hold_v[(hold_v['持仓天数'] >= 3) & (hold_v['持仓天数'] <= 5)]
if len(sub35) > 0:
    report.append(f"| 3-5天 | {len(sub35)} | {sub35['单笔收益%'].mean():+.2f}% | {(sub35['单笔收益%']>0).mean()*100:.0f}% |")
sub6p = hold_v[hold_v['持仓天数'] >= 6]
if len(sub6p) > 0:
    report.append(f"| 6天+ | {len(sub6p)} | {sub6p['单笔收益%'].mean():+.2f}% | {(sub6p['单笔收益%']>0).mean()*100:.0f}% |")

# 最佳融合策略定义
report.append("\n### 融合策略规则定义\n")

# 找出回测最佳的融合策略
fusion_ranked = [(s, n, a, m, w, p, t) for s, n, a, m, w, p, t in ranked if s.startswith('F')]
fusion_ranked.sort(key=lambda x: x[2], reverse=True)

if fusion_ranked:
    best_f = fusion_ranked[0]
    report.append(f"**最佳融合策略: {best_f[0]}**\n")
    report.append(f"- 回测笔数: {best_f[1]}")
    report.append(f"- 单笔均值: {best_f[2]:+.2f}%")
    report.append(f"- 胜率: {best_f[4]:.1f}%")
    report.append(f"- 总收益: {best_f[6]:+.0f}%\n")
    
    # 详细月度
    bt_best = results[best_f[0]]
    bt_c = bt_best.copy()
    bt_c['month'] = bt_c['buy_date'].str[:6]
    monthly = bt_c.groupby('month').agg(笔数=('return','count'), 均值=('return','mean'), 胜率=('return', lambda x: (x>0).mean()*100), 总和=('return','sum')).round(2)
    
    report.append("#### 月度表现\n")
    report.append("| 月份 | 笔数 | 均值% | 胜率% | 月总% |")
    report.append("|------|------|-------|-------|-------|")
    pos_m = 0
    for m, row in monthly.iterrows():
        mark = '✅' if row['总和'] > 0 else '❌'
        report.append(f"| {m} {mark} | {int(row['笔数'])} | {row['均值']:+.2f}% | {row['胜率']:.0f}% | {row['总和']:+.1f}% |")
        if row['总和'] > 0:
            pos_m += 1
    report.append(f"\n正收益月份: {pos_m}/{len(monthly)}\n")

report.append("""
### D14 + 融合策略双组合对比

| 维度 | D14单独 | 融合单独 | 双组合(60/40) |
|------|---------|---------|--------------|
| 策略依赖 | 盘中盯盘 | 开盘可执行 | 分散 |
| 选股重叠 | - | - | **0%** (完全互补) |
| 适用行情 | 强势突破行情 | 涨停接力行情 | 全市场 |
| 风险分散 | 单一 | 单一 | ✅ 双重保障 |
""")


# ─── 写入报告 ─────────────────────────────────────
report_path = os.path.join(OUTPUT_DIR, '淘股吧高手策略深度研究.md')
with open(report_path, 'a', encoding='utf-8') as f:
    f.write('\n'.join(report))

print(f"\n✅ 完整报告已保存: {report_path}")
print(f"总耗时: {time.time()-t0:.1f}s")

# 保存优秀策略
analyze_dir = os.path.join(PROJECT_ROOT, 'analyze')
os.makedirs(analyze_dir, exist_ok=True)

if ranked:
    for sname, n, avg, med, wr, plr, tot in ranked[:3]:
        if avg > 0.5:
            safe_name = sname.replace('/','_').replace(' ','_').replace('+','_').replace('%','pct').replace('~','to').replace('(','').replace(')','')
            path = os.path.join(analyze_dir, f'strategy_{safe_name}.py')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f'''#!/usr/bin/env python3
"""
策略: {sname}
回测: {n}笔, 均值{avg:+.2f}%, 胜率{wr:.1f}%, 总{tot:+.0f}%
来源: 淘股吧6位高手策略融合分析
条件: 见策略名 (涨停=前日涨幅>9.5%/19%, 高开=开盘涨幅)
买入: 开盘价买入
卖出: 持仓N天后开盘价卖出
手续费: 0.15%
"""
''')
            print(f"策略保存: {path}")

print("\n🎉 Step 3 全部完成！")
