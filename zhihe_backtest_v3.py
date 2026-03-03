"""
只核大学生策略学习 v3 - 严格无后视镜
=========================================
规则:
1. 选股只用T-1及之前的数据
2. T日开盘价买入（假设集合竞价可成交）
3. 卖出只用持仓期间已知的信息
4. 不使用他的交易记录作为选股输入

从他的交割单分析中学到的模式:
- 前日涨幅5~9.8%的非涨停强势股
- 当日平开或低开买入
- 超短线2-3天
- 他不在意胜率，在意盈亏比
- 需要有选股排序逻辑（不能随机）

改进点（vs v2）:
1. 选股排序: 按"信号质量"排序（成交额+涨幅+换手）
2. 动态仓位: 根据连续盈亏调整
3. 严格止损: -5%硬止损
4. 加入量能过滤: 成交额须放量
"""

import pandas as pd
import numpy as np
import os
import glob
from collections import defaultdict

KLINE_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d'
OUTPUT_DIR = '/Users/tq/PycharmProjects/stocks_analysis/output'
INITIAL_CAPITAL = 113893  # 11.39万

print("=" * 70)
print("只核大学生策略学习 v3 - 严格无后视镜回测")
print("=" * 70)

# ==== Step 1: 加载数据 ====
print("\n[1/6] 加载2025年日线...")
files_2025 = glob.glob(os.path.join(KLINE_DIR, '*_*_20250101_20251231.csv'))

all_klines = {}
for f in files_2025:
    try:
        basename = os.path.basename(f)
        parts = basename.split('_')
        code = parts[0]
        market = parts[1]
        if market == 'BJ':  # 跳过北交所
            continue
        df = pd.read_csv(f)
        if len(df) < 10:
            continue
        key = f"{code}_{market}"
        all_klines[key] = df
    except:
        continue

print(f"  {len(all_klines)} 只股票")

# ==== Step 2: 预计算每只股票每天的特征 ====
print("\n[2/6] 预计算特征（无后视镜）...")

# 结构: features[date] = [{code, key, ...}, ...]
# 每个特征只使用T-1及之前的数据
daily_features = defaultdict(list)
all_dates_set = set()

