"""
analyze/sell_strategy_backtest.py — 卖出策略回测与优化

目标：
  在"首板策略"买入信号基础上（涨停日开板回落买入），对比不同卖出策略的盈利效果。
  支持多月回测（2025年2月~12月），获取足够样本进行统计。

时间线：
  Day1 = 涨停日（当天开板回落买入）
  Day2 = 买入后次日（可选卖出日）
  Day3 = 买入后第2日（可选卖出日）

卖出策略集合：
  A. 次日收盘直接卖
  B. Day3收盘直接卖
  C. 3档分批(Day3) — 用户方案
  D. 优化分批(Day3) — 细化版
  E. 移动止盈(Day2)
  F. 自适应(Day2)
  G. 跨日分批(Day2+Day3)

运行：
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 \
        analyze/sell_strategy_backtest.py

    # 可选参数:
    #   --start 20250901  起始日期(默认20251001)
    #   --end   20251231  结束日期(默认20251231)
    #   --buy-gain 7.9    买入涨幅%(默认7.9)
    #   --seal-before 09:50  封板截止时间
    #   --min-seal 30     最短封板分钟
"""
from __future__ import annotations

import os
import sys
import glob
import argparse
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import KLINE_ROOT, OUTPUT_DIR

# ============================================================
# 常量
# ============================================================
KLINE_1D_DIR = os.path.join(KLINE_ROOT, '1d')
KLINE_1M_DIR = os.path.join(KLINE_ROOT, '1m')

LIMIT_PCT = 0.10
SEAL_BEFORE_TIME = '09:50'
MIN_SEAL_MINUTES = 30
BUY_GAIN_PCT = 7.9


# ============================================================
# 数据类
# ============================================================
@dataclass
class TradeRecord:
    code: str
    buy_date: str
    buy_price: float
    pre_close: float
    buy_time: str
    seal_time: str
    seal_duration: int
    open_time: str
    day1_close: float
    day1_close_pct: float
    day1_open_pct: float
    prev_day_pct: Optional[float] = None
    day2_data: Optional[dict] = None
    day3_data: Optional[dict] = None


# ============================================================
# 1m K线缓存 & 加载 (支持多月)
# ============================================================
_1m_cache: Dict[str, Optional[pd.DataFrame]] = {}


def _find_1m_files(code: str) -> List[str]:
    """查找某只股票所有的1m文件"""
    c = str(code)
    exch = 'SH' if c.startswith('6') else 'SZ'
    pattern = os.path.join(KLINE_1M_DIR, f'{code}_{exch}_*.csv')
    return sorted(glob.glob(pattern))


def load_1m_for_date(code: str, date_str: str) -> Optional[pd.DataFrame]:
    """加载某只股票某日的1分钟K线"""
    cache_key = f"{code}_{date_str}"
    if cache_key in _1m_cache:
        return _1m_cache[cache_key]

    # 确定该日期属于哪个月份文件
    year_month_start = date_str[:6] + '01'
    month = int(date_str[4:6])
    year = int(date_str[:4])

    # 计算月末
    if month == 12:
        year_month_end = date_str[:6] + '31'
    elif month in [1, 3, 5, 7, 8, 10]:
        year_month_end = date_str[:6] + '31'
    elif month in [4, 6, 9, 11]:
        year_month_end = date_str[:6] + '30'
    else:  # 2月
        year_month_end = date_str[:6] + '28'

    c = str(code)
    exch = 'SH' if c.startswith('6') else 'SZ'

    # 尝试精确月份文件
    pattern = os.path.join(KLINE_1M_DIR,
                           f'{code}_{exch}_{year_month_start}_{year_month_end}*.csv')
    files = glob.glob(pattern)

    if not files:
        # 尝试其他可能的日期范围
        all_files = _find_1m_files(code)
        for f in all_files:
            bn = os.path.basename(f)
            parts = bn.split('_')
            if len(parts) >= 4:
                f_start = parts[2]
                f_end = parts[3].replace('.csv', '')
                if f_start <= date_str <= f_end:
                    files = [f]
                    break

    if not files:
        _1m_cache[cache_key] = None
        return None

    # 检查是否已经加载过完整月文件
    file_cache_key = files[0]
    if file_cache_key not in _1m_cache:
        try:
            df = pd.read_csv(files[0], encoding='utf-8-sig')
        except Exception:
            _1m_cache[cache_key] = None
            return None

        req = {'date', 'open', 'high', 'low', 'close'}
        if not req.issubset(df.columns):
            _1m_cache[cache_key] = None
            return None

        df['date_str'] = df['date'].astype(str).str[:8]

        if 'time' in df.columns:
            df['time_str'] = (
                pd.to_datetime(df['time'], unit='ms', utc=True)
                .dt.tz_convert('Asia/Shanghai')
                .dt.strftime('%H:%M')
            )
        else:
            df['time_str'] = '09:30'

        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        _1m_cache[file_cache_key] = df

    full_df = _1m_cache[file_cache_key]
    if full_df is None:
        _1m_cache[cache_key] = None
        return None

    day_df = full_df[full_df['date_str'] == date_str].copy().reset_index(drop=True)
    if len(day_df) == 0:
        _1m_cache[cache_key] = None
        return None

    _1m_cache[cache_key] = day_df
    return day_df


def is_main_board(code: str) -> bool:
    c = str(code).strip()
    if c.startswith('688'):
        return False
    return c.startswith('0') or c.startswith('6')


