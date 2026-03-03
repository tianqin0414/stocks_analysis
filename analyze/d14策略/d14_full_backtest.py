#!/usr/bin/env python3
"""
D14策略 全月份回测（优化版）
============================
策略核心：日内峰值涨幅≥14%的股票，在突破14%时买入。
优化：先用日线快速筛选，再只对命中股票加载1m数据。

数据覆盖：2025-02 ~ 2026-02

用法：
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/PycharmProjects/stocks_v2/venv/bin/python3 analyze/d14_full_backtest.py
"""
from __future__ import annotations

import os
import sys
import glob
import time
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import KLINE_ROOT, OUTPUT_DIR
from data_loader import code_to_exchange

# ============================================================
# 配置
# ============================================================
THRESHOLD_PCT = 14.0
KLINE_1D_DIR = os.path.join(KLINE_ROOT, '1d')
KLINE_1M_DIR = os.path.join(KLINE_ROOT, '1m')

MONTHS = sorted([d for d in os.listdir(KLINE_1M_DIR) 
                 if os.path.isdir(os.path.join(KLINE_1M_DIR, d)) and d.isdigit()])

# 月份编码 → 日期范围
def month_to_date_range(m: str) -> Tuple[str, str]:
    """2512 → (20251201, 20251231)"""
    if len(m) == 4:
        yy, mm = int(m[:2]), int(m[2:])
        year = 2000 + yy
        start = f'{year}{mm:02d}01'
        # 月末
        if mm == 12:
            end = f'{year}1231'
        else:
            import calendar
            last_day = calendar.monthrange(year, mm)[1]
            end = f'{year}{mm:02d}{last_day:02d}'
        return start, end
    return m, m


# ============================================================
# Step 1: 日线快速筛选
# ============================================================
def scan_1d_for_candidates(threshold: float) -> Dict[str, List[Tuple[str, float, float, float]]]:
    """
    扫描所有日线文件，找出峰值涨幅≥threshold的(code, date)组合。
    返回: {code: [(date_str, pre_close, day_close, day_high), ...]}
    """
    print(f"📊 扫描日线数据，筛选峰值涨幅≥{threshold}%...")
    
    all_files = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    print(f"   日线文件: {len(all_files)}")
    
    # 按code分组
    code_files: Dict[str, List[str]] = defaultdict(list)
    for f in all_files:
        bn = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) >= 2:
            code = parts[0]
            # 排除北交所
            if not (code.startswith('4') or code.startswith('8')):
                code_files[code].append(f)
    
    print(f"   覆盖股票: {len(code_files)} 只（排除北交所）")
    
    candidates: Dict[str, List[Tuple[str, float, float, float]]] = defaultdict(list)
    total = len(code_files)
    
    for i, (code, files) in enumerate(sorted(code_files.items())):
        if (i + 1) % 1000 == 0:
            print(f"   进度: {i+1}/{total} 命中: {sum(len(v) for v in candidates.values())}")
        
        # 读取所有日线文件
        dfs = []
        for f in sorted(files):
            try:
                df = pd.read_csv(f, encoding='utf-8-sig')
                if not {'date', 'open', 'high', 'low', 'close'}.issubset(df.columns):
                    continue
                df['date_str'] = df['date'].astype(str).str[:8]
                for col in ['open', 'high', 'low', 'close']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                if 'preClose' in df.columns:
                    df['preClose'] = pd.to_numeric(df['preClose'], errors='coerce')
                dfs.append(df)
            except Exception:
                continue
        
        if not dfs:
            continue
        
        df_1d = pd.concat(dfs).drop_duplicates('date_str').sort_values('date_str').reset_index(drop=True)
        
        for idx in range(len(df_1d)):
            row = df_1d.iloc[idx]
            high = row['high']
            close_p = row['close']
            open_p = row['open']
            
            if pd.isna(high) or pd.isna(close_p):
                continue
            
            # preClose
            pc = row.get('preClose', None)
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                pc = float('nan')
            if pd.isna(pc) or pc <= 0:
                if idx > 0:
                    pc = df_1d.iloc[idx - 1]['close']
                else:
                    continue
            if pd.isna(pc) or pc <= 0:
                continue
            
            peak_pct = (high - pc) / pc * 100
            if peak_pct >= threshold:
                date_str = row['date_str']
                
                # 次日数据
                next_open = None
                next_close = None
                next_high = None
                next_low = None
                if idx < len(df_1d) - 1:
                    nxt = df_1d.iloc[idx + 1]
                    next_open = float(nxt['open']) if pd.notna(nxt['open']) else None
                    next_close = float(nxt['close']) if pd.notna(nxt['close']) else None
                    next_high = float(nxt['high']) if pd.notna(nxt['high']) else None
                    next_low = float(nxt['low']) if pd.notna(nxt['low']) else None
                
                candidates[code].append((
                    date_str, float(pc), float(close_p), float(high),
                    float(open_p), next_open, next_close, next_high, next_low
                ))
    
    total_hits = sum(len(v) for v in candidates.values())
    print(f"   ✅ 筛选完成: {len(candidates)} 只股票, {total_hits} 个交易日")
    return candidates