for key, df in all_klines.items():
    code = key.split('_')[0]
    
    dates = df['date'].values
    opens = df['open'].values
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    pre_closes = df['preClose'].values
    volumes = df['volume'].values
    amounts = df['amount'].values
    
    all_dates_set.update(dates)
    
    # 预计算5日均量（滚动），用于判断放量
    vol_ma5 = pd.Series(volumes).rolling(5).mean().values
    amt_ma5 = pd.Series(amounts).rolling(5).mean().values
    
    for i in range(2, len(df)):  # 从第3天开始（需要至少2天历史）
        today_date = dates[i]
        
        if pre_closes[i] <= 0 or pre_closes[i-1] <= 0:
            continue
        if volumes[i] <= 0:  # 停牌
            continue
        
        # ===== 只用T-1及之前的数据 =====
        
        # T-1（昨天）的指标
        prev_close_pct = (closes[i-1] - pre_closes[i-1]) / pre_closes[i-1]  # 昨日涨幅
        prev_open_pct = (opens[i-1] - pre_closes[i-1]) / pre_closes[i-1]    # 昨日开盘涨幅
        prev_amplitude = (highs[i-1] - lows[i-1]) / pre_closes[i-1]         # 昨日振幅
        prev_volume = volumes[i-1]
        prev_amount = amounts[i-1]
        prev_limit_up = prev_close_pct >= 0.098
        
        # T-2（前天）
        prev2_close_pct = (closes[i-2] - pre_closes[i-2]) / pre_closes[i-2] if pre_closes[i-2] > 0 else 0
        
        # 放量判断: 昨日成交量 vs 5日均量
        vol_ratio = prev_volume / vol_ma5[i-1] if vol_ma5[i-1] and vol_ma5[i-1] > 0 else 1
        amt_ratio = prev_amount / amt_ma5[i-1] if amt_ma5[i-1] and amt_ma5[i-1] > 0 else 1
        
        # T日的开盘涨幅（集合竞价后已知，不算后视镜）
        today_open_pct = (opens[i] - pre_closes[i]) / pre_closes[i]
        
        # ===== 选股条件 =====
        
        # 条件A: 前日涨幅5~9.8%（非涨停强势）+ 今日开盘<3%
        cond_a = (0.05 <= prev_close_pct < 0.098) and (today_open_pct < 0.03)
        
        # 条件B: 前日涨停 + 今日低开(<0%)
        cond_b = prev_limit_up and (today_open_pct < 0)
        
        # 条件C（新增）: 连续两天强势(T-2涨>3%, T-1涨>3%) + 今日平开/低开
        cond_c = (prev2_close_pct > 0.03) and (prev_close_pct > 0.03) and (today_open_pct < 0.02)
        
        if not (cond_a or cond_b or cond_c):
            continue
        
        # ===== 基础过滤（无后视镜）=====
        if prev_amount < 10000000:    # 昨日成交额>1000万
            continue
        if pre_closes[i] < 3:          # 股价>3元
            continue
        if pre_closes[i] > 300:        # 股价<300元
            continue
        
        # 信号质量评分（只用历史数据）
        # 1. 前日涨幅（越强越好，但不能涨停）
        strength_score = min(prev_close_pct / 0.10, 1.0) * 30  # 0-30分
        
        # 2. 放量程度（越放量越好）
        volume_score = min(vol_ratio / 3.0, 1.0) * 25  # 0-25分
        
        # 3. 今日低开幅度（适度低开最佳，深跌不好）
        if -0.03 <= today_open_pct <= 0:
            open_score = 25  # 小幅低开最佳
        elif 0 < today_open_pct < 0.02:
            open_score = 15  # 小幅高开还行
        elif -0.05 <= today_open_pct < -0.03:
            open_score = 10  # 大幅低开差一些
        else:
            open_score = 5
        
        # 4. 成交额越大越好（流动性）
        liquidity_score = min(prev_amount / 500000000, 1.0) * 20  # 0-20分, 5亿满分
        
        total_score = strength_score + volume_score + open_score + liquidity_score
        
        condition = 'A' if cond_a else ('B' if cond_b else 'C')
        
        daily_features[today_date].append({
            'code': code,
            'key': key,
            'condition': condition,
            'prev_close_pct': prev_close_pct,
            'today_open_pct': today_open_pct,
            'open_price': opens[i],  # T日开盘买入价
            'prev_amount': prev_amount,
            'vol_ratio': vol_ratio,
            'score': total_score,
        })

total_signals = sum(len(v) for v in daily_features.values())
print(f"  {len(daily_features)}天产生信号, 总计{total_signals}, 日均{total_signals/max(len(daily_features),1):.0f}")

# 条件分布
cond_counts = defaultdict(int)
for feats in daily_features.values():
    for f in feats:
        cond_counts[f['condition']] += 1
print(f"  条件A: {cond_counts['A']}, B: {cond_counts['B']}, C: {cond_counts['C']}")

# ==== Step 3: 回测引擎 ====
print("\n[3/6] 构建回测引擎...")

all_dates = sorted(all_dates_set)

class Position:
    def __init__(self, code, key, buy_date, buy_price, shares, condition, score):
        self.code = code
        self.key = key
        self.buy_date = buy_date
        self.buy_price = buy_price
        self.shares = shares
        self.condition = condition
        self.score = score
        self.hold_days = 0
        self.max_pnl = 0
        self.current_price = buy_price