# ============================================================
# 买入信号扫描
# ============================================================
def find_buy_signals(start_date: str, end_date: str,
                     buy_gain_pct: float = BUY_GAIN_PCT,
                     seal_before: str = SEAL_BEFORE_TIME,
                     min_seal: int = MIN_SEAL_MINUTES) -> List[TradeRecord]:
    """扫描日期范围内所有主板股票，找到首板买入信号"""
    all_1d = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    code_files: Dict[str, List[str]] = {}

    for f in all_1d:
        bn = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) < 4:
            continue
        code = parts[0]
        exch = parts[1]
        f_start = parts[2]
        f_end = parts[3].replace('.csv', '')
        if exch == 'BJ':
            continue
        if not is_main_board(code):
            continue
        # 文件日期范围必须覆盖我们的扫描范围
        if f_start <= end_date and f_end >= start_date:
            key = f'{code}_{exch}'
            code_files.setdefault(key, []).append(f)

    total = len(code_files)
    print(f"  主板股票数: {total}")

    trades: List[TradeRecord] = []

    for i, (key, files) in enumerate(sorted(code_files.items())):
        code = key.split('_')[0]

        if (i + 1) % 500 == 0:
            print(f"  进度 {i + 1}/{total}  命中: {len(trades)}")

        # 合并日线
        dfs = []
        for f in sorted(files):
            try:
                df = pd.read_csv(f, encoding='utf-8-sig')
                if not {'date', 'open', 'high', 'low', 'close'}.issubset(df.columns):
                    continue
                df['date_str'] = df['date'].astype(str).str[:8]
                cols = ['date_str', 'open', 'high', 'low', 'close']
                if 'preClose' in df.columns:
                    cols.append('preClose')
                for col in ['open', 'high', 'low', 'close']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                if 'preClose' in df.columns:
                    df['preClose'] = pd.to_numeric(df['preClose'], errors='coerce')
                dfs.append(df[cols])
            except Exception:
                continue

        if not dfs:
            continue

        df_1d = (pd.concat(dfs)
                 .drop_duplicates('date_str')
                 .sort_values('date_str')
                 .reset_index(drop=True))

        # 找扫描范围内的涨停日
        df_range = df_1d[(df_1d['date_str'] >= start_date) &
                         (df_1d['date_str'] <= end_date)]
        if len(df_range) == 0:
            continue

        for abs_idx, drow in df_range.iterrows():
            pc = drow.get('preClose', None)
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                pc = float('nan')
            if pd.isna(pc) or pc <= 0:
                pos = df_1d.index.get_loc(abs_idx)
                if pos > 0:
                    pc = float(df_1d.iloc[pos - 1]['close'])
            if pd.isna(pc) or pc <= 0:
                continue

            lp = round(pc * 1.10, 2)
            c = drow['close']
            if pd.isna(c) or abs(c - lp) / lp > 0.005:
                continue

            rec = _analyze_buy_signal(code, drow['date_str'], df_1d,
                                      buy_gain_pct, seal_before, min_seal)
            if rec:
                trades.append(rec)

    print(f"\n✅ 扫描完成  触发买点: {len(trades)} 笔")
    return trades


def _analyze_buy_signal(code: str, date_str: str, df_1d: pd.DataFrame,
                        buy_gain_pct: float, seal_before: str,
                        min_seal: int) -> Optional[TradeRecord]:
    """分析单个买入信号"""
    idx_list = df_1d.index[df_1d['date_str'] == date_str].tolist()
    if not idx_list:
        return None
    idx_1d = idx_list[0]
    day = df_1d.iloc[idx_1d]

    pre_close = pd.to_numeric(day.get('preClose', None), errors='coerce')
    if pd.isna(pre_close) or pre_close <= 0:
        if idx_1d == 0:
            return None
        pre_close = df_1d.iloc[idx_1d - 1]['close']
    if pd.isna(pre_close) or pre_close <= 0:
        return None

    close_p = pd.to_numeric(day['close'], errors='coerce')
    open_p = pd.to_numeric(day['open'], errors='coerce')
    if pd.isna(close_p) or pd.isna(open_p):
        return None

    limit_price = round(pre_close * (1 + LIMIT_PCT), 2)

    if (close_p - limit_price) / limit_price < -0.005:
        return None

    # 首板判断
    if idx_1d == 0:
        return None
    prev = df_1d.iloc[idx_1d - 1]
    prev_c = pd.to_numeric(prev['close'], errors='coerce')
    prev_pc = pd.to_numeric(prev.get('preClose', None), errors='coerce')
    if pd.isna(prev_pc) or prev_pc <= 0:
        if idx_1d >= 2:
            prev_pc = df_1d.iloc[idx_1d - 2]['close']
    if pd.isna(prev_pc) or prev_pc <= 0:
        return None

    prev_limit = round(prev_pc * (1 + LIMIT_PCT), 2)
    prev_was_limit = (not pd.isna(prev_c)) and (abs(prev_c - prev_limit) / prev_limit <= 0.005)
    if prev_was_limit:
        return None

    prev_close_pct = (prev_c - prev_pc) / prev_pc * 100 if not pd.isna(prev_c) else None

    # 加载 1m K线
    day_1m = load_1m_for_date(code, date_str)
    if day_1m is None or len(day_1m) == 0:
        return None

    # 封板检测
    limit_thresh = limit_price * (1 - 0.001)
    sealed = day_1m['close'] >= limit_thresh

    first_seal_idx = sealed.idxmax() if sealed.any() else None
    if first_seal_idx is None:
        return None
    if not sealed[first_seal_idx]:
        return None
    first_seal_time = day_1m.at[first_seal_idx, 'time_str']

    if first_seal_time > seal_before:
        return None

    # 连续封板
    seal_end_idx = first_seal_idx
    for i in range(first_seal_idx, len(day_1m)):
        if sealed.iloc[i] if i != first_seal_idx else sealed[first_seal_idx]:
            seal_end_idx = i
        else:
            break

    # 修正循环逻辑
    seal_end_idx = first_seal_idx
    for i in range(first_seal_idx + 1, len(day_1m)):
        if sealed[i]:
            seal_end_idx = i
        else:
            break

    seal_duration = seal_end_idx - first_seal_idx + 1
    if seal_duration < min_seal:
        return None

    # 开板
    open_idx = None
    open_time = None
    open_start = seal_end_idx + 1
    if open_start >= len(day_1m):
        return None

    for i in range(open_start, len(day_1m)):
        if not sealed[i]:
            open_idx = i
            open_time = day_1m.at[i, 'time_str']
            break

    if open_idx is None:
        return None

    # 回落到 buy_gain_pct
    buy_price = round(pre_close * (1 + buy_gain_pct / 100), 3)
    buy_time = None

    for i in range(open_idx, len(day_1m)):
        if day_1m.iloc[i]['low'] <= buy_price:
            buy_time = day_1m.iloc[i]['time_str']
            break

    if buy_time is None:
        return None

    close_gain = (close_p - pre_close) / pre_close * 100
    open_gain = (open_p - pre_close) / pre_close * 100

    # Day2 和 Day3 数据
    day2_data = _get_future_day_data(code, idx_1d + 1, df_1d, buy_price)
    day3_data = _get_future_day_data(code, idx_1d + 2, df_1d, buy_price)

    return TradeRecord(
        code=code,
        buy_date=date_str,
        buy_price=buy_price,
        pre_close=round(pre_close, 3),
        buy_time=buy_time,
        seal_time=first_seal_time,
        seal_duration=seal_duration,
        open_time=open_time,
        day1_close=close_p,
        day1_close_pct=round(close_gain, 2),
        day1_open_pct=round(open_gain, 2),
        prev_day_pct=round(prev_close_pct, 2) if prev_close_pct is not None else None,
        day2_data=day2_data,
        day3_data=day3_data,
    )


