"""
只核大学生策略复刻+优化 回测 v2
=================================
修复: 数据加载优化 + 条件A信号修复
"""

import pandas as pd
import numpy as np
import os
import glob
from collections import defaultdict

KLINE_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d'
OUTPUT_DIR = '/Users/tq/PycharmProjects/stocks_analysis/output'
INITIAL_CAPITAL = 113893  # 11.39万

# 策略参数
MAX_POSITIONS = 3
STOP_LOSS = -0.07
DEFAULT_HOLD_DAYS = 2
EXTEND_HOLD_DAYS = 3
EXTEND_THRESHOLD = 0.08

print("=" * 60)
print("只核大学生策略复刻+优化 v2")
print("=" * 60)

# ==== Step 1: 只加载2025年日线 ====
print("\n[1/5] 加载2025年日线数据...")

files_2025 = glob.glob(os.path.join(KLINE_DIR, '*_*_20250101_20251231.csv'))
print(f"  找到 {len(files_2025)} 个2025年数据文件")

all_klines = {}
for f in files_2025:
    try:
        basename = os.path.basename(f)
        parts = basename.split('_')
        code = parts[0]
        market = parts[1]
        
        df = pd.read_csv(f)
        if len(df) < 5:
            continue
        
        # 过滤停牌+无量股
        df = df[df['volume'] > 0].reset_index(drop=True)
        
        key = f"{code}_{market}"
        all_klines[key] = df
    except:
        continue

print(f"  成功加载 {len(all_klines)} 只股票")

# ==== Step 2: 上证指数 ====
print("\n[2/5] 加载上证指数...")

# 用平安银行or上证综指代替
index_key = None
for k in all_klines:
    if k.startswith('000001_SH'):
        # 判断是平安银行还是指数（看价格）
        df = all_klines[k]
        if df['close'].mean() > 100:  # 指数
            index_key = k
            break

if index_key is None:
    # 用沪深300ETF代替
    for k in ['510300_SH', '510050_SH']:
        if k in all_klines:
            index_key = k
            break

if index_key:
    idx_df = all_klines[index_key].copy()
    idx_df['ma20'] = idx_df['close'].rolling(20).mean()
    idx_df['above_ma20'] = idx_df['close'] > idx_df['ma20']
    index_signal = dict(zip(idx_df['date'], idx_df['above_ma20']))
    print(f"  使用 {index_key} 作为大盘指标，{idx_df['above_ma20'].sum()}/{len(idx_df)}天在20日线上方")
else:
    print("  未找到指数，不使用大盘过滤")
    index_signal = defaultdict(lambda: True)

# ==== Step 3: 预计算每日选股信号 ====
print("\n[3/5] 扫描选股信号...")

daily_signals = defaultdict(list)
all_dates_set = set()

for key, df in all_klines.items():
    code = key.split('_')[0]
    market = key.split('_')[1]
    
    # 跳过指数
    if key == index_key:
        continue
    # 跳过北交所（920开头）
    if code.startswith('920') or market == 'BJ':
        continue
    
    dates = df['date'].values
    opens = df['open'].values
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    pre_closes = df['preClose'].values
    volumes = df['volume'].values
    amounts = df['amount'].values
    
    all_dates_set.update(dates)
    
    for i in range(1, len(df)):
        if pre_closes[i] <= 0 or pre_closes[i-1] <= 0:
            continue
        if amounts[i] < 5000000:  # 成交额>500万
            continue
        
        # 今日开盘涨幅
        open_pct = (opens[i] - pre_closes[i]) / pre_closes[i]
        # 前日涨幅
        prev_pct = (closes[i-1] - pre_closes[i-1]) / pre_closes[i-1]
        prev_limit_up = prev_pct >= 0.098
        
        # 条件A: 前日涨5~9.8%（非涨停）+ 当日开盘<3%
        cond_a = (0.05 <= prev_pct < 0.098) and (open_pct < 0.03)
        # 条件B: 前日涨停 + 当日低开
        cond_b = prev_limit_up and (open_pct < 0)
        
        if cond_a or cond_b:
            daily_signals[dates[i]].append({
                'code': code,
                'key': key,
                'condition': 'A' if cond_a else 'B',
                'prev_pct': prev_pct,
                'open_pct': open_pct,
                'open': opens[i],
                'close': closes[i],
                'date': dates[i],
                'amount': amounts[i],
            })