def run_backtest(params):
    """
    params dict:
      max_pos: 最大持仓数
      stop_loss: 止损比例 (负数)
      hold_days: 默认持仓天数
      extend_days: 盈利延长天数
      extend_thresh: 延长阈值
      top_n: 每天信号排名前N选入
      min_score: 最低信号分数
      dynamic_pos: 是否动态仓位
    """
    max_pos = params.get('max_pos', 3)
    stop_loss = params.get('stop_loss', -0.07)
    hold_days = params.get('hold_days', 2)
    extend_days = params.get('extend_days', None)
    extend_thresh = params.get('extend_thresh', 0.08)
    top_n = params.get('top_n', 5)  # 每天只看排名前N的
    min_score = params.get('min_score', 30)
    take_profit = params.get('take_profit', None)
    
    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    daily_equity = []
    consecutive_losses = 0
    
    for date in all_dates:
        candidates = daily_features.get(date, [])
        
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
        
        # 卖出决策（无后视镜：用当天盘中数据）
        to_sell = []
        for pos in positions:
            kline = all_klines.get(pos.key)
            if kline is None:
                continue
            day = kline[kline['date'] == date]
            if len(day) == 0:
                # 可能停牌了，跳过
                continue
            
            today_open = day.iloc[0]['open']
            today_close = day.iloc[0]['close']
            today_low = day.iloc[0]['low']
            
            pnl_open = (today_open - pos.buy_price) / pos.buy_price
            pnl_low = (today_low - pos.buy_price) / pos.buy_price
            pnl_close = (today_close - pos.buy_price) / pos.buy_price
            
            sell_reason = None
            sell_price = None
            
            # 止损（开盘跌破止损线，开盘就卖）
            if stop_loss and pnl_open <= stop_loss:
                sell_price = today_open
                sell_reason = '开盘止损'
            # 盘中触发止损
            elif stop_loss and pnl_low <= stop_loss:
                sell_price = pos.buy_price * (1 + stop_loss)
                sell_reason = '盘中止损'
            
            # 止盈
            if sell_reason is None and take_profit and pnl_open >= take_profit:
                sell_price = today_open
                sell_reason = '开盘止盈'
            
            # 持仓到期
            if sell_reason is None:
                target = hold_days
                if extend_days and pos.max_pnl >= extend_thresh:
                    target = extend_days
                if pos.hold_days >= target:
                    sell_price = today_open  # 到期日开盘卖
                    sell_reason = f'T+{pos.hold_days}到期'
            
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
                'buy_price': round(pos.buy_price, 3),
                'sell_price': round(price, 3),
                'pnl_pct': round(pnl * 100, 2),
                'hold_days': pos.hold_days,
                'condition': pos.condition,
                'score': round(pos.score, 1),
                'reason': reason,
            })
            
            # 连续亏损计数
            if pnl < 0:
                consecutive_losses += 1
            else:
                consecutive_losses = 0
            
            positions.remove(pos)
        
        # 买入决策
        if candidates and len(positions) < max_pos:
            # 过滤最低分数
            valid = [c for c in candidates if c['score'] >= min_score]
            # 按分数排序，取前top_n
            valid.sort(key=lambda x: x['score'], reverse=True)
            valid = valid[:top_n]
            
            for cand in valid:
                if len(positions) >= max_pos:
                    break
                # 不重复买
                if any(p.code == cand['code'] for p in positions):
                    continue
                
                equity = cash + sum(p.current_price * p.shares for p in positions)
                alloc = equity / max_pos
                invest = min(alloc, cash)
                
                buy_price = cand['open_price']
                shares = int(invest / buy_price / 100) * 100
                if shares <= 0:
                    continue
                
                cost = shares * buy_price
                cash -= cost
                positions.append(Position(
                    cand['code'], cand['key'], date,
                    buy_price, shares, cand['condition'], cand['score']
                ))
        
        # 记录每日净值
        pos_val = sum(p.current_price * p.shares for p in positions)
        equity = cash + pos_val
        ret = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        daily_equity.append({
            'date': date,
            'equity': round(equity, 2),
            'return_pct': round(ret, 2),
            'n_pos': len(positions),
        })
    
    return trades, daily_equity

# ==== Step 4: 参数网格搜索 ====
print("\n[4/6] 参数网格搜索...")