def _get_future_day_data(code: str, future_idx: int,
                         df_1d: pd.DataFrame,
                         buy_price: float) -> Optional[dict]:
    """获取未来某日的日线 + 1m 数据"""
    if future_idx >= len(df_1d):
        return None

    day = df_1d.iloc[future_idx]
    date_str = day['date_str']
    open_p = pd.to_numeric(day['open'], errors='coerce')
    high_p = pd.to_numeric(day['high'], errors='coerce')
    low_p = pd.to_numeric(day['low'], errors='coerce')
    close_p = pd.to_numeric(day['close'], errors='coerce')
    pre_close = pd.to_numeric(day.get('preClose', None), errors='coerce')

    if pd.isna(pre_close) or pre_close <= 0:
        if future_idx > 0:
            pre_close = pd.to_numeric(df_1d.iloc[future_idx - 1]['close'], errors='coerce')
    if pd.isna(pre_close) or pre_close <= 0:
        return None

    open_pct = (open_p - pre_close) / pre_close * 100 if not pd.isna(open_p) else None
    high_pct = (high_p - pre_close) / pre_close * 100 if not pd.isna(high_p) else None
    low_pct = (low_p - pre_close) / pre_close * 100 if not pd.isna(low_p) else None
    close_pct = (close_p - pre_close) / pre_close * 100 if not pd.isna(close_p) else None

    profit_close = (close_p - buy_price) / buy_price * 100 if not pd.isna(close_p) else None
    profit_high = (high_p - buy_price) / buy_price * 100 if not pd.isna(high_p) else None
    profit_low = (low_p - buy_price) / buy_price * 100 if not pd.isna(low_p) else None
    profit_open = (open_p - buy_price) / buy_price * 100 if not pd.isna(open_p) else None

    minute_bars = load_1m_for_date(code, date_str)

    return {
        'date': date_str,
        'open': open_p,
        'high': high_p,
        'low': low_p,
        'close': close_p,
        'pre_close': pre_close,
        'open_pct': round(open_pct, 2) if open_pct is not None else None,
        'high_pct': round(high_pct, 2) if high_pct is not None else None,
        'low_pct': round(low_pct, 2) if low_pct is not None else None,
        'close_pct': round(close_pct, 2) if close_pct is not None else None,
        'profit_open': round(profit_open, 2) if profit_open is not None else None,
        'profit_close': round(profit_close, 2) if profit_close is not None else None,
        'profit_high': round(profit_high, 2) if profit_high is not None else None,
        'profit_low': round(profit_low, 2) if profit_low is not None else None,
        'minute_bars': minute_bars,
    }


# ============================================================
# 卖出策略工具
# ============================================================
def _simulate_intraday_sell(minute_bars: Optional[pd.DataFrame],
                            buy_price: float,
                            targets: List[Tuple[float, float]],
                            stop_loss_pct: float = -5.0,
                            sell_at_close: bool = True) -> Tuple[float, str]:
    """
    日内分批卖出模拟。

    targets: [(涨幅%, 卖出仓位比例), ...]  涨幅相对买入价
    """
    if minute_bars is None or len(minute_bars) == 0:
        return 0.0, '无分钟数据'

    remaining = 1.0
    total_profit = 0.0
    details = []

    target_idx = 0
    stop_price = buy_price * (1 + stop_loss_pct / 100)

    for _, row in minute_bars.iterrows():
        if remaining <= 0.001:
            break

        bar_time = row['time_str']
        bar_high = row['high']
        bar_low = row['low']

        # 止损优先
        if bar_low <= stop_price and remaining > 0:
            total_profit += stop_loss_pct * remaining
            details.append(f'止损@{bar_time}({remaining:.0%})')
            remaining = 0
            break

        # 目标止盈
        while target_idx < len(targets) and remaining > 0.001:
            target_pct, sell_ratio = targets[target_idx]
            target_price = buy_price * (1 + target_pct / 100)

            if bar_high >= target_price:
                actual_sell = min(sell_ratio, remaining)
                total_profit += target_pct * actual_sell
                remaining -= actual_sell
                details.append(f'+{target_pct}%@{bar_time}({actual_sell:.0%})')
                target_idx += 1
            else:
                break

    # 收盘卖出
    if remaining > 0.001 and sell_at_close:
        last_close = minute_bars.iloc[-1]['close']
        profit = (last_close - buy_price) / buy_price * 100
        total_profit += profit * remaining
        details.append(f'收盘{profit:+.1f}%({remaining:.0%})')

    return round(total_profit, 3), ' | '.join(details) if details else '未执行'