# ============================================================
# Step 2: 分钟线模拟交易
# ============================================================
def simulate_trade(code: str, date_str: str, day_1m: pd.DataFrame,
                   pre_close: float, day_close: float, day_open: float,
                   next_open: Optional[float], next_close: Optional[float],
                   next_high: Optional[float], next_low: Optional[float],
                   month: str) -> Optional[dict]:
    """模拟一笔D14交易"""
    
    is_20pct = str(code).startswith('3') or str(code).startswith('68')
    limit_pct = 0.20 if is_20pct else 0.10
    
    buy_target = pre_close * (1 + THRESHOLD_PCT / 100)
    open_pct = (day_open - pre_close) / pre_close * 100
    
    # 找买入点
    buy_idx = None
    buy_price = buy_target
    buy_time = None
    buy_time_minutes = None
    
    for i in range(len(day_1m)):
        row = day_1m.iloc[i]
        if row['high'] >= buy_target:
            buy_idx = i
            buy_time = row['time_str']
            buy_time_minutes = row.get('time_minutes', 570)
            break
    
    if buy_idx is None:
        return None
    
    # 涨停封死检查
    last_bar = day_1m.iloc[-1]
    limit_price = pre_close * (1 + limit_pct)
    is_limit_up_close = (abs(last_bar['close'] - limit_price) <= limit_price * 0.005
                         and last_bar['close'] >= last_bar['open'] * 0.99)
    
    # 开盘即涨停封死 → 买不到
    if buy_idx <= 1 and is_limit_up_close:
        return None
    
    # 买入后的分钟线
    after_buy = day_1m.iloc[buy_idx + 1:]
    remaining = len(after_buy)
    
    # 买后日内最高价
    if remaining > 0:
        day_peak_after = after_buy['high'].max()
        day_low_after = after_buy['low'].min()
    else:
        day_peak_after = buy_price
        day_low_after = buy_price
    
    # === S1: 当天收盘卖 ===
    s1 = (last_bar['close'] - buy_price) / buy_price * 100
    
    # === S2: 次日开盘卖 ===
    s2 = (next_open - buy_price) / buy_price * 100 if next_open else None
    
    # === S3: 次日收盘卖 ===
    s3 = (next_close - buy_price) / buy_price * 100 if next_close else None
    
    # === S4: 动态止盈止损（日内）===
    # +3%启动trailing, 从峰值回撤1.5%止盈, -3%止损
    s4 = s1  # default
    peak = buy_price
    for _, bar in after_buy.iterrows():
        if bar['low'] <= buy_price * 0.97:
            s4 = -3.0
            break
        if bar['high'] > peak:
            peak = bar['high']
        if peak > buy_price * 1.03:
            trail = peak * 0.985
            if bar['low'] <= trail:
                s4 = (trail - buy_price) / buy_price * 100
                break
    
    # === S5: 目标17%止盈，-2%止损 ===
    target_17 = pre_close * 1.17
    stop_2 = buy_price * 0.98
    s5 = s1
    for _, bar in after_buy.iterrows():
        if bar['low'] <= stop_2:
            s5 = -2.0
            break
        if bar['high'] >= target_17:
            s5 = (target_17 - buy_price) / buy_price * 100
            break
    
    # === S6: 目标16%止盈，-2%止损 ===
    target_16 = pre_close * 1.16
    s6 = s1
    for _, bar in after_buy.iterrows():
        if bar['low'] <= stop_2:
            s6 = -2.0
            break
        if bar['high'] >= target_16:
            s6 = (target_16 - buy_price) / buy_price * 100
            break
    
    # === S7: 次日最高（理论最优）===
    s7 = (next_high - buy_price) / buy_price * 100 if next_high else None
    
    # === S8: 目标18%止盈，-2%止损 ===
    target_18 = pre_close * 1.18
    s8 = s1
    for _, bar in after_buy.iterrows():
        if bar['low'] <= stop_2:
            s8 = -2.0
            break
        if bar['high'] >= target_18:
            s8 = (target_18 - buy_price) / buy_price * 100
            break
    
    # === S9: 目标15%止盈（赚1个百分点），-1%止损 ===
    target_15 = pre_close * 1.15
    stop_1 = buy_price * 0.99
    s9 = s1
    for _, bar in after_buy.iterrows():
        if bar['low'] <= stop_1:
            s9 = -1.0
            break
        if bar['high'] >= target_15:
            s9 = (target_15 - buy_price) / buy_price * 100
            break
    
    return {
        '月份': month,
        '股票代码': code,
        '日期': date_str,
        '买入时间': buy_time,
        '买入价': round(buy_price, 3),
        'preClose': round(pre_close, 3),
        '开盘涨幅%': round(open_pct, 2),
        '峰值涨幅%': round((day_1m['high'].max() - pre_close) / pre_close * 100, 2),
        '收盘涨幅%': round((day_close - pre_close) / pre_close * 100, 2),
        '买后剩余分钟': remaining,
        '买后最高%': round((day_peak_after - buy_price) / buy_price * 100, 2),
        '买后最低%': round((day_low_after - buy_price) / buy_price * 100, 2),
        'S1_当天收盘%': round(s1, 2),
        'S2_次日开盘%': round(s2, 2) if s2 is not None else None,
        'S3_次日收盘%': round(s3, 2) if s3 is not None else None,
        'S4_动态止盈止损%': round(s4, 2),
        'S5_目标17%_止损2%': round(s5, 2),
        'S6_目标16%_止损2%': round(s6, 2),
        'S7_次日最高%': round(s7, 2) if s7 is not None else None,
        'S8_目标18%_止损2%': round(s8, 2),
        'S9_目标15%_止损1%': round(s9, 2),
        '板块': '20%板' if is_20pct else '10%板',
    }