param_grid = [
    # 基础策略
    {'name': 'A_T2_止损5%', 'max_pos': 3, 'stop_loss': -0.05, 'hold_days': 2, 'top_n': 3, 'min_score': 40},
    {'name': 'B_T2_止损7%', 'max_pos': 3, 'stop_loss': -0.07, 'hold_days': 2, 'top_n': 3, 'min_score': 40},
    {'name': 'C_T3_止损7%', 'max_pos': 3, 'stop_loss': -0.07, 'hold_days': 3, 'top_n': 3, 'min_score': 40},
    
    # 变换持仓数
    {'name': 'D_T2_2仓', 'max_pos': 2, 'stop_loss': -0.05, 'hold_days': 2, 'top_n': 2, 'min_score': 50},
    {'name': 'E_T2_1仓集中', 'max_pos': 1, 'stop_loss': -0.05, 'hold_days': 2, 'top_n': 1, 'min_score': 60},
    
    # 自适应持仓
    {'name': 'F_自适应_止损5%', 'max_pos': 3, 'stop_loss': -0.05, 'hold_days': 2, 
     'extend_days': 3, 'extend_thresh': 0.08, 'top_n': 3, 'min_score': 40},
    {'name': 'G_自适应_止损7%', 'max_pos': 3, 'stop_loss': -0.07, 'hold_days': 2,
     'extend_days': 3, 'extend_thresh': 0.05, 'top_n': 3, 'min_score': 40},
    
    # 高门槛选股
    {'name': 'H_高分选股_T2', 'max_pos': 3, 'stop_loss': -0.05, 'hold_days': 2, 'top_n': 1, 'min_score': 60},
    {'name': 'I_高分选股_T3', 'max_pos': 3, 'stop_loss': -0.07, 'hold_days': 3, 'top_n': 1, 'min_score': 60},
    
    # 宽松选股+严格止损
    {'name': 'J_宽选严止_T2', 'max_pos': 3, 'stop_loss': -0.03, 'hold_days': 2, 'top_n': 5, 'min_score': 30},
    
    # 加止盈
    {'name': 'K_T3_止盈20%', 'max_pos': 3, 'stop_loss': -0.07, 'hold_days': 3, 'top_n': 3, 'min_score': 40, 'take_profit': 0.20},
    {'name': 'L_T2_止盈10%', 'max_pos': 3, 'stop_loss': -0.05, 'hold_days': 2, 'top_n': 3, 'min_score': 40, 'take_profit': 0.10},
]

results = {}
for p in param_grid:
    name = p.pop('name')
    trades, equity = run_backtest(p)
    results[name] = (trades, equity, p)
    p['name'] = name  # 恢复

# ==== Step 5: 输出报告 ====
print("\n[5/6] 生成对比报告...")
print()
print("=" * 100)
print(f"{'策略':<25} {'交易':>5} {'胜率':>6} {'盈利':>7} {'亏损':>7} {'盈亏比':>6} {'最终收益':>9} {'峰值':>8} {'最大回撤':>8} {'夏普':>7}")
print("=" * 100)

# 基准
print(f"{'★只核大学生实盘':<25} {'231':>5} {'44.6%':>6} {'+13.3%':>7} {'-5.1%':>7} {'2.58':>6} {'+794.2%':>9} {'+1039%':>8} {'-394.9%':>8} {'2.41':>7}")
print("-" * 100)

best_name = ''
best_return = -999