def _trailing_stop_sell(minute_bars: Optional[pd.DataFrame],
                        buy_price: float,
                        trail_pct: float = 2.5,
                        stop_loss_pct: float = -5.0,
                        sell_at_close: bool = True) -> Tuple[float, str]:
    """移动止盈"""
    if minute_bars is None or len(minute_bars) == 0:
        return 0.0, '无分钟数据'

    peak = buy_price
    stop_price = buy_price * (1 + stop_loss_pct / 100)

    for _, row in minute_bars.iterrows():
        bar_time = row['time_str']
        bar_high = row['high']
        bar_low = row['low']

        if bar_high > peak:
            peak = bar_high

        if bar_low <= stop_price:
            return round(stop_loss_pct, 3), f'止损@{bar_time} {stop_loss_pct:+.1f}%'

        if peak > buy_price * 1.01:  # 至少涨1%后启动移动止盈
            trail_price = peak * (1 - trail_pct / 100)
            if bar_low <= trail_price:
                profit = (trail_price - buy_price) / buy_price * 100
                peak_g = (peak - buy_price) / buy_price * 100
                return round(profit, 3), f'移动止盈@{bar_time} 峰{peak_g:+.1f}%→{profit:+.1f}%'

    if sell_at_close:
        last_close = minute_bars.iloc[-1]['close']
        profit = (last_close - buy_price) / buy_price * 100
        return round(profit, 3), f'收盘卖 {profit:+.1f}%'

    return 0.0, '未触发'


# ============================================================
# 策略A ~ G
# ============================================================
def strategy_A_next_close(trade: TradeRecord) -> Tuple[float, str]:
    if trade.day2_data is None:
        return 0.0, '无Day2'
    p = trade.day2_data.get('profit_close')
    return (p, f'Day2收盘 {p:+.2f}%') if p is not None else (0.0, '无数据')


def strategy_B_day3_close(trade: TradeRecord) -> Tuple[float, str]:
    if trade.day3_data is None:
        return 0.0, '无Day3'
    p = trade.day3_data.get('profit_close')
    return (p, f'Day3收盘 {p:+.2f}%') if p is not None else (0.0, '无数据')


def strategy_C_tiered_v1(trade: TradeRecord, sell_day: str = 'day3') -> Tuple[float, str]:
    """
    用户3档策略:
      低开(<-3%): +3%止盈, -5%止损
      常规(-3%~+3%): 50%@+4%, 50%@+7%
      高开(>+3%): 持有到14:50
    """
    day_data = trade.day3_data if sell_day == 'day3' else trade.day2_data
    if day_data is None:
        return 0.0, f'无{sell_day}'

    open_pct = day_data.get('open_pct', 0)
    if open_pct is None:
        return 0.0, '无开盘'

    mb = day_data.get('minute_bars')
    bp = trade.buy_price

    if open_pct < -3.0:
        targets = [(3.0, 1.0)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -5.0, True)
        return profit, f'[低开{open_pct:+.1f}%] {detail}'
    elif open_pct > 3.0:
        if mb is not None and len(mb) > 0:
            sell_bars = mb[mb['time_str'] >= '14:50']
            sp = sell_bars.iloc[0]['close'] if len(sell_bars) > 0 else mb.iloc[-1]['close']
            profit = (sp - bp) / bp * 100
            return round(profit, 3), f'[高开{open_pct:+.1f}%] 14:50卖 {profit:+.2f}%'
        p = day_data.get('profit_close', 0) or 0
        return p, f'[高开{open_pct:+.1f}%] 收盘 {p:+.2f}%'
    else:
        targets = [(4.0, 0.5), (7.0, 0.5)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -5.0, True)
        return profit, f'[常规{open_pct:+.1f}%] {detail}'


def strategy_D_tiered_v2(trade: TradeRecord, sell_day: str = 'day3') -> Tuple[float, str]:
    """
    优化版:
      深低开(<-3%): +2%(50%)+4%(50%), -4%止损
      小低开(-3%~0%): +3%(30%)+5%(40%)+8%(30%), -5%止损
      小高开(0%~+3%): +4%(30%)+6%(40%)+9%(30%), -4%止损
      大高开(>+3%): 移动止盈(回撤2.5%)
    """
    day_data = trade.day3_data if sell_day == 'day3' else trade.day2_data
    if day_data is None:
        return 0.0, f'无{sell_day}'

    open_pct = day_data.get('open_pct', 0)
    if open_pct is None:
        return 0.0, '无开盘'

    mb = day_data.get('minute_bars')
    bp = trade.buy_price

    if open_pct < -3.0:
        targets = [(2.0, 0.5), (4.0, 0.5)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -4.0, True)
        return profit, f'[深低开{open_pct:+.1f}%] {detail}'
    elif open_pct < 0:
        targets = [(3.0, 0.3), (5.0, 0.4), (8.0, 0.3)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -5.0, True)
        return profit, f'[小低开{open_pct:+.1f}%] {detail}'
    elif open_pct <= 3.0:
        targets = [(4.0, 0.3), (6.0, 0.4), (9.0, 0.3)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -4.0, True)
        return profit, f'[小高开{open_pct:+.1f}%] {detail}'
    else:
        profit, detail = _trailing_stop_sell(mb, bp, 2.5, -5.0, True)
        return profit, f'[大高开{open_pct:+.1f}%] {detail}'


def strategy_E_trailing_day2(trade: TradeRecord) -> Tuple[float, str]:
    """Day2 移动止盈: 峰值回撤3%卖, -5%止损"""
    if trade.day2_data is None:
        return 0.0, '无Day2'
    mb = trade.day2_data.get('minute_bars')
    profit, detail = _trailing_stop_sell(mb, trade.buy_price, 3.0, -5.0, True)
    return profit, f'[Day2移动] {detail}'


def strategy_F_adaptive_day2(trade: TradeRecord) -> Tuple[float, str]:
    """
    Day2 开盘自适应:
      低开(<-2%): +2%止盈, -3%止损
      平开(-2%~+2%): 50%@+3% 50%@+6%, -4%止损
      高开(>+2%): 移动止盈(回撤2%)
    """
    if trade.day2_data is None:
        return 0.0, '无Day2'

    open_pct = trade.day2_data.get('open_pct', 0)
    if open_pct is None:
        return 0.0, '无开盘'

    mb = trade.day2_data.get('minute_bars')
    bp = trade.buy_price

    if open_pct < -2.0:
        targets = [(2.0, 1.0)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -3.0, True)
        return profit, f'[Day2低开{open_pct:+.1f}%] {detail}'
    elif open_pct <= 2.0:
        targets = [(3.0, 0.5), (6.0, 0.5)]
        profit, detail = _simulate_intraday_sell(mb, bp, targets, -4.0, True)
        return profit, f'[Day2平开{open_pct:+.1f}%] {detail}'
    else:
        profit, detail = _trailing_stop_sell(mb, bp, 2.0, -3.0, True)
        return profit, f'[Day2高开{open_pct:+.1f}%] {detail}'