def main():
    t0 = time.time()
    
    print("=" * 70)
    print(f"🔍 D14策略全月份回测 | 阈值: ≥{THRESHOLD_PCT}%")
    print(f"   月份: {MONTHS[0]} ~ {MONTHS[-1]} ({len(MONTHS)}个月)")
    print("=" * 70)
    
    # Step 1: 日线筛选
    candidates = scan_1d_for_candidates(THRESHOLD_PCT)
    
    # Step 2: 分月份加载1m模拟
    print(f"\n📈 Step 2: 逐月加载1m数据模拟交易...")
    
    all_trades = []
    monthly_stats = []
    
    for month_dir in MONTHS:
        month_start, month_end = month_to_date_range(month_dir)
        month_path = os.path.join(KLINE_1M_DIR, month_dir)
        
        # 找出该月份候选的(code, date)
        month_candidates = []
        for code, entries in candidates.items():
            for entry in entries:
                date_str = entry[0]
                if month_start <= date_str <= month_end:
                    month_candidates.append((code, entry))
        
        if not month_candidates:
            print(f"   {month_dir}: 无候选")
            continue
        
        print(f"   {month_dir}: {len(month_candidates)} 个候选...", end=" ", flush=True)
        
        month_trades = []
        loaded_1m = {}  # cache
        
        for code, entry in month_candidates:
            date_str, pc, day_close, day_high, day_open, n_open, n_close, n_high, n_low = entry
            
            # 加载1m数据（缓存）
            if code not in loaded_1m:
                exchange = code_to_exchange(code)
                pattern = os.path.join(month_path, f'{code}_{exchange}_*.csv')
                flist = glob.glob(pattern)
                if flist:
                    try:
                        df = pd.read_csv(flist[0], encoding='utf-8-sig')
                        if {'date', 'open', 'high', 'low', 'close'}.issubset(df.columns):
                            df['date_str'] = df['date'].astype(str).str[:8]
                            if 'time' in df.columns:
                                df['time_dt'] = pd.to_datetime(df['time'], unit='ms', utc=True).dt.tz_convert('Asia/Shanghai')
                                df['time_str'] = df['time_dt'].dt.strftime('%H:%M')
                                df['time_minutes'] = df['time_dt'].dt.hour * 60 + df['time_dt'].dt.minute
                            else:
                                df['time_str'] = '09:30'
                                df['time_minutes'] = 570
                            for c in ['open', 'high', 'low', 'close']:
                                df[c] = pd.to_numeric(df[c], errors='coerce')
                            loaded_1m[code] = df
                        else:
                            loaded_1m[code] = None
                    except Exception:
                        loaded_1m[code] = None
                else:
                    loaded_1m[code] = None
            
            df_1m_all = loaded_1m.get(code)
            if df_1m_all is None:
                continue
            
            # 取该天的分钟数据
            day_1m = df_1m_all[df_1m_all['date_str'] == date_str].reset_index(drop=True)
            if len(day_1m) < 5:
                continue
            
            trade = simulate_trade(
                code, date_str, day_1m, pc, day_close, day_open,
                n_open, n_close, n_high, n_low, month_dir
            )
            if trade:
                month_trades.append(trade)
        
        loaded_1m.clear()  # 释放内存
        
        if month_trades:
            mdf = pd.DataFrame(month_trades)
            stats = {'月份': month_dir, '交易数': len(month_trades)}
            for col_name in ['S1_当天收盘%', 'S5_目标17%_止损2%', 'S6_目标16%_止损2%', 
                            'S9_目标15%_止损1%', 'S8_目标18%_止损2%']:
                v = mdf[col_name].dropna()
                if len(v) > 0:
                    short = col_name.split('_', 1)[1] if '_' in col_name else col_name
                    stats[f'{short}_均值'] = round(v.mean(), 2)
                    stats[f'{short}_胜率'] = round((v > 0).mean() * 100, 1)
            monthly_stats.append(stats)
            
            s1m = mdf['S1_当天收盘%'].mean()
            s5m = mdf['S5_目标17%_止损2%'].mean()
            s6m = mdf['S6_目标16%_止损2%'].mean()
            print(f"✅ {len(month_trades)}笔 | S1:{s1m:+.2f}% S5_17%:{s5m:+.2f}% S6_16%:{s6m:+.2f}%")
        else:
            print(f"无成交")
        
        all_trades.extend(month_trades)
    
    # ============================================================
    # 汇总报告
    # ============================================================
    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"📊 D14策略全月份回测报告 | 耗时: {elapsed:.0f}秒")
    print(f"{'=' * 70}")
    
    if not all_trades:
        print("⚠️ 没有交易记录")
        return
    
    df_all = pd.DataFrame(all_trades)
    
    print(f"\n总交易: {len(df_all)} 笔 | 月份数: {len(monthly_stats)}")
    
    # 策略汇总表
    strategies = [
        ('S1_当天收盘%', 'S1:当天收盘'),
        ('S2_次日开盘%', 'S2:次日开盘'),
        ('S3_次日收盘%', 'S3:次日收盘'),
        ('S4_动态止盈止损%', 'S4:动态止盈止损'),
        ('S9_目标15%_止损1%', 'S9:目标15%止损1%'),
        ('S6_目标16%_止损2%', 'S6:目标16%止损2%'),
        ('S5_目标17%_止损2%', 'S5:目标17%止损2%'),
        ('S8_目标18%_止损2%', 'S8:目标18%止损2%'),
        ('S7_次日最高%', 'S7:次日最高(理论)'),
    ]
    
    print(f"\n{'策略':<24} {'均值':>7} {'中位数':>7} {'胜率':>6} {'盈亏比':>6} {'累计':>8} {'笔数':>5}")
    print("-" * 72)
    
    for col, name in strategies:
        v = df_all[col].dropna()
        if len(v) == 0:
            continue
        mean_v = v.mean()
        median_v = v.median()
        win_rate = (v > 0).mean() * 100
        wins = v[v > 0]
        losses = v[v < 0]
        if len(losses) > 0 and losses.mean() != 0:
            pnl = abs(wins.mean() / losses.mean()) if len(wins) > 0 else 0
        else:
            pnl = 99.9 if len(wins) > 0 else 0
        cumulative = v.sum()
        print(f"  {name:<22} {mean_v:>+6.2f}% {median_v:>+6.2f}% {win_rate:>5.1f}% {pnl:>5.2f} {cumulative:>+7.1f}% {len(v):>5}")
    
    # 月度明细
    print(f"\n📅 月度明细：")
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.width', 200)
    ms_df = pd.DataFrame(monthly_stats)
    print(ms_df.to_string(index=False))
    
    # 按买入时间
    print(f"\n⏰ 按买入时间（S1: 当天收盘）:")
    df_all['buy_hour'] = df_all['买入时间'].str.split(':').str[0].astype(int)
    for h in sorted(df_all['buy_hour'].unique()):
        sub = df_all[df_all['buy_hour'] == h]
        v = sub['S1_当天收盘%']
        print(f"  {h:>2}时: {len(sub):>5}笔 | 均值:{v.mean():>+6.2f}% | 胜率:{(v>0).mean()*100:>5.1f}%")
    
    # 按开盘涨幅
    print(f"\n📈 按开盘涨幅（S1: 当天收盘）:")
    bins = [-100, -5, 0, 3, 5, 8, 10, 15, 100]
    labels = ['<-5%', '-5~0%', '0~3%', '3~5%', '5~8%', '8~10%', '10~15%', '>15%']
    df_all['open_grp'] = pd.cut(df_all['开盘涨幅%'], bins=bins, labels=labels)
    for g in labels:
        sub = df_all[df_all['open_grp'] == g]
        if len(sub) >= 3:
            v = sub['S1_当天收盘%']
            v5 = sub['S5_目标17%_止损2%']
            print(f"  {g:>8}: {len(sub):>5}笔 | S1均值:{v.mean():>+6.2f}% 胜率:{(v>0).mean()*100:>5.1f}% | S5均值:{v5.mean():>+6.2f}%")
    
    # 按板块
    print(f"\n🏷️ 按板块:")
    for bk, sub in df_all.groupby('板块'):
        v = sub['S1_当天收盘%']
        v5 = sub['S5_目标17%_止损2%']
        print(f"  {bk}: {len(sub):>5}笔 | S1:{v.mean():>+6.2f}% 胜率:{(v>0).mean()*100:>5.1f}% | S5:{v5.mean():>+6.2f}%")
    
    # 保存
    out1 = os.path.join(OUTPUT_DIR, 'd14_full_backtest.xlsx')
    df_all.to_excel(out1, index=False)
    print(f"\n💾 交易明细: {out1}")
    
    out2 = os.path.join(OUTPUT_DIR, 'd14_monthly_stats.xlsx')
    ms_df.to_excel(out2, index=False)
    print(f"💾 月度统计: {out2}")


if __name__ == '__main__':
    main()
