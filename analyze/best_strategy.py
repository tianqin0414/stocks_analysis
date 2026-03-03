"""
analyze/best_strategy.py — 最强策略：首板买入 + 策略J混合最优卖出

策略逻辑：
  买入端（首板策略）：
    1. 主板股票（0xx/6xx，排除科创板688/北交所）
    2. 当日收盘涨停 & 前一日未涨停（首板）
    3. 9:50前封板，连续封板≥30分钟
    4. 开板后价格回落至 +7.9% → 买入

  卖出端（策略J混合最优，Day2执行）：
    高开(>+2%): 移动止盈，从峰值回撤2%卖出，-2%止损
    平开(-2%~+2%): 分批止盈，50%@+3%, 50%@+6%，-3%止损
    低开(<-2%): 快速脱手，+2%全卖，-2%止损

用法:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 \
        analyze/best_strategy.py

    # 可选参数:
    #   --start 20250201   起始日期(默认20250201)
    #   --end   20251231   结束日期(默认20251231)
    #   --buy-gain 7.9     买入涨幅%(默认7.9)
    #   --seal-before 09:50  封板截止时间
    #   --min-seal 30      最短封板分钟
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

LIMIT_PCT = 0.10           # 主板涨停幅度
SEAL_BEFORE_TIME = '09:50' # 封板截止时间
MIN_SEAL_MINUTES = 30      # 最短连续封板分钟数
BUY_GAIN_PCT = 7.9         # 开板后买入点（相对 preClose 的涨幅%）

# 策略J默认参数
J_HIGH_OPEN_THRESH = 2.0   # 高开分界线(%)
J_LOW_OPEN_THRESH = -2.0   # 低开分界线(%)
J_HIGH_TRAIL_PCT = 2.0     # 高开移动止盈回撤(%)
J_HIGH_STOP_LOSS = -2.0    # 高开止损(%)
J_MID_T1_PCT = 3.0         # 平开第一档止盈(%)
J_MID_T1_RATIO = 0.5       # 平开第一档仓位比例
J_MID_T2_PCT = 6.0         # 平开第二档止盈(%)
J_MID_T2_RATIO = 0.5       # 平开第二档仓位比例
J_MID_STOP_LOSS = -3.0     # 平开止损(%)
J_LOW_TARGET_PCT = 2.0     # 低开止盈(%)
J_LOW_STOP_LOSS = -2.0     # 低开止损(%)


# ============================================================
# 数据类
# ============================================================
@dataclass
class TradeRecord:
    """一笔完整交易记录"""
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


# ============================================================
# 1m K线缓存 & 加载
# ============================================================
_1m_cache: Dict[str, Optional[pd.DataFrame]] = {}


def _find_1m_files(code: str) -> List[str]:
    """查找某只股票所有的1m文件（含子目录）"""
    exch = 'SH' if str(code).startswith('6') else 'SZ'
    # 先在根目录找
    pattern = os.path.join(KLINE_1M_DIR, f'{code}_{exch}_*.csv')
    files = glob.glob(pattern)
    # 再在子目录找（如 1m/2512/）
    pattern_sub = os.path.join(KLINE_1M_DIR, '*', f'{code}_{exch}_*.csv')
    files += glob.glob(pattern_sub)
    return sorted(set(files))


def load_1m_for_date(code: str, date_str: str) -> Optional[pd.DataFrame]:
    """加载某只股票某日的1分钟K线"""
    cache_key = f"{code}_{date_str}"
    if cache_key in _1m_cache:
        return _1m_cache[cache_key]

    # 确定该日期属于哪个月份文件
    year_month_start = date_str[:6] + '01'
    month = int(date_str[4:6])
    if month in [1, 3, 5, 7, 8, 10, 12]:
        year_month_end = date_str[:6] + '31'
    elif month in [4, 6, 9, 11]:
        year_month_end = date_str[:6] + '30'
    else:
        year_month_end = date_str[:6] + '28'

    exch = 'SH' if str(code).startswith('6') else 'SZ'
    # 根目录 + 子目录（如 1m/2512/）都搜
    pattern = os.path.join(KLINE_1M_DIR,
                           f'{code}_{exch}_{year_month_start}_{year_month_end}*.csv')
    pattern_sub = os.path.join(KLINE_1M_DIR, '*',
                               f'{code}_{exch}_{year_month_start}_{year_month_end}*.csv')
    files = glob.glob(pattern) + glob.glob(pattern_sub)

    if not files:
        # 尝试其他可能的日期范围
        for f in _find_1m_files(code):
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

    file_cache_key = files[0]
    if file_cache_key not in _1m_cache:
        try:
            df = pd.read_csv(files[0], encoding='utf-8-sig')
        except Exception:
            _1m_cache[cache_key] = None
            return None

        if not {'date', 'open', 'high', 'low', 'close'}.issubset(df.columns):
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
    """判断是否主板（排除科创板688）"""
    c = str(code).strip()
    if c.startswith('688'):
        return False
    return c.startswith('0') or c.startswith('6')


# ============================================================
# 买入信号扫描（首板策略）
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

        df_range = df_1d[(df_1d['date_str'] >= start_date) &
                         (df_1d['date_str'] <= end_date)]

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

    # 当日需涨停收盘
    if (close_p - limit_price) / limit_price < -0.005:
        return None

    # 首板：前一日未涨停
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
    if (not pd.isna(prev_c)) and (abs(prev_c - prev_limit) / prev_limit <= 0.005):
        return None  # 昨日也涨停 → 非首板

    prev_close_pct = (prev_c - prev_pc) / prev_pc * 100 if not pd.isna(prev_c) else None

    # 加载 1m K线
    day_1m = load_1m_for_date(code, date_str)
    if day_1m is None or len(day_1m) == 0:
        return None

    # 封板检测
    limit_thresh = limit_price * (1 - 0.001)
    sealed = day_1m['close'] >= limit_thresh

    first_seal_idx = sealed.idxmax() if sealed.any() else None
    if first_seal_idx is None or not sealed[first_seal_idx]:
        return None
    first_seal_time = day_1m.at[first_seal_idx, 'time_str']

    if first_seal_time > seal_before:
        return None

    # 连续封板计算
    seal_end_idx = first_seal_idx
    for i in range(first_seal_idx + 1, len(day_1m)):
        if sealed[i]:
            seal_end_idx = i
        else:
            break

    seal_duration = seal_end_idx - first_seal_idx + 1
    if seal_duration < min_seal:
        return None

    # 开板检测
    open_start = seal_end_idx + 1
    if open_start >= len(day_1m):
        return None  # 全天封板

    open_idx = None
    open_time = None
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

    # 获取 Day2 数据（用于策略J卖出）
    day2_data = _get_day2_data(code, idx_1d + 1, df_1d, buy_price)

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
    )


def _get_day2_data(code: str, future_idx: int,
                   df_1d: pd.DataFrame,
                   buy_price: float) -> Optional[dict]:
    """获取次日的日线 + 1m 数据"""
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
    close_pct = (close_p - pre_close) / pre_close * 100 if not pd.isna(close_p) else None

    profit_close = (close_p - buy_price) / buy_price * 100 if not pd.isna(close_p) else None
    profit_high = (high_p - buy_price) / buy_price * 100 if not pd.isna(high_p) else None

    minute_bars = load_1m_for_date(code, date_str)

    return {
        'date': date_str,
        'open': open_p,
        'high': high_p,
        'low': low_p,
        'close': close_p,
        'pre_close': pre_close,
        'open_pct': round(open_pct, 2) if open_pct is not None else None,
        'close_pct': round(close_pct, 2) if close_pct is not None else None,
        'profit_close': round(profit_close, 2) if profit_close is not None else None,
        'profit_high': round(profit_high, 2) if profit_high is not None else None,
        'minute_bars': minute_bars,
    }


# ============================================================
# 策略J：混合最优卖出（Day2执行）
# ============================================================
def _simulate_intraday_sell(minute_bars: Optional[pd.DataFrame],
                            buy_price: float,
                            targets: List[Tuple[float, float]],
                            stop_loss_pct: float = -5.0) -> Tuple[float, str]:
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

    # 尾盘卖出剩余仓位
    if remaining > 0.001:
        last_close = minute_bars.iloc[-1]['close']
        profit = (last_close - buy_price) / buy_price * 100
        total_profit += profit * remaining
        details.append(f'收盘{profit:+.1f}%({remaining:.0%})')

    return round(total_profit, 3), ' | '.join(details) if details else '未执行'


def _trailing_stop_sell(minute_bars: Optional[pd.DataFrame],
                        buy_price: float,
                        trail_pct: float = 2.0,
                        stop_loss_pct: float = -2.0) -> Tuple[float, str]:
    """移动止盈：从峰值回撤 trail_pct% 即卖出"""
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

        # 固定止损
        if bar_low <= stop_price:
            return round(stop_loss_pct, 3), f'止损@{bar_time} {stop_loss_pct:+.1f}%'

        # 移动止盈：至少涨1%后才启动
        if peak > buy_price * 1.01:
            trail_price = peak * (1 - trail_pct / 100)
            if bar_low <= trail_price:
                profit = (trail_price - buy_price) / buy_price * 100
                peak_g = (peak - buy_price) / buy_price * 100
                return round(profit, 3), f'移动止盈@{bar_time} 峰{peak_g:+.1f}%→{profit:+.1f}%'

    # 未触发，收盘卖出
    last_close = minute_bars.iloc[-1]['close']
    profit = (last_close - buy_price) / buy_price * 100
    return round(profit, 3), f'收盘卖 {profit:+.1f}%'


def strategy_j_sell(trade: TradeRecord,
                    high_open_thresh: float = J_HIGH_OPEN_THRESH,
                    low_open_thresh: float = J_LOW_OPEN_THRESH,
                    high_trail_pct: float = J_HIGH_TRAIL_PCT,
                    high_stop_loss: float = J_HIGH_STOP_LOSS,
                    mid_t1_pct: float = J_MID_T1_PCT,
                    mid_t1_ratio: float = J_MID_T1_RATIO,
                    mid_t2_pct: float = J_MID_T2_PCT,
                    mid_t2_ratio: float = J_MID_T2_RATIO,
                    mid_stop_loss: float = J_MID_STOP_LOSS,
                    low_target_pct: float = J_LOW_TARGET_PCT,
                    low_stop_loss: float = J_LOW_STOP_LOSS,
                    ) -> Tuple[float, str]:
    """
    策略J — 混合最优卖出（Day2执行）

    根据次日开盘涨幅自适应选择操作模式：
      高开(>+2%): 移动止盈 → 历史回测100%胜率, 均盈+6.72%
      平开(-2%~+2%): 分批止盈 → 历史回测~86%胜率
      低开(<-2%): 快速脱手 → 历史回测仅23%胜率，快速止损减损
    """
    if trade.day2_data is None:
        return 0.0, '无Day2数据'

    open_pct = trade.day2_data.get('open_pct', 0)
    if open_pct is None:
        return 0.0, '无开盘数据'

    mb = trade.day2_data.get('minute_bars')
    bp = trade.buy_price

    if open_pct > high_open_thresh:
        # ===== 高开: 移动止盈，博取最大收益 =====
        profit, detail = _trailing_stop_sell(
            mb, bp, trail_pct=high_trail_pct, stop_loss_pct=high_stop_loss
        )
        return profit, f'[高开{open_pct:+.1f}%|移动止盈] {detail}'

    elif open_pct >= low_open_thresh:
        # ===== 平开: 分批止盈 =====
        targets = [(mid_t1_pct, mid_t1_ratio), (mid_t2_pct, mid_t2_ratio)]
        profit, detail = _simulate_intraday_sell(
            mb, bp, targets, stop_loss_pct=mid_stop_loss
        )
        return profit, f'[平开{open_pct:+.1f}%|分批] {detail}'

    else:
        # ===== 低开: 快速脱手 =====
        targets = [(low_target_pct, 1.0)]
        profit, detail = _simulate_intraday_sell(
            mb, bp, targets, stop_loss_pct=low_stop_loss
        )
        return profit, f'[低开{open_pct:+.1f}%|快脱] {detail}'


# ============================================================
# 主回测流程
# ============================================================
def run_backtest(start_date: str, end_date: str,
                 buy_gain_pct: float = BUY_GAIN_PCT,
                 seal_before: str = SEAL_BEFORE_TIME,
                 min_seal: int = MIN_SEAL_MINUTES) -> pd.DataFrame:
    """运行完整的买入扫描 + 策略J卖出回测"""
    print("=" * 70)
    print("🎯 最强策略回测：首板买入 + 策略J混合最优卖出")
    print(f"   买入: 首板(主板) | {seal_before}前封板≥{min_seal}分钟 | 开板回落至+{buy_gain_pct}%")
    print(f"   卖出: 策略J(Day2) | 高开移动止盈 | 平开分批 | 低开快脱")
    print(f"   时间: {start_date} ~ {end_date}")
    print("=" * 70)

    # 1. 扫描买入信号
    trades = find_buy_signals(start_date, end_date, buy_gain_pct, seal_before, min_seal)
    if not trades:
        print("  ⚠️ 无买入信号")
        return pd.DataFrame()

    # 2. 对每笔交易执行策略J卖出
    rows = []
    for trade in trades:
        profit, detail = strategy_j_sell(trade)

        row = {
            '股票代码': trade.code,
            '涨停日': trade.buy_date,
            'preClose': trade.pre_close,
            '买入价': trade.buy_price,
            '买入时间': trade.buy_time,
            '封板时间': trade.seal_time,
            '封板持续(分)': trade.seal_duration,
            '开板时间': trade.open_time,
            '前日涨跌(%)': trade.prev_day_pct,
            'Day1开盘涨(%)': trade.day1_open_pct,
            'Day1收盘涨(%)': trade.day1_close_pct,
        }

        if trade.day2_data:
            row['Day2开盘涨(%)'] = trade.day2_data.get('open_pct')
            row['Day2收盘涨(%)'] = trade.day2_data.get('close_pct')

        row['策略J盈亏(%)'] = round(profit, 3) if profit is not None else None
        row['策略J详情'] = detail

        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.sort_values(['涨停日', '封板时间']).reset_index(drop=True)
    return df


def print_summary(df: pd.DataFrame):
    """打印回测统计摘要"""
    pnl_col = '策略J盈亏(%)'
    pnl = df[pnl_col].dropna()

    if len(pnl) == 0:
        print("  ⚠️ 无有效盈亏数据")
        return

    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0

    print("\n" + "=" * 70)
    print("📊 策略J回测统计")
    print("=" * 70)
    print(f"  总交易笔数:   {len(pnl)}")
    print(f"  胜率:         {(pnl > 0).mean() * 100:.1f}%  ({len(wins)} 盈 / {len(losses)} 亏)")
    print(f"  平均盈亏:     {pnl.mean():+.3f}%")
    print(f"  中位盈亏:     {pnl.median():+.3f}%")
    print(f"  最大盈利:     {pnl.max():+.2f}%")
    print(f"  最大亏损:     {pnl.min():+.2f}%")
    print(f"  总收益(等权):  {pnl.sum():+.2f}%")
    if avg_loss != 0:
        print(f"  盈亏比:       {abs(avg_win / avg_loss):.2f}")
    if pnl.std() > 0:
        print(f"  夏普(简):     {pnl.mean() / pnl.std():.3f}")

    # 按 Day2 开盘分类统计
    if 'Day2开盘涨(%)' in df.columns:
        print("\n  📈 按Day2开盘分类:")
        bins = [(-999, -2), (-2, 0), (0, 2), (2, 999)]
        labels = ['低开(<-2%)', '平低(-2%~0%)', '平高(0%~+2%)', '高开(>+2%)']

        for (lo, hi), lab in zip(bins, labels):
            subset = df[(df['Day2开盘涨(%)'] >= lo) & (df['Day2开盘涨(%)'] < hi)]
            if len(subset) == 0:
                print(f"    {lab}: 无样本")
                continue
            sp = subset[pnl_col].dropna()
            if len(sp) == 0:
                continue
            print(f"    {lab}: {len(sp)}笔  "
                  f"胜率={((sp > 0).mean() * 100):.0f}%  "
                  f"均盈={sp.mean():+.2f}%  "
                  f"总收={sp.sum():+.2f}%")

    # 按月份统计
    if '涨停日' in df.columns:
        print("\n  📅 按月份分布:")
        df_t = df.copy()
        df_t['月份'] = df_t['涨停日'].str[:6]
        monthly = df_t.groupby('月份')[pnl_col].agg(['count', 'mean', 'sum'])
        for m, row in monthly.iterrows():
            print(f"    {m}: {int(row['count'])}笔  均{row['mean']:+.2f}%  总{row['sum']:+.2f}%")

    print("=" * 70)


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='最强策略回测：首板买入 + 策略J混合最优卖出')
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
    parser.add_argument('--top', type=int, default=50,
                        help='显示前N笔交易 (默认 50)')
    args = parser.parse_args()

    df = run_backtest(args.start, args.end, args.buy_gain,
                      args.seal_before, args.min_seal)
    if len(df) == 0:
        return

    # 打印交易明细
    print("\n" + "=" * 70)
    print("📋 交易明细")
    print("=" * 70)
    pd.set_option('display.width', 300)
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.float_format', '{:.2f}'.format)

    show_cols = [c for c in [
        '股票代码', '涨停日', '买入价', '买入时间', '封板时间',
        '封板持续(分)', 'Day1收盘涨(%)',
        'Day2开盘涨(%)', 'Day2收盘涨(%)',
        '策略J盈亏(%)', '策略J详情'
    ] if c in df.columns]
    print(df[show_cols].head(args.top).to_string(index=False))

    # 打印统计
    print_summary(df)

    # 保存 Excel
    out_path = os.path.join(OUTPUT_DIR, 'best_strategy_result.xlsx')
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='交易明细', index=False)

        # 统计摘要 sheet
        pnl = df['策略J盈亏(%)'].dropna()
        if len(pnl) > 0:
            wins = pnl[pnl > 0]
            losses = pnl[pnl <= 0]
            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = losses.mean() if len(losses) > 0 else 0
            summary = pd.DataFrame([{
                '总笔数': len(pnl),
                '盈利笔数': len(wins),
                '亏损笔数': len(losses),
                '胜率(%)': round((pnl > 0).mean() * 100, 1),
                '平均盈亏(%)': round(pnl.mean(), 3),
                '中位盈亏(%)': round(pnl.median(), 3),
                '最大盈利(%)': round(pnl.max(), 2),
                '最大亏损(%)': round(pnl.min(), 2),
                '总收益(%)': round(pnl.sum(), 2),
                '盈亏比': round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None,
                '夏普(简)': round(pnl.mean() / pnl.std(), 3) if pnl.std() > 0 else 0,
            }])
            summary.to_excel(writer, sheet_name='策略统计', index=False)

    print(f"\n💾 已保存: {out_path}")


if __name__ == '__main__':
    main()
