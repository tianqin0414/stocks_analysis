"""
只核大学生策略复刻 + 优化回测
===============================
核心选股条件（从交割单数据分析得出）:
- 条件A: 前日涨幅5~9.8%（非涨停强势股）+ 当日平开/低开(开盘涨幅<3%)
- 条件B: 前日涨停 + 当日低开(<0%)
- 大盘趋势过滤: 上证指数 > 20日均线时才开仓

卖出策略:
- 基础: 持仓2天后卖出（T+2）
- 优化1: 持仓期间盈利>=8%，延长到第3天
- 优化2: 单笔止损-7%强制出局
- 优化3: 大盘跌破20日线，持仓全清

仓位管理:
- 最多同时持3只股票，每只1/3仓位
- 大盘<20日均线时空仓
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime, timedelta
from collections import defaultdict

# ==== 配置 ====
KLINE_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d'
OUTPUT_DIR = '/Users/tq/PycharmProjects/stocks_analysis/output'
INITIAL_CAPITAL = 113893  # 11.39万，和他一样的起始资金

# 策略参数
MAX_POSITIONS = 3          # 最多持仓数
STOP_LOSS = -0.07          # 止损线 -7%
DEFAULT_HOLD_DAYS = 2      # 默认持仓天数
EXTEND_HOLD_DAYS = 3       # 盈利延长持仓
EXTEND_THRESHOLD = 0.08    # 延长持仓的盈利阈值 8%
USE_MARKET_FILTER = True   # 是否使用大盘过滤
MA_PERIOD = 20             # 均线周期

print("=" * 60)
print("只核大学生策略复刻+优化 回测系统")
print("=" * 60)

# ==== Step 1: 加载所有2025年日线数据 ====
print("\n[1/5] 加载日线数据...")

def load_all_klines():
    """加载所有股票的2025年日线数据"""
    all_data = {}
    files = glob.glob(os.path.join(KLINE_DIR, '*_2025*.csv'))
    # 也加载跨年的文件
    files += glob.glob(os.path.join(KLINE_DIR, '*_20250101_*.csv'))
    files += glob.glob(os.path.join(KLINE_DIR, '*_20240101_*.csv'))  # 可能包含2025初数据
    
    # 去重
    files = list(set(files))
    
    loaded = 0
    for f in files:
        try:
            basename = os.path.basename(f)
            code = basename.split('_')[0]
            market = basename.split('_')[1]
            
            df = pd.read_csv(f)
            if len(df) == 0:
                continue
            
            # 只保留2025年数据
            df = df[(df['date'] >= 20250101) & (df['date'] <= 20251231)]
            if len(df) == 0:
                continue
            
            key = f"{code}_{market}"
            if key in all_data:
                all_data[key] = pd.concat([all_data[key], df]).drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
            else:
                all_data[key] = df.sort_values('date').reset_index(drop=True)
            loaded += 1
        except Exception as e:
            continue
    
    print(f"  加载了 {loaded} 个文件，{len(all_data)} 只股票")
    return all_data

all_klines = load_all_klines()

# ==== Step 2: 加载上证指数 ====
print("\n[2/5] 加载上证指数...")

def load_index():
    """加载上证指数"""
    # 尝试找上证指数文件
    patterns = [
        os.path.join(KLINE_DIR, '000001_SH_*2025*.csv'),
        os.path.join(KLINE_DIR, '999999_SH_*.csv'),
    ]
    
    for p in patterns:
        files = glob.glob(p)
        if files:
            dfs = [pd.read_csv(f) for f in files]
            df = pd.concat(dfs).drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
            df = df[(df['date'] >= 20250101) & (df['date'] <= 20251231)]
            if len(df) > 100:  # 指数应该有很多数据
                print(f"  找到指数数据: {len(df)} 天")
                return df
    
    # 如果找不到指数，用所有股票的平均收益代替
    print("  未找到上证指数，使用全市场平均代替")
    return None

index_data = load_index()

# 计算指数20日均线
if index_data is not None:
    index_data['ma20'] = index_data['close'].rolling(MA_PERIOD).mean()
    index_data['above_ma20'] = index_data['close'] > index_data['ma20']
    index_dates = dict(zip(index_data['date'], index_data['above_ma20']))
else:
    # 如果没有指数数据，默认全部允许交易
    index_dates = defaultdict(lambda: True)

# ==== Step 3: 按日扫描选股 ====
print("\n[3/5] 扫描选股信号...")

def get_stock_features(kline_df, idx):
    """获取某天的股票特征"""
    if idx < 1 or idx >= len(kline_df):
        return None
    
    today = kline_df.iloc[idx]
    yesterday = kline_df.iloc[idx - 1]
    
    pre_close = today['preClose']
    if pre_close <= 0 or yesterday['preClose'] <= 0:
        return None
    
    # 停牌过滤
    if today.get('suspendFlag', 0) == 1:
        return None
    if today['volume'] <= 0:
        return None
    
    # 计算指标
    open_pct = (today['open'] - pre_close) / pre_close
    close_pct = (today['close'] - pre_close) / pre_close
    prev_close_pct = (yesterday['close'] - yesterday['preClose']) / yesterday['preClose']
    prev_limit_up = prev_close_pct >= 0.098  # 涨停
    
    return {
        'date': today['date'],
        'open': today['open'],
        'close': today['close'],
        'high': today['high'],
        'low': today['low'],
        'pre_close': pre_close,
        'open_pct': open_pct,
        'close_pct': close_pct,
        'prev_close_pct': prev_close_pct,
        'prev_limit_up': prev_limit_up,
        'volume': today['volume'],
        'amount': today['amount'],
    }

# 建立每天的候选股池
daily_candidates = defaultdict(list)

for key, kline in all_klines.items():
    code = key.split('_')[0]
    market = key.split('_')[1]
    
    # 跳过ST、退市股（简化判断：跳过代码以3开头的创业板中价格<2的）
    # 跳过指数
    if code.startswith('399') or code.startswith('000001') and market == 'SH':
        if market == 'SH' and code == '000001':
            # 这是平安银行不是指数... 看价格判断
            if len(kline) > 0 and kline.iloc[0]['close'] < 5:
                continue
    
    for i in range(1, len(kline)):
        features = get_stock_features(kline, i)
        if features is None:
            continue
        
        date = features['date']
        
        # ===== 选股条件 =====
        
        # 条件A: 前日涨幅5~9.8%（非涨停强势股）+ 当日平开/低开(开盘涨幅<3%)
        cond_a = (0.05 <= features['prev_close_pct'] < 0.098) and (features['open_pct'] < 0.03)
        
        # 条件B: 前日涨停 + 当日低开(<0%)
        cond_b = features['prev_limit_up'] and (features['open_pct'] < 0)
        
        if cond_a or cond_b:
            # 过滤低流动性
            if features['amount'] < 5000000:  # 成交额<500万排除
                continue
            
            daily_candidates[date].append({
                'code': code,
                'market': market,
                'key': key,
                'condition': 'A' if cond_a else 'B',
                **features,
            })

# 统计
total_signals = sum(len(v) for v in daily_candidates.values())
print(f"  共 {len(daily_candidates)} 个交易日产生信号")
print(f"  总信号数: {total_signals}")
print(f"  日均信号: {total_signals / max(len(daily_candidates), 1):.1f}")

# ==== Step 4: 回测引擎 ====
print("\n[4/5] 执行回测...")

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

class BacktestEngine:
    def __init__(self, initial_capital):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = []  # List[Position]
        self.trades = []      # 完成的交易记录
        self.daily_equity = []  # 每日净值
        self.daily_log = []
    
    def get_total_equity(self):
        pos_value = sum(p.current_price * p.shares for p in self.positions)
        return self.cash + pos_value
    
    def buy(self, code, key, date, price, condition):
        """买入"""
        if len(self.positions) >= MAX_POSITIONS:
            return False
        
        # 每只分配等额资金
        equity = self.get_total_equity()
        alloc = equity / MAX_POSITIONS
        if self.cash < alloc * 0.5:  # 现金不够一半就不买
            return False
        
        invest = min(alloc, self.cash)
        shares = int(invest / price / 100) * 100  # 整百股
        if shares <= 0:
            return False
        
        cost = shares * price
        self.cash -= cost
        
        pos = Position(code, key, date, price, shares, condition)
        self.positions.append(pos)
        return True
    
    def sell(self, pos, date, price, reason):
        """卖出"""
        revenue = pos.shares * price
        self.cash += revenue
        
        pnl_pct = (price - pos.buy_price) / pos.buy_price
        
        self.trades.append({
            'code': pos.code,
            'buy_date': pos.buy_date,
            'sell_date': date,
            'buy_price': pos.buy_price,
            'sell_price': price,
            'shares': pos.shares,
            'pnl_pct': pnl_pct,
            'pnl_amount': revenue - pos.shares * pos.buy_price,
            'hold_days': pos.hold_days,
            'condition': pos.condition,
            'sell_reason': reason,
        })
        
        self.positions.remove(pos)
    
    def update_daily(self, date, all_klines):
        """每日更新持仓价格"""
        for pos in self.positions:
            kline = all_klines.get(pos.key)
            if kline is None:
                continue
            day_data = kline[kline['date'] == date]
            if len(day_data) > 0:
                pos.current_price = day_data.iloc[0]['close']
                pos.hold_days += 1
                pnl = (pos.current_price - pos.buy_price) / pos.buy_price
                pos.max_pnl = max(pos.max_pnl, pnl)
    
    def record_daily(self, date):
        equity = self.get_total_equity()
        ret = (equity - self.initial_capital) / self.initial_capital * 100
        self.daily_equity.append({
            'date': date,
            'equity': equity,
            'cash': self.cash,
            'positions': len(self.positions),
            'cum_return_pct': ret,
        })

# 获取所有交易日期（排序）
all_dates = sorted(set(
    d for kline in all_klines.values() 
    for d in kline['date'].values 
    if 20250101 <= d <= 20251231
))
print(f"  2025年交易日: {len(all_dates)}天")

# ===== 策略1: 原始策略（无大盘过滤） =====
engine1 = BacktestEngine(INITIAL_CAPITAL)

# ===== 策略2: 加大盘过滤 =====
engine2 = BacktestEngine(INITIAL_CAPITAL)

# ===== 策略3: 加大盘过滤 + 优化卖出 =====
engine3 = BacktestEngine(INITIAL_CAPITAL)

engines = {
    '策略1_原始': engine1,
    '策略2_大盘过滤': engine2, 
    '策略3_大盘过滤+优化卖出': engine3,
}

for date in all_dates:
    above_ma20 = index_dates.get(date, True)
    candidates = daily_candidates.get(date, [])
    
    for name, engine in engines.items():
        use_filter = '大盘过滤' in name
        use_optimized_sell = '优化卖出' in name
        
        # 更新持仓价格
        engine.update_daily(date, all_klines)
        
        # 卖出检查
        to_sell = []
        for pos in engine.positions:
            kline = all_klines.get(pos.key)
            if kline is None:
                continue
            day_data = kline[kline['date'] == date]
            if len(day_data) == 0:
                continue
            
            today_close = day_data.iloc[0]['close']
            today_open = day_data.iloc[0]['open']
            pnl = (today_close - pos.buy_price) / pos.buy_price
            pnl_open = (today_open - pos.buy_price) / pos.buy_price
            
            sell_reason = None
            sell_price = today_close
            
            # 止损（用开盘价触发，更真实）
            if pnl_open <= STOP_LOSS:
                sell_reason = '止损'
                sell_price = today_open  # 开盘就卖
            elif pnl <= STOP_LOSS:
                sell_reason = '止损'
                sell_price = pos.buy_price * (1 + STOP_LOSS)
            
            # 大盘过滤：跌破均线清仓
            if use_filter and not above_ma20:
                sell_reason = '大盘过滤清仓'
                sell_price = today_close
            
            # 持仓天数到期
            if sell_reason is None:
                if use_optimized_sell:
                    # 优化: 盈利>=8%延长到第3天
                    target_days = EXTEND_HOLD_DAYS if pos.max_pnl >= EXTEND_THRESHOLD else DEFAULT_HOLD_DAYS
                else:
                    target_days = DEFAULT_HOLD_DAYS
                
                if pos.hold_days >= target_days:
                    sell_reason = f'持仓{pos.hold_days}天到期'
                    sell_price = today_open  # T+N开盘卖
            
            if sell_reason:
                to_sell.append((pos, sell_price, sell_reason))
        
        for pos, price, reason in to_sell:
            engine.sell(pos, date, price, reason)
        
        # 买入
        can_buy = True
        if use_filter and not above_ma20:
            can_buy = False
        
        if can_buy and candidates and len(engine.positions) < MAX_POSITIONS:
            # 按前日涨幅排序，选最强的
            sorted_cands = sorted(candidates, key=lambda x: x['prev_close_pct'], reverse=True)
            
            for cand in sorted_cands:
                if len(engine.positions) >= MAX_POSITIONS:
                    break
                # 避免重复买入同一只
                if any(p.code == cand['code'] for p in engine.positions):
                    continue
                # 用开盘价买入（更真实）
                engine.buy(cand['code'], cand['key'], date, cand['open'], cand['condition'])
        
        engine.record_daily(date)

# ==== Step 5: 输出结果 ====
print("\n[5/5] 生成回测报告...")
print("=" * 80)

for name, engine in engines.items():
    trades_df = pd.DataFrame(engine.trades)
    equity_df = pd.DataFrame(engine.daily_equity)
    
    if len(trades_df) == 0:
        print(f"\n{name}: 无交易")
        continue
    
    total_trades = len(trades_df)
    wins = (trades_df['pnl_pct'] > 0).sum()
    win_rate = wins / total_trades
    avg_win = trades_df[trades_df['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = trades_df[trades_df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if (total_trades - wins) > 0 else 0
    profit_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    final_return = equity_df['cum_return_pct'].iloc[-1]
    max_return = equity_df['cum_return_pct'].max()
    
    # 最大回撤
    cum = equity_df['cum_return_pct'].values
    peak = np.maximum.accumulate(cum)
    drawdown = cum - peak
    max_dd = drawdown.min()
    
    # 夏普
    daily_returns = equity_df['equity'].pct_change().dropna()
    sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(244) if daily_returns.std() > 0 else 0
    
    # 按条件分析
    cond_a = trades_df[trades_df['condition'] == 'A']
    cond_b = trades_df[trades_df['condition'] == 'B']
    
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  总交易: {total_trades}笔")
    print(f"  胜率: {win_rate:.1%}")
    print(f"  平均盈利: +{avg_win:.1f}%")
    print(f"  平均亏损: {avg_loss:.1f}%")
    print(f"  盈亏比: {profit_ratio:.2f}")
    print(f"  最终收益: {final_return:+.1f}%")
    print(f"  最高收益: {max_return:+.1f}%")
    print(f"  最大回撤: {max_dd:.1f}%")
    print(f"  年化夏普: {sharpe:.3f}")
    print(f"  ---")
    print(f"  条件A(非涨停强势+平开): {len(cond_a)}笔, 胜率{(cond_a['pnl_pct']>0).mean():.1%}" if len(cond_a) > 0 else "  条件A: 0笔")
    print(f"  条件B(涨停+低开): {len(cond_b)}笔, 胜率{(cond_b['pnl_pct']>0).mean():.1%}" if len(cond_b) > 0 else "  条件B: 0笔")
    
    # 月度收益
    equity_df['month'] = equity_df['date'] // 100 % 100
    print(f"\n  月度收益:")
    prev = 0
    for m, grp in equity_df.groupby('month'):
        end = grp['cum_return_pct'].iloc[-1]
        delta = end - prev
        print(f"    {m:2d}月: {delta:+8.1f}% (累计 {end:+.1f}%)")
        prev = end

# 保存详细交易记录
for name, engine in engines.items():
    trades_df = pd.DataFrame(engine.trades)
    if len(trades_df) > 0:
        safe_name = name.replace('/', '_')
        trades_df.to_csv(f'{OUTPUT_DIR}/zhihe_backtest_{safe_name}_trades.csv', index=False, encoding='utf-8-sig')
        equity_df = pd.DataFrame(engine.daily_equity)
        equity_df.to_csv(f'{OUTPUT_DIR}/zhihe_backtest_{safe_name}_equity.csv', index=False, encoding='utf-8-sig')

print(f"\n{'='*80}")
print("对比基准: 只核大学生实盘 794.2%")
print("="*80)
print(f"\n交易记录和净值曲线已保存到: {OUTPUT_DIR}/zhihe_backtest_*.csv")