def strategy_G_two_day_split(trade: TradeRecord) -> Tuple[float, str]:
    """
    跨日分批:
      Day2: +3%卖50%，否则不动
      Day3: 剩余按3档策略
    """
    if trade.day2_data is None:
        return 0.0, '无Day2'

    bp = trade.buy_price
    mb_d2 = trade.day2_data.get('minute_bars')

    day2_sold = 0.0
    day2_profit = 0.0
    details = []

    # Day2 尝试+3%卖50%
    if mb_d2 is not None and len(mb_d2) > 0:
        t_price = bp * 1.03
        for _, row in mb_d2.iterrows():
            if row['high'] >= t_price:
                day2_sold = 0.5
                day2_profit = 3.0 * 0.5
                details.append(f'Day2+3%@{row["time_str"]}(50%)')
                break

    remaining = 1.0 - day2_sold

    if remaining > 0.001 and trade.day3_data is not None:
        d3_open = trade.day3_data.get('open_pct', 0) or 0
        mb_d3 = trade.day3_data.get('minute_bars')

        if d3_open < -3.0:
            targets = [(3.0, remaining)]
        elif d3_open > 3.0:
            if mb_d3 is not None and len(mb_d3) > 0:
                sb = mb_d3[mb_d3['time_str'] >= '14:50']
                sp = sb.iloc[0]['close'] if len(sb) > 0 else mb_d3.iloc[-1]['close']
                d3p = (sp - bp) / bp * 100
                day2_profit += d3p * remaining
                details.append(f'Day3高开持有→{d3p:+.1f}%({remaining:.0%})')
                return round(day2_profit, 3), ' | '.join(details)
            targets = []
        else:
            targets = [(4.0, remaining * 0.5), (7.0, remaining * 0.5)]

        if targets:
            d3p, d3d = _simulate_intraday_sell(mb_d3, bp, targets, -5.0, True)
            day2_profit += d3p
            details.append(f'Day3[{d3_open:+.1f}%] {d3d}')
    elif remaining > 0.001:
        if mb_d2 is not None and len(mb_d2) > 0:
            lc = mb_d2.iloc[-1]['close']
            d2p = (lc - bp) / bp * 100
            day2_profit += d2p * remaining
            details.append(f'Day2收盘{d2p:+.1f}%({remaining:.0%})')

    return round(day2_profit, 3), ' | '.join(details) if details else '未执行'


# ---- 策略 H: 激进移动止盈(Day2) ----
def strategy_H_aggressive_trailing(trade: TradeRecord) -> Tuple[float, str]:
    """Day2 激进移动止盈: 峰值回撤2%即卖, -3%止损"""
    if trade.day2_data is None:
        return 0.0, '无Day2'
    mb = trade.day2_data.get('minute_bars')
    profit, detail = _trailing_stop_sell(mb, trade.buy_price, 2.0, -3.0, True)
    return profit, f'[Day2激进] {detail}'


# ---- 策略 I: 3档分批Day2, 更宽止盈 ----
def strategy_I_wide_tiered_day2(trade: TradeRecord) -> Tuple[float, str]:
    """Day2 宽幅3档: 33%@+2%, 33%@+4%, 34%@+7%, -5%止损"""
    if trade.day2_data is None:
        return 0.0, '无Day2'
    mb = trade.day2_data.get('minute_bars')
    targets = [(2.0, 0.33), (4.0, 0.33), (7.0, 0.34)]
    profit, detail = _simulate_intraday_sell(mb, trade.buy_price, targets, -5.0, True)
    return profit, f'[Day2宽幅3档] {detail}'


# ============================================================
# 策略 J: 混合最优策略 (基于回测数据优化)
# ============================================================
def strategy_J_hybrid_optimal(trade: TradeRecord,
                              # 开盘分界线
                              high_open_thresh: float = 2.0,
                              low_open_thresh: float = -2.0,
                              # 高开: 移动止盈参数
                              high_trail_pct: float = 2.0,
                              high_stop_loss: float = -2.0,
                              # 平开: 分批参数
                              mid_t1_pct: float = 3.0,
                              mid_t1_ratio: float = 0.5,
                              mid_t2_pct: float = 6.0,
                              mid_t2_ratio: float = 0.5,
                              mid_stop_loss: float = -3.0,
                              # 低开: 快速止损/止盈
                              low_target_pct: float = 2.0,
                              low_stop_loss: float = -2.0,
                              ) -> Tuple[float, str]:
    """
    混合最优策略(Day2执行):
      基于118笔回测数据的最优行为:

      高开(>high_open_thresh%): 移动止盈
        - 回测100%胜率, 均盈+6.72%
        - 用移动止盈锁定利润, 从峰值回撤high_trail_pct%卖

      平开(low_open_thresh ~ high_open_thresh): 分批止盈
        - 回测86%胜率区间
        - 分2批卖出: mid_t1_pct% / mid_t2_pct%

      低开(<low_open_thresh%): 快速脱手
        - 回测仅23%胜率, 平均亏-1.66%
        - 极窄止盈+极紧止损, 快速脱手减少损失
    """
    if trade.day2_data is None:
        return 0.0, '无Day2'

    open_pct = trade.day2_data.get('open_pct', 0)
    if open_pct is None:
        return 0.0, '无开盘'

    mb = trade.day2_data.get('minute_bars')
    bp = trade.buy_price

    if open_pct > high_open_thresh:
        # ===== 高开: 移动止盈, 博取最大收益 =====
        profit, detail = _trailing_stop_sell(
            mb, bp, trail_pct=high_trail_pct,
            stop_loss_pct=high_stop_loss, sell_at_close=True
        )
        return profit, f'[J高开{open_pct:+.1f}%|移动止盈] {detail}'

    elif open_pct >= low_open_thresh:
        # ===== 平开: 分批止盈 =====
        targets = [(mid_t1_pct, mid_t1_ratio), (mid_t2_pct, mid_t2_ratio)]
        profit, detail = _simulate_intraday_sell(
            mb, bp, targets, stop_loss_pct=mid_stop_loss, sell_at_close=True
        )
        return profit, f'[J平开{open_pct:+.1f}%|分批] {detail}'

    else:
        # ===== 低开: 快速脱手 =====
        targets = [(low_target_pct, 1.0)]
        profit, detail = _simulate_intraday_sell(
            mb, bp, targets, stop_loss_pct=low_stop_loss, sell_at_close=True
        )
        return profit, f'[J低开{open_pct:+.1f}%|快脱] {detail}'