total_signals = sum(len(v) for v in daily_signals.values())
cond_a_total = sum(1 for v in daily_signals.values() for s in v if s['condition'] == 'A')
cond_b_total = sum(1 for v in daily_signals.values() for s in v if s['condition'] == 'B')
print(f"  {len(daily_signals)}个交易日产生信号")
print(f"  总信号: {total_signals} (条件A: {cond_a_total}, 条件B: {cond_b_total})")
print(f"  日均: {total_signals / max(len(daily_signals),1):.1f}个")

# ==== Step 4: 回测 ====
print("\n[4/5] 执行回测...")

all_dates = sorted(all_dates_set)

class Position:
    def __init__(self, code, key, buy_date, buy_price, shares, condition):
        self.code = code
        self.key = key
        self.buy_date = buy_date
        self.buy_price = buy_price
        self.shares = shares
        self.condition = condition
        self.hold_days = 0
        self.max_pnl = 0
        self.current_price = buy_price

def run_backtest(name, use_filter, use_optimized_sell, use_cond_a=True, use_cond_b=True):
    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    daily_equity = []
    
    for date in all_dates:
        above_ma20 = index_signal.get(date, True)
        candidates = daily_signals.get(date, [])
        
        # 过滤条件类型
        if not use_cond_a:
            candidates = [c for c in candidates if c['condition'] != 'A']
        if not use_cond_b:
            candidates = [c for c in candidates if c['condition'] != 'B']
        
        # 更新持仓
        for pos in positions:
            kline = all_klines.get(pos.key)
            if kline is None:
                continue
            day = kline[kline['date'] == date]
            if len(day) > 0:
                pos.current_price = day.iloc[0]['close']
                pos.hold_days += 1
                pnl = (pos.current_price - pos.buy_price) / pos.buy_price
                pos.max_pnl = max(pos.max_pnl, pnl)
        
        # 卖出
        to_sell = []
        for pos in positions:
            kline = all_klines.get(pos.key)
            if kline is None:
                continue
            day = kline[kline['date'] == date]
            if len(day) == 0:
                continue
            
            today_open = day.iloc[0]['open']
            today_close = day.iloc[0]['close']
            pnl_open = (today_open - pos.buy_price) / pos.buy_price
            pnl_close = (today_close - pos.buy_price) / pos.buy_price
            
            sell_reason = None
            sell_price = today_close
            
            # 止损
            if pnl_open <= STOP_LOSS:
                sell_reason = '止损'
                sell_price = today_open
            elif pnl_close <= STOP_LOSS:
                sell_reason = '止损'
                sell_price = pos.buy_price * (1 + STOP_LOSS)
            
            # 大盘过滤清仓
            if use_filter and not above_ma20 and sell_reason is None:
                sell_reason = '大盘清仓'
                sell_price = today_open
            
            # 持仓到期
            if sell_reason is None:
                if use_optimized_sell:
                    target = EXTEND_HOLD_DAYS if pos.max_pnl >= EXTEND_THRESHOLD else DEFAULT_HOLD_DAYS
                else:
                    target = DEFAULT_HOLD_DAYS
                if pos.hold_days >= target:
                    sell_reason = f'持仓到期'
                    sell_price = today_open
            
            if sell_reason:
                to_sell.append((pos, sell_price, sell_reason))
        
        for pos, price, reason in to_sell:
            revenue = pos.shares * price
            cash += revenue
            pnl = (price - pos.buy_price) / pos.buy_price
            trades.append({
                'code': pos.code,
                'buy_date': pos.buy_date,
                'sell_date': date,
                'buy_price': pos.buy_price,
                'sell_price': price,
                'pnl_pct': pnl,
                'hold_days': pos.hold_days,
                'condition': pos.condition,
                'reason': reason,
            })
            positions.remove(pos)
        
        # 买入
        can_buy = True
        if use_filter and not above_ma20:
            can_buy = False
        
        if can_buy and candidates and len(positions) < MAX_POSITIONS:
            # 优先选条件A（盈亏比更高），按前日涨幅排序
            sorted_cands = sorted(candidates, key=lambda x: (-({'A':1,'B':0}[x['condition']]), -x['prev_pct']))
            
            for cand in sorted_cands:
                if len(positions) >= MAX_POSITIONS:
                    break
                if any(p.code == cand['code'] for p in positions):
                    continue
                
                equity = cash + sum(p.current_price * p.shares for p in positions)
                alloc = equity / MAX_POSITIONS
                invest = min(alloc, cash)
                shares = int(invest / cand['open'] / 100) * 100
                if shares <= 0:
                    continue
                
                cost = shares * cand['open']
                cash -= cost
                positions.append(Position(
                    cand['code'], cand['key'], date, cand['open'], shares, cand['condition']
                ))
        
        # 记录
        pos_val = sum(p.current_price * p.shares for p in positions)
        equity = cash + pos_val
        ret = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        daily_equity.append({'date': date, 'equity': equity, 'cum_return_pct': ret, 'positions': len(positions)})
    
    return trades, daily_equity