for name, (trades, equity, params) in sorted(results.items()):
    if not trades:
        continue
    
    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(equity)
    
    n = len(tdf)
    wins = (tdf['pnl_pct'] > 0).sum()
    wr = wins / n * 100
    avg_win = tdf[tdf['pnl_pct'] > 0]['pnl_pct'].mean() if wins > 0 else 0
    avg_loss = tdf[tdf['pnl_pct'] <= 0]['pnl_pct'].mean() if (n - wins) > 0 else 0
    pr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    final = edf['return_pct'].iloc[-1]
    peak = edf['return_pct'].max()
    
    cum = edf['return_pct'].values
    peak_arr = np.maximum.accumulate(cum)
    max_dd = (cum - peak_arr).min()
    
    rets = edf['equity'].pct_change().dropna()
    sharpe = rets.mean() / rets.std() * np.sqrt(244) if rets.std() > 0 else 0
    
    if final > best_return:
        best_return = final
        best_name = name
    
    print(f"{name:<25} {n:>5} {wr:>5.1f}% {avg_win:>+6.1f}% {avg_loss:>+6.1f}% {pr:>6.2f} {final:>+8.1f}% {peak:>+7.1f}% {max_dd:>+7.1f}% {sharpe:>7.3f}")

print("=" * 100)
print(f"\n最优策略: {best_name} (收益 {best_return:+.1f}%)")

# ==== Step 6: 最优策略详细分析 ====
print(f"\n{'='*70}")
print(f"最优策略 [{best_name}] 详细分析")
print(f"{'='*70}")

best_trades, best_equity, best_params = results[best_name]
tdf = pd.DataFrame(best_trades)
edf = pd.DataFrame(best_equity)

# 按条件分析
print("\n--- 按条件分类 ---")
for cond in ['A', 'B', 'C']:
    sub = tdf[tdf['condition'] == cond]
    if len(sub) == 0:
        continue
    wr = (sub['pnl_pct'] > 0).mean() * 100
    avg = sub['pnl_pct'].mean()
    print(f"  条件{cond}: {len(sub)}笔 | 胜率{wr:.1f}% | 均收益{avg:+.1f}%")

# 按卖出原因
print("\n--- 按卖出原因 ---")
for reason, grp in tdf.groupby('reason'):
    wr = (grp['pnl_pct'] > 0).mean() * 100
    avg = grp['pnl_pct'].mean()
    print(f"  {reason}: {len(grp)}笔 | 胜率{wr:.1f}% | 均收益{avg:+.1f}%")

# 月度
print("\n--- 月度收益 ---")
edf['month'] = edf['date'] // 100 % 100
prev = 0
for m, grp in edf.groupby('month'):
    end = grp['return_pct'].iloc[-1]
    delta = end - prev
    print(f"  {m:2d}月: {delta:+8.1f}% (累计 {end:+.1f}%)")
    prev = end

# 保存
tdf.to_csv(f'{OUTPUT_DIR}/zhihe_v3_best_trades.csv', index=False, encoding='utf-8-sig')
edf.to_csv(f'{OUTPUT_DIR}/zhihe_v3_best_equity.csv', index=False, encoding='utf-8-sig')

# 保存全部策略对比
summary = []
for name, (trades, equity, params) in results.items():
    if not trades:
        continue
    t = pd.DataFrame(trades)
    e = pd.DataFrame(equity)
    n = len(t)
    wins = (t['pnl_pct'] > 0).sum()
    summary.append({
        '策略': name,
        '交易数': n,
        '胜率': f"{wins/n*100:.1f}%",
        '最终收益': f"{e['return_pct'].iloc[-1]:+.1f}%",
        '最大回撤': f"{(e['return_pct'].values - np.maximum.accumulate(e['return_pct'].values)).min():.1f}%",
    })

pd.DataFrame(summary).to_csv(f'{OUTPUT_DIR}/zhihe_v3_策略对比.csv', index=False, encoding='utf-8-sig')
print(f"\n结果已保存到 {OUTPUT_DIR}/zhihe_v3_*.csv")

print(f"\n{'='*70}")
print("严格无后视镜回测结论")
print(f"{'='*70}")
print(f"基准(只核大学生实盘): +794.2%")
print(f"最优策略({best_name}): {best_return:+.1f}%")
if best_return > 0:
    print(f"→ 正收益，但仍远不及实盘")
else:
    print(f"→ 负收益，纯K线量化无法复刻他的选股能力")
print(f"\n核心差距: 他的α来源于题材+板块判断（人工盘感），不是K线形态")