# ============================================================
# 参数网格搜索: 搜索最优的卖出参数组合
# ============================================================
def grid_search_sell_params(trades: List[TradeRecord]) -> pd.DataFrame:
    """
    对混合最优策略J的参数进行网格搜索。

    搜索空间:
      - 高开分界线: [1.0, 1.5, 2.0, 2.5, 3.0]
      - 低开分界线: [-1.0, -1.5, -2.0, -2.5, -3.0]
      - 高开移动止盈回撤%: [1.5, 2.0, 2.5, 3.0]
      - 平开目标1%: [2.0, 3.0, 4.0]
      - 平开目标2%: [5.0, 6.0, 7.0, 8.0]
      - 低开止盈%: [1.0, 2.0, 3.0]
      - 低开止损%: [-1.5, -2.0, -3.0]
      - 平开止损%: [-3.0, -4.0, -5.0]
    """
    import itertools

    param_grid = {
        'high_open_thresh': [1.0, 1.5, 2.0, 2.5, 3.0],
        'low_open_thresh': [-1.0, -1.5, -2.0, -2.5, -3.0],
        'high_trail_pct': [1.5, 2.0, 2.5, 3.0],
        'high_stop_loss': [-2.0, -3.0],
        'mid_t1_pct': [2.0, 3.0, 4.0],
        'mid_t2_pct': [5.0, 6.0, 7.0, 8.0],
        'mid_stop_loss': [-3.0, -4.0, -5.0],
        'low_target_pct': [1.0, 2.0, 3.0],
        'low_stop_loss': [-1.5, -2.0, -3.0],
    }

    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    total = len(combos)

    print(f"\n🔍 参数网格搜索: {total} 组参数")
    print(f"   trades 样本: {len(trades)} 笔")

    results = []

    for idx, combo in enumerate(combos):
        params = dict(zip(keys, combo))

        # 确保 mid_t1 < mid_t2
        if params['mid_t1_pct'] >= params['mid_t2_pct']:
            continue

        if (idx + 1) % 5000 == 0:
            print(f"  进度 {idx + 1}/{total}...")

        profits = []
        for trade in trades:
            try:
                p, _ = strategy_J_hybrid_optimal(
                    trade,
                    high_open_thresh=params['high_open_thresh'],
                    low_open_thresh=params['low_open_thresh'],
                    high_trail_pct=params['high_trail_pct'],
                    high_stop_loss=params['high_stop_loss'],
                    mid_t1_pct=params['mid_t1_pct'],
                    mid_t1_ratio=0.5,
                    mid_t2_pct=params['mid_t2_pct'],
                    mid_t2_ratio=0.5,
                    mid_stop_loss=params['mid_stop_loss'],
                    low_target_pct=params['low_target_pct'],
                    low_stop_loss=params['low_stop_loss'],
                )
                profits.append(p)
            except Exception:
                profits.append(0.0)

        pnl = pd.Series(profits)
        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = losses.mean() if len(losses) > 0 else 0
        std = pnl.std() if len(pnl) > 1 else 1

        row = {
            **params,
            '笔数': len(pnl),
            '胜率(%)': round((pnl > 0).mean() * 100, 1),
            '均盈亏(%)': round(pnl.mean(), 3),
            '中位(%)': round(pnl.median(), 3),
            '总收益(%)': round(pnl.sum(), 2),
            '最大盈(%)': round(pnl.max(), 2),
            '最大亏(%)': round(pnl.min(), 2),
            '盈亏比': round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else None,
            '夏普': round(pnl.mean() / std, 3) if std > 1e-9 else 0,
        }
        results.append(row)

    df = pd.DataFrame(results)
    df = df.sort_values('总收益(%)', ascending=False).reset_index(drop=True)
    df.index += 1
    return df


# ============================================================
# 策略注册
# ============================================================
SELL_STRATEGIES = {
    'A_次日收盘': strategy_A_next_close,
    'B_Day3收盘': strategy_B_day3_close,
    'C_3档分批(Day3)': lambda t: strategy_C_tiered_v1(t, 'day3'),
    'C2_3档分批(Day2)': lambda t: strategy_C_tiered_v1(t, 'day2'),
    'D_优化分批(Day3)': lambda t: strategy_D_tiered_v2(t, 'day3'),
    'D2_优化分批(Day2)': lambda t: strategy_D_tiered_v2(t, 'day2'),
    'E_移动止盈(Day2)': strategy_E_trailing_day2,
    'F_自适应(Day2)': strategy_F_adaptive_day2,
    'G_跨日分批': strategy_G_two_day_split,
    'H_激进止盈(Day2)': strategy_H_aggressive_trailing,
    'I_宽幅3档(Day2)': strategy_I_wide_tiered_day2,
    'J_混合最优(Day2)': lambda t: strategy_J_hybrid_optimal(t),
}