# 跑多个策略版本
strategies = {
    '策略1_纯条件A': (False, False, True, False),      # 只用条件A，无过滤
    '策略2_纯条件B': (False, False, False, True),      # 只用条件B
    '策略3_AB混合': (False, False, True, True),         # AB混合
    '策略4_AB+大盘过滤': (True, False, True, True),    # 加大盘
    '策略5_AB+大盘+优化卖出': (True, True, True, True), # 全优化
    '策略6_A+大盘+优化卖出': (True, True, True, False), # 只用A+全优化
}

results = {}
for name, (filt, opt_sell, cond_a, cond_b) in strategies.items():
    trades, equity = run_backtest(name, filt, opt_sell, cond_a, cond_b)
    results[name] = (trades, equity)

# ==== Step 5: 报告 ====
print("\n" + "=" * 80)
print("回测结果对比")
print("=" * 80)

for name, (trades, equity) in results.items():
    if not trades:
        print(f"\n{name}: 无交易")
        continue
    
    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(equity)
    
    n = len(tdf)
    wins = (tdf['pnl_pct'] > 0).sum()
    wr = wins / n
    avg_win = tdf[tdf['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = tdf[tdf['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if (n - wins) > 0 else 0
    pr = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    final = edf['cum_return_pct'].iloc[-1]
    peak_ret = edf['cum_return_pct'].max()
    
    cum = edf['cum_return_pct'].values
    peak = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()
    
    daily_rets = edf['equity'].pct_change().dropna()
    sharpe = daily_rets.mean() / daily_rets.std() * np.sqrt(244) if daily_rets.std() > 0 else 0
    
    ca = tdf[tdf['condition'] == 'A']
    cb = tdf[tdf['condition'] == 'B']
    
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")
    print(f"  交易: {n}笔 | 胜率: {wr:.1%} | 盈利: +{avg_win:.1f}% | 亏损: {avg_loss:.1f}% | 盈亏比: {pr:.2f}")
    print(f"  ★ 最终收益: {final:+.1f}% | 峰值: {peak_ret:+.1f}% | 最大回撤: {max_dd:.1f}% | 夏普: {sharpe:.3f}")

    if len(ca) > 0:
        ca_wr = (ca['pnl_pct']>0).mean()
        ca_avg = ca['pnl_pct'].mean()*100
        print(f"  条件A: {len(ca)}笔 | 胜率{ca_wr:.1%} | 均收益{ca_avg:+.1f}%")
    if len(cb) > 0:
        cb_wr = (cb['pnl_pct']>0).mean()
        cb_avg = cb['pnl_pct'].mean()*100
        print(f"  条件B: {len(cb)}笔 | 胜率{cb_wr:.1%} | 均收益{cb_avg:+.1f}%")
    
    # 月度
    edf['month'] = edf['date'] // 100 % 100
    prev = 0
    months_str = []
    for m, grp in edf.groupby('month'):
        end = grp['cum_return_pct'].iloc[-1]
        delta = end - prev
        months_str.append(f"{m}月:{delta:+.0f}%")
        prev = end
    print(f"  月度: {' | '.join(months_str)}")
    
    # 保存
    safe = name.replace('+', '_').replace('/', '_')
    tdf.to_csv(f'{OUTPUT_DIR}/zhihe_v2_{safe}_trades.csv', index=False, encoding='utf-8-sig')
    edf.to_csv(f'{OUTPUT_DIR}/zhihe_v2_{safe}_equity.csv', index=False, encoding='utf-8-sig')

print(f"\n{'='*80}")
print(f"  基准: 只核大学生实盘 +794.2% (胜率44.6%, 盈亏比2.58)")
print(f"{'='*80}")