# ============================================================
# 主回测
# ============================================================
def run_full_backtest(start_date: str, end_date: str,
                     buy_gain_pct: float = BUY_GAIN_PCT,
                     seal_before: str = SEAL_BEFORE_TIME,
                     min_seal: int = MIN_SEAL_MINUTES,
                     do_grid_search: bool = False) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    print("=" * 70)
    print("🎯 卖出策略对比回测")
    print(f"   买入: 首板(主板) | {seal_before}前封板≥{min_seal}分钟 | 开板回落至+{buy_gain_pct}%")
    print(f"   时间: {start_date} ~ {end_date}")
    print("=" * 70)

    trades = find_buy_signals(start_date, end_date, buy_gain_pct, seal_before, min_seal)
    if not trades:
        print("  ⚠️ 无买入信号")
        return pd.DataFrame(), None

    rows = []
    for trade in trades:
        row = {
            '股票代码': trade.code,
            '涨停日': trade.buy_date,
            '买入价': trade.buy_price,
            'preClose': trade.pre_close,
            '买入时间': trade.buy_time,
            '封板时间': trade.seal_time,
            '封板持续(分)': trade.seal_duration,
            '开板时间': trade.open_time,
            '前日涨跌(%)': trade.prev_day_pct,
            'Day1收盘涨(%)': trade.day1_close_pct,
        }

        if trade.day2_data:
            row['Day2开盘涨(%)'] = trade.day2_data.get('open_pct')
            row['Day2最高涨(%)'] = trade.day2_data.get('high_pct')
            row['Day2最低涨(%)'] = trade.day2_data.get('low_pct')
            row['Day2收盘涨(%)'] = trade.day2_data.get('close_pct')
        if trade.day3_data:
            row['Day3开盘涨(%)'] = trade.day3_data.get('open_pct')
            row['Day3最高涨(%)'] = trade.day3_data.get('high_pct')
            row['Day3最低涨(%)'] = trade.day3_data.get('low_pct')
            row['Day3收盘涨(%)'] = trade.day3_data.get('close_pct')

        for name, func in SELL_STRATEGIES.items():
            try:
                profit, detail = func(trade)
                row[f'盈亏_{name}(%)'] = round(profit, 3) if profit is not None else None
                row[f'详情_{name}'] = detail
            except Exception as e:
                row[f'盈亏_{name}(%)'] = None
                row[f'详情_{name}'] = f'错误: {e}'

        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.sort_values(['涨停日', '封板时间']).reset_index(drop=True)

    # 可选：参数网格搜索
    grid_df = None
    if do_grid_search:
        grid_df = grid_search_sell_params(trades)

        # 用最优参数跑一遍，加入df
        if len(grid_df) > 0:
            best_params = grid_df.iloc[0]
            print(f"\n🏆 最优参数组合:")
            param_keys = ['high_open_thresh', 'low_open_thresh', 'high_trail_pct',
                          'high_stop_loss', 'mid_t1_pct', 'mid_t2_pct',
                          'mid_stop_loss', 'low_target_pct', 'low_stop_loss']
            for k in param_keys:
                print(f"   {k}: {best_params[k]}")
            print(f"   总收益: {best_params['总收益(%)']:+.2f}%  胜率: {best_params['胜率(%)']:.1f}%")

            # 把最优参数结果加入df
            best_profits = []
            best_details = []
            for trade in trades:
                try:
                    p, d = strategy_J_hybrid_optimal(
                        trade,
                        high_open_thresh=best_params['high_open_thresh'],
                        low_open_thresh=best_params['low_open_thresh'],
                        high_trail_pct=best_params['high_trail_pct'],
                        high_stop_loss=best_params['high_stop_loss'],
                        mid_t1_pct=best_params['mid_t1_pct'],
                        mid_t1_ratio=0.5,
                        mid_t2_pct=best_params['mid_t2_pct'],
                        mid_t2_ratio=0.5,
                        mid_stop_loss=best_params['mid_stop_loss'],
                        low_target_pct=best_params['low_target_pct'],
                        low_stop_loss=best_params['low_stop_loss'],
                    )
                    best_profits.append(round(p, 3))
                    best_details.append(d)
                except Exception as e:
                    best_profits.append(None)
                    best_details.append(f'err: {e}')

            df['盈亏_J★最优参数(%)'] = best_profits
            df['详情_J★最优参数'] = best_details

    return df, grid_df


def print_comparison(df: pd.DataFrame):
    print("\n" + "=" * 100)
    print("📊 卖出策略对比统计")
    print("=" * 100)

    stats = []
    for name in SELL_STRATEGIES.keys():
        col = f'盈亏_{name}(%)'
        if col not in df.columns:
            continue
        pnl = df[col].dropna()
        if len(pnl) == 0:
            continue

        wins = pnl[pnl > 0]
        losses = pnl[pnl <= 0]
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = losses.mean() if len(losses) > 0 else 0

        stats.append({
            '策略': name,
            '笔数': len(pnl),
            '胜率(%)': round((pnl > 0).mean() * 100, 1),
            '均盈亏(%)': round(pnl.mean(), 3),
            '中位(%)': round(pnl.median(), 3),
            '最大盈(%)': round(pnl.max(), 2),
            '最大亏(%)': round(pnl.min(), 2),
            '总收益(%)': round(pnl.sum(), 2),
            '盈亏比': round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else None,
            '夏普': round(pnl.mean() / pnl.std(), 3) if pnl.std() > 0 else 0,
        })

    stats_df = pd.DataFrame(stats)
    stats_df = stats_df.sort_values('总收益(%)', ascending=False).reset_index(drop=True)
    stats_df.index += 1

    pd.set_option('display.width', 300)
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.float_format', '{:.3f}'.format)
    print(stats_df.to_string())

    print("\n" + "-" * 70)
    best = stats_df.iloc[0]
    print(f"🏆 最优策略: {best['策略']}")
    print(f"   总收益: {best['总收益(%)']:+.2f}%  |  胜率: {best['胜率(%)']:.1f}%  |  "
          f"均盈亏: {best['均盈亏(%)']:+.3f}%  |  夏普: {best['夏普']:.3f}")

    # 细分分析
    for strat_name, day_col, label in [
        ('C_3档分批(Day3)', 'Day3开盘涨(%)', 'Day3'),
        ('F_自适应(Day2)', 'Day2开盘涨(%)', 'Day2'),
        ('D_优化分批(Day3)', 'Day3开盘涨(%)', 'Day3'),
    ]:
        pnl_col = f'盈亏_{strat_name}(%)'
        if day_col not in df.columns or pnl_col not in df.columns:
            continue
        valid = df[df[day_col].notna() & df[pnl_col].notna()].copy()
        if len(valid) == 0:
            continue

        print(f"\n📈 {strat_name} 按{label}开盘分类:")
        if 'Day3' in label:
            bins = [(-999, -3), (-3, 0), (0, 3), (3, 999)]
            labels_list = ['低开(<-3%)', '小低开(-3%~0%)', '小高开(0%~+3%)', '高开(>+3%)']
        else:
            bins = [(-999, -2), (-2, 0), (0, 2), (2, 999)]
            labels_list = ['低开(<-2%)', '平低(-2%~0%)', '平高(0%~+2%)', '高开(>+2%)']

        for (lo, hi), lab in zip(bins, labels_list):
            subset = valid[(valid[day_col] >= lo) & (valid[day_col] < hi)]
            if len(subset) == 0:
                print(f"  {lab}: 无样本")
                continue
            pnl = subset[pnl_col]
            print(f"  {lab}: {len(subset)}笔  "
                  f"胜率={((pnl > 0).mean() * 100):.0f}%  "
                  f"均盈={pnl.mean():+.2f}%  "
                  f"总收={pnl.sum():+.2f}%")

    # 按月份分布
    print("\n📅 按月份分布:")
    if '涨停日' in df.columns:
        df_t = df.copy()
        df_t['月份'] = df_t['涨停日'].str[:6]
        for name in list(SELL_STRATEGIES.keys())[:5]:  # 显示前5个策略
            col = f'盈亏_{name}(%)'
            if col not in df_t.columns:
                continue
            monthly = df_t.groupby('月份')[col].agg(['count', 'mean', 'sum'])
            print(f"\n  {name}:")
            for m, row in monthly.iterrows():
                print(f"    {m}: {int(row['count'])}笔  均{row['mean']:+.2f}%  总{row['sum']:+.2f}%")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='卖出策略对比回测')
    parser.add_argument('--start', default='20250201',
                        help='起始日期 (默认 20250201)')
    parser.add_argument('--end', default='20251231',
                        help='结束日期 (默认 20251231)')
    parser.add_argument('--buy-gain', type=float, default=BUY_GAIN_PCT,
                        help=f'买入点涨幅%% (默认 {BUY_GAIN_PCT})')
    parser.add_argument('--seal-before', default=SEAL_BEFORE_TIME,
                        help=f'封板截止时间 (默认 {SEAL_BEFORE_TIME})')
    parser.add_argument('--min-seal', type=int, default=MIN_SEAL_MINUTES,
                        help=f'最短封板分钟 (默认 {MIN_SEAL_MINUTES})')
    parser.add_argument('--top', type=int, default=80,
                        help='显示前N笔交易 (默认 80)')
    parser.add_argument('--grid-search', action='store_true',
                        help='启用参数网格搜索')
    args = parser.parse_args()

    df, grid_df = run_full_backtest(args.start, args.end, args.buy_gain,
                                    args.seal_before, args.min_seal,
                                    do_grid_search=args.grid_search)
    if len(df) == 0:
        return

    # 打印明细
    print("\n" + "=" * 70)
    print("📋 交易明细")
    print("=" * 70)
    pd.set_option('display.width', 350)
    pd.set_option('display.max_columns', 30)

    core_cols = ['股票代码', '涨停日', '买入价', '买入时间',
                 '封板时间', '封板持续(分)', 'Day1收盘涨(%)',
                 'Day2开盘涨(%)', 'Day2收盘涨(%)',
                 'Day3开盘涨(%)', 'Day3收盘涨(%)']
    profit_cols = [c for c in df.columns if c.startswith('盈亏_')]
    show_cols = [c for c in core_cols + profit_cols if c in df.columns]
    print(df[show_cols].head(args.top).to_string(index=False))

    # 对比
    print_comparison(df)

    # 保存
    out_path = os.path.join(OUTPUT_DIR, 'sell_strategy_comparison.xlsx')
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        # 排行榜 (动态获取所有盈亏列)
        all_strategy_names = [c.replace('盈亏_', '').replace('(%)', '')
                              for c in df.columns if c.startswith('盈亏_')]
        stats = []
        for name in all_strategy_names:
            col = f'盈亏_{name}(%)'
            if col not in df.columns:
                continue
            pnl = df[col].dropna()
            if len(pnl) == 0:
                continue
            wins = pnl[pnl > 0]
            losses = pnl[pnl <= 0]
            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = losses.mean() if len(losses) > 0 else 0
            stats.append({
                '策略': name,
                '笔数': len(pnl),
                '胜率(%)': round((pnl > 0).mean() * 100, 1),
                '均盈亏(%)': round(pnl.mean(), 3),
                '中位(%)': round(pnl.median(), 3),
                '最大盈(%)': round(pnl.max(), 2),
                '最大亏(%)': round(pnl.min(), 2),
                '总收益(%)': round(pnl.sum(), 2),
                '盈亏比': round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else None,
                '夏普': round(pnl.mean() / pnl.std(), 3) if pnl.std() > 0 else 0,
            })

        stats_df = pd.DataFrame(stats).sort_values('总收益(%)', ascending=False)
        stats_df.to_excel(writer, sheet_name='策略排行', index=False)

        # 交易明细
        detail_cols = [c for c in core_cols + profit_cols if c in df.columns]
        df[detail_cols].to_excel(writer, sheet_name='交易明细', index=False)

        # 完整数据
        df.to_excel(writer, sheet_name='完整数据', index=False)

        # 网格搜索结果
        if grid_df is not None and len(grid_df) > 0:
            grid_df.head(100).to_excel(writer, sheet_name='参数搜索Top100', index=False)

    print(f"\n💾 已保存: {out_path}")


if __name__ == '__main__':
    main()
