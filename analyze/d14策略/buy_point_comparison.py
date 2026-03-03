"""
analyze/buy_point_comparison.py — 创业板/科创板 买点对比回测

研究问题：强势股（日内涨幅能超14%的票），最佳买点在哪里？

三种买入策略对比：
  策略A: 涨到 BUY_A_PCT% 时买入（激进，早上车）
  策略B: 涨到 BUY_B_PCT% 时买入（基准）
  策略C: 确认涨到 CONFIRM_PCT% 后，等回调到 PULLBACK_PCT% 再买（追确认）

适用范围：
  - 创业板(3xx) + 科创板(68x)，涨跌幅 ±20%
  - 排除新股（参考列表中不存在的代码）
  - 使用 1m 分钟线精确确定买点时间和价格

输出：
  - 每种策略的胜率/平均盈亏/收益分布
  - 参数网格搜索（可选）
  - Excel 明细

运行方式:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 \
        analyze/buy_point_comparison.py

    # 可选参数:
    #   --buy-a     13.0   策略A买入涨幅(%)
    #   --buy-b     14.0   策略B买入涨幅(%)
    #   --confirm   17.0   策略C确认涨幅(%)
    #   --pullback  15.0   策略C回调买入涨幅(%)
    #   --grid              启用参数网格搜索
"""
from __future__ import annotations

import os
import sys
import glob
import argparse
from typing import Optional, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import KLINE_ROOT, OUTPUT_DIR
from data_loader import code_to_exchange

# ============================================================
# 默认参数
# ============================================================
BUY_A_PCT     = 13.0   # 策略A：直接在 13% 买
BUY_B_PCT     = 14.0   # 策略B：直接在 14% 买
CONFIRM_PCT   = 17.0   # 策略C：确认涨到 17%
PULLBACK_PCT  = 15.0   # 策略C：回调到 15% 买入

# 日期范围
DEC_START = '20251201'
DEC_END   = '20251231'

KLINE_1D_DIR = os.path.join(KLINE_ROOT, '1d')
KLINE_1M_DIR = os.path.join(KLINE_ROOT, '1m')

# 参考股票列表（排除新股）
REFERENCE_CSV = '/Users/tq/PycharmProjects/stocks_v2/data/2025/china_2025-12-01.csv'

# ============================================================
# 辅助：判断是否创业板/科创板（20%涨跌幅板块）
# ============================================================
def is_cyb_or_star(code: str) -> bool:
    """创业板(3xx)或科创板(68x)"""
    c = str(code).strip()
    return c.startswith('3') or c.startswith('68')


# ============================================================
# 辅助：加载参考股票列表
# ============================================================
def load_reference_codes(csv_path: str) -> set:
    if not os.path.exists(csv_path):
        print("  ⚠️  参考文件不存在: {}，跳过新股过滤".format(csv_path))
        return set()
    df = pd.read_csv(csv_path, usecols=['商品代码'], dtype={'商品代码': str})
    codes = set(df['商品代码'].astype(str).str.strip())
    print("  参考股票列表: {} 只".format(len(codes)))
    return codes


# ============================================================
# 辅助：加载 1m K线（带缓存）
# ============================================================
_1m_cache: Dict[str, Optional[pd.DataFrame]] = {}


def load_1m_dec(code: str) -> Optional[pd.DataFrame]:
    if code in _1m_cache:
        return _1m_cache[code]

    exchange = code_to_exchange(code)
    fname_pattern = '{}_{}_{}_{}*.csv'.format(code, exchange, DEC_START, DEC_END)
    pattern = os.path.join(KLINE_1M_DIR, fname_pattern)
    files = glob.glob(pattern)
    if not files:
        pattern = os.path.join(KLINE_1M_DIR, '**', fname_pattern)
        files = glob.glob(pattern, recursive=True)
    if not files:
        _1m_cache[code] = None
        return None

    try:
        df = pd.read_csv(files[0], encoding='utf-8-sig')
    except Exception as e:
        _1m_cache[code] = None
        return None

    req = {'date', 'open', 'high', 'low', 'close'}
    if not req.issubset(df.columns):
        _1m_cache[code] = None
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

    _1m_cache[code] = df.reset_index(drop=True)
    return _1m_cache[code]


# ============================================================
# 核心：1m 级别模拟买入，计算收益
# ============================================================
def simulate_buy_on_1m(day_1m: pd.DataFrame,
                       pre_close: float,
                       buy_pct: float,
                       strategy_name: str = '') -> Optional[dict]:
    """
    在 1m 分钟线中，找到价格首次达到 pre_close * (1 + buy_pct/100) 的时刻，
    按该价格买入，然后计算当日收盘收益、次日收益等。

    返回: {buy_time, buy_price, buy_idx, ...} 或 None（未触发）
    """
    target_price = pre_close * (1 + buy_pct / 100)

    # 找首次 high >= target_price 的 bar
    hit_rows = day_1m[day_1m['high'] >= target_price]
    if len(hit_rows) == 0:
        return None

    first_row = hit_rows.iloc[0]
    buy_idx   = hit_rows.index[0]
    buy_time  = first_row['time_str']

    # 实际买入价：如果 open >= target_price，以 open 买入；否则以 target_price 买入
    if first_row['open'] >= target_price:
        buy_price = first_row['open']
    else:
        buy_price = target_price

    # 当日收盘价（1m最后一根bar的close）
    day_close = day_1m.iloc[-1]['close']
    same_day_pct = (day_close - buy_price) / buy_price * 100

    # 当日最高价（买入后的最高）
    remaining_bars = day_1m.iloc[buy_idx:]
    day_high_after = remaining_bars['high'].max()
    day_high_pct = (day_high_after - buy_price) / buy_price * 100

    # 当日最低价（买入后的最低）
    day_low_after = remaining_bars['low'].min()
    day_low_pct = (day_low_after - buy_price) / buy_price * 100

    # 买入后剩余分钟数
    remaining_minutes = len(day_1m) - 1 - buy_idx

    # 涨停价
    limit_price = pre_close * 1.20
    last_bar = day_1m.iloc[-1]
    is_limit_up = (
        abs(last_bar['close'] - limit_price) <= limit_price * 0.005
        and abs(last_bar['close'] - last_bar['high']) < 0.002
    )

    return {
        'buy_time':         buy_time,
        'buy_price':        round(buy_price, 3),
        'buy_idx':          buy_idx,
        'buy_pct_actual':   round((buy_price - pre_close) / pre_close * 100, 2),
        'day_close':        round(day_close, 3),
        'same_day_pct':     round(same_day_pct, 2),
        'day_high_pct':     round(day_high_pct, 2),
        'day_low_pct':      round(day_low_pct, 2),
        'remaining_min':    remaining_minutes,
        'is_limit_up':      is_limit_up,
    }


def simulate_pullback_buy(day_1m: pd.DataFrame,
                          pre_close: float,
                          confirm_pct: float,
                          pullback_pct: float) -> Optional[dict]:
    """
    策略C：先确认涨到 confirm_pct%, 然后等回调到 pullback_pct% 时买入。

    返回: 同 simulate_buy_on_1m 格式，额外包含确认时间等信息
    """
    confirm_price  = pre_close * (1 + confirm_pct / 100)
    pullback_price = pre_close * (1 + pullback_pct / 100)

    # Step1: 找到首次确认点（high >= confirm_price）
    confirm_rows = day_1m[day_1m['high'] >= confirm_price]
    if len(confirm_rows) == 0:
        return None

    confirm_idx  = confirm_rows.index[0]
    confirm_time = confirm_rows.iloc[0]['time_str']

    # Step2: 确认之后，找回调到 pullback_price 的 bar（low <= pullback_price）
    after_confirm = day_1m.iloc[confirm_idx + 1:]  # 确认后的下一根 bar 开始
    if len(after_confirm) == 0:
        return {'status': 'no_pullback', 'confirm_time': confirm_time}

    pullback_rows = after_confirm[after_confirm['low'] <= pullback_price]
    if len(pullback_rows) == 0:
        return {'status': 'no_pullback', 'confirm_time': confirm_time}

    first_pull = pullback_rows.iloc[0]
    buy_idx    = pullback_rows.index[0]
    buy_time   = first_pull['time_str']

    # 买入价取 pullback_price（因为 low <= pullback_price）
    if first_pull['open'] <= pullback_price:
        buy_price = first_pull['open']
    else:
        buy_price = pullback_price

    # 当日收盘
    day_close = day_1m.iloc[-1]['close']
    same_day_pct = (day_close - buy_price) / buy_price * 100

    remaining_bars = day_1m.iloc[buy_idx:]
    day_high_after = remaining_bars['high'].max()
    day_high_pct = (day_high_after - buy_price) / buy_price * 100
    day_low_after = remaining_bars['low'].min()
    day_low_pct = (day_low_after - buy_price) / buy_price * 100

    remaining_minutes = len(day_1m) - 1 - buy_idx

    limit_price = pre_close * 1.20
    last_bar = day_1m.iloc[-1]
    is_limit_up = (
        abs(last_bar['close'] - limit_price) <= limit_price * 0.005
        and abs(last_bar['close'] - last_bar['high']) < 0.002
    )

    return {
        'status':           'filled',
        'confirm_time':     confirm_time,
        'buy_time':         buy_time,
        'buy_price':        round(buy_price, 3),
        'buy_idx':          buy_idx,
        'buy_pct_actual':   round((buy_price - pre_close) / pre_close * 100, 2),
        'day_close':        round(day_close, 3),
        'same_day_pct':     round(same_day_pct, 2),
        'day_high_pct':     round(day_high_pct, 2),
        'day_low_pct':      round(day_low_pct, 2),
        'remaining_min':    remaining_minutes,
        'is_limit_up':      is_limit_up,
    }


# ============================================================
# 单只股票单日：三策略对比
# ============================================================
def analyze_one_day(code: str, date_str: str,
                    df_1d: pd.DataFrame,
                    buy_a_pct: float, buy_b_pct: float,
                    confirm_pct: float, pullback_pct: float) -> Optional[dict]:
    """
    对单只股票单日运行三种买入策略，返回合并结果。
    前置条件：日线峰值涨幅 >= min(buy_a_pct, buy_b_pct)（由外层预筛选保证）
    """
    idx_list = df_1d.index[df_1d['date_str'] == date_str].tolist()
    if not idx_list:
        return None
    idx_1d = idx_list[0]
    day = df_1d.iloc[idx_1d]

    # --- preClose ---
    pre_close = pd.to_numeric(day.get('preClose', None), errors='coerce')
    if pd.isna(pre_close) or pre_close <= 0:
        if idx_1d == 0:
            return None
        pre_close = df_1d.iloc[idx_1d - 1]['close']
    if pd.isna(pre_close) or pre_close <= 0:
        return None

    open_p  = pd.to_numeric(day['open'],  errors='coerce')
    high_p  = pd.to_numeric(day['high'],  errors='coerce')
    close_p = pd.to_numeric(day['close'], errors='coerce')
    if pd.isna(high_p) or pd.isna(close_p) or pd.isna(open_p):
        return None

    peak_pct  = (high_p - pre_close) / pre_close * 100
    open_pct  = (open_p - pre_close) / pre_close * 100
    close_pct = (close_p - pre_close) / pre_close * 100

    # --- 上一日收(跌)幅 ---
    prev_close_pct = None
    if idx_1d > 0:
        prev    = df_1d.iloc[idx_1d - 1]
        prev_c  = pd.to_numeric(prev['close'], errors='coerce')
        prev_pc = pd.to_numeric(prev.get('preClose', None), errors='coerce')
        if (pd.isna(prev_pc) or prev_pc <= 0) and idx_1d >= 2:
            prev_pc = df_1d.iloc[idx_1d - 2]['close']
        if not pd.isna(prev_c) and not pd.isna(prev_pc) and prev_pc > 0:
            prev_close_pct = (prev_c - prev_pc) / prev_pc * 100

    # --- 次日日线数据 ---
    next_day_pct = None
    next_day_high_pct = None
    next_day_low_pct = None
    next_open_pct = None
    if idx_1d < len(df_1d) - 1:
        nxt = df_1d.iloc[idx_1d + 1]
        nxt_c = pd.to_numeric(nxt['close'], errors='coerce')
        nxt_o = pd.to_numeric(nxt['open'],  errors='coerce')
        nxt_h = pd.to_numeric(nxt['high'],  errors='coerce')
        nxt_l = pd.to_numeric(nxt['low'],   errors='coerce')
        nxt_pc = pd.to_numeric(nxt.get('preClose', None), errors='coerce')
        if pd.isna(nxt_pc) or nxt_pc <= 0:
            nxt_pc = close_p
        if not pd.isna(nxt_c) and nxt_pc > 0:
            next_day_pct = (nxt_c - nxt_pc) / nxt_pc * 100
        if not pd.isna(nxt_o) and nxt_pc > 0:
            next_open_pct = (nxt_o - nxt_pc) / nxt_pc * 100
        if not pd.isna(nxt_h) and nxt_pc > 0:
            next_day_high_pct = (nxt_h - nxt_pc) / nxt_pc * 100
        if not pd.isna(nxt_l) and nxt_pc > 0:
            next_day_low_pct = (nxt_l - nxt_pc) / nxt_pc * 100

    # --- 加载 1m 分钟线 ---
    df_1m_all = load_1m_dec(code)
    if df_1m_all is None:
        return None

    day_1m = df_1m_all[df_1m_all['date_str'] == date_str].copy().reset_index(drop=True)
    if len(day_1m) == 0:
        return None

    # --- 模拟三种策略 ---
    result_a = simulate_buy_on_1m(day_1m, pre_close, buy_a_pct, 'A')
    result_b = simulate_buy_on_1m(day_1m, pre_close, buy_b_pct, 'B')
    result_c = simulate_pullback_buy(day_1m, pre_close, confirm_pct, pullback_pct)

    # 至少有一种策略触发，才记录
    if result_a is None and result_b is None and result_c is None:
        return None

    rec = {
        '股票代码':          code,
        '日期':              date_str,
        'preClose':          round(pre_close, 3),
        '上一日收跌幅(%)':   round(prev_close_pct, 2) if prev_close_pct is not None else None,
        '开盘涨幅(%)':       round(open_pct, 2),
        '峰值涨幅(%)':       round(peak_pct, 2),
        '收盘涨幅(%)':       round(close_pct, 2),
        '次日涨跌幅(%)':     round(next_day_pct, 2) if next_day_pct is not None else None,
    }

    # --- 策略A ---
    if result_a:
        rec['A_买入时间']      = result_a['buy_time']
        rec['A_买入价']        = result_a['buy_price']
        rec['A_实际买入涨幅(%)'] = result_a['buy_pct_actual']
        rec['A_当日收益(%)']   = result_a['same_day_pct']
        rec['A_日内最高收益(%)'] = result_a['day_high_pct']
        rec['A_日内最低(%)']   = result_a['day_low_pct']
        # 次日收益（从策略A买入价出发）
        if idx_1d < len(df_1d) - 1:
            nxt = df_1d.iloc[idx_1d + 1]
            nxt_c = pd.to_numeric(nxt['close'], errors='coerce')
            nxt_h = pd.to_numeric(nxt['high'],  errors='coerce')
            if not pd.isna(nxt_c):
                rec['A_次日收盘收益(%)'] = round((nxt_c - result_a['buy_price']) / result_a['buy_price'] * 100, 2)
            if not pd.isna(nxt_h):
                rec['A_次日最高收益(%)'] = round((nxt_h - result_a['buy_price']) / result_a['buy_price'] * 100, 2)
    else:
        rec['A_买入时间'] = None
        rec['A_买入价'] = None
        rec['A_实际买入涨幅(%)'] = None
        rec['A_当日收益(%)'] = None
        rec['A_日内最高收益(%)'] = None
        rec['A_日内最低(%)'] = None
        rec['A_次日收盘收益(%)'] = None
        rec['A_次日最高收益(%)'] = None

    # --- 策略B ---
    if result_b:
        rec['B_买入时间']      = result_b['buy_time']
        rec['B_买入价']        = result_b['buy_price']
        rec['B_实际买入涨幅(%)'] = result_b['buy_pct_actual']
        rec['B_当日收益(%)']   = result_b['same_day_pct']
        rec['B_日内最高收益(%)'] = result_b['day_high_pct']
        rec['B_日内最低(%)']   = result_b['day_low_pct']
        if idx_1d < len(df_1d) - 1:
            nxt = df_1d.iloc[idx_1d + 1]
            nxt_c = pd.to_numeric(nxt['close'], errors='coerce')
            nxt_h = pd.to_numeric(nxt['high'],  errors='coerce')
            if not pd.isna(nxt_c):
                rec['B_次日收盘收益(%)'] = round((nxt_c - result_b['buy_price']) / result_b['buy_price'] * 100, 2)
            if not pd.isna(nxt_h):
                rec['B_次日最高收益(%)'] = round((nxt_h - result_b['buy_price']) / result_b['buy_price'] * 100, 2)
    else:
        rec['B_买入时间'] = None
        rec['B_买入价'] = None
        rec['B_实际买入涨幅(%)'] = None
        rec['B_当日收益(%)'] = None
        rec['B_日内最高收益(%)'] = None
        rec['B_日内最低(%)'] = None
        rec['B_次日收盘收益(%)'] = None
        rec['B_次日最高收益(%)'] = None

    # --- 策略C ---
    if result_c and result_c.get('status') == 'filled':
        rec['C_确认时间']      = result_c['confirm_time']
        rec['C_买入时间']      = result_c['buy_time']
        rec['C_买入价']        = result_c['buy_price']
        rec['C_实际买入涨幅(%)'] = result_c['buy_pct_actual']
        rec['C_当日收益(%)']   = result_c['same_day_pct']
        rec['C_日内最高收益(%)'] = result_c['day_high_pct']
        rec['C_日内最低(%)']   = result_c['day_low_pct']
        rec['C_成交']          = '是'
        if idx_1d < len(df_1d) - 1:
            nxt = df_1d.iloc[idx_1d + 1]
            nxt_c = pd.to_numeric(nxt['close'], errors='coerce')
            nxt_h = pd.to_numeric(nxt['high'],  errors='coerce')
            if not pd.isna(nxt_c):
                rec['C_次日收盘收益(%)'] = round((nxt_c - result_c['buy_price']) / result_c['buy_price'] * 100, 2)
            if not pd.isna(nxt_h):
                rec['C_次日最高收益(%)'] = round((nxt_h - result_c['buy_price']) / result_c['buy_price'] * 100, 2)
    elif result_c and result_c.get('status') == 'no_pullback':
        rec['C_确认时间']      = result_c['confirm_time']
        rec['C_买入时间']      = None
        rec['C_买入价']        = None
        rec['C_实际买入涨幅(%)'] = None
        rec['C_当日收益(%)']   = None
        rec['C_日内最高收益(%)'] = None
        rec['C_日内最低(%)']   = None
        rec['C_成交']          = '否(未回调)'
        rec['C_次日收盘收益(%)'] = None
        rec['C_次日最高收益(%)'] = None
    else:
        rec['C_确认时间']      = None
        rec['C_买入时间']      = None
        rec['C_买入价']        = None
        rec['C_实际买入涨幅(%)'] = None
        rec['C_当日收益(%)']   = None
        rec['C_日内最高收益(%)'] = None
        rec['C_日内最低(%)']   = None
        rec['C_成交']          = '否(未达确认线)'
        rec['C_次日收盘收益(%)'] = None
        rec['C_次日最高收益(%)'] = None

    return rec


# ============================================================
# 打印策略统计摘要
# ============================================================
def print_strategy_stats(df: pd.DataFrame, prefix: str, label: str):
    """打印单个策略的统计结果"""
    col_sd  = '{}_当日收益(%)'.format(prefix)
    col_nc  = '{}_次日收盘收益(%)'.format(prefix)
    col_nh  = '{}_次日最高收益(%)'.format(prefix)
    col_hi  = '{}_日内最高收益(%)'.format(prefix)
    col_lo  = '{}_日内最低(%)'.format(prefix)

    if col_sd not in df.columns:
        print("  {} — 无数据".format(label))
        return

    valid = df[col_sd].dropna()
    total = len(df)
    triggered = len(valid)
    fill_rate = triggered / total * 100 if total > 0 else 0

    print("\n  ---- {} (触发 {}/{} = {:.1f}%) ----".format(
        label, triggered, total, fill_rate))

    if triggered == 0:
        return

    # 当日收益
    win = (valid > 0).sum()
    loss = (valid <= 0).sum()
    print("  当日收盘:  均值={:+.2f}%  中位={:+.2f}%  胜率={:.1f}%  ({}/{})"
          .format(valid.mean(), valid.median(), win / triggered * 100, win, triggered))
    print("             最大盈={:+.2f}%  最大亏={:+.2f}%".format(valid.max(), valid.min()))

    # 日内最高/最低
    hi = df[col_hi].dropna()
    lo = df[col_lo].dropna()
    if len(hi) > 0:
        print("  日内最高:  均值={:+.2f}%  最大={:+.2f}%".format(hi.mean(), hi.max()))
    if len(lo) > 0:
        print("  日内最低:  均值={:+.2f}%  最大回撤={:+.2f}%".format(lo.mean(), lo.min()))

    # 次日收益
    nc = df[col_nc].dropna()
    nh = df[col_nh].dropna()
    if len(nc) > 0:
        win_nc = (nc > 0).sum()
        print("  次日收盘:  均值={:+.2f}%  中位={:+.2f}%  胜率={:.1f}%"
              .format(nc.mean(), nc.median(), win_nc / len(nc) * 100))
    if len(nh) > 0:
        print("  次日最高:  均值={:+.2f}%".format(nh.mean()))

    # 收益分布
    bins = [-100, -8, -5, -3, -1, 0, 1, 3, 5, 8, 100]
    dist = pd.cut(valid, bins=bins).value_counts().sort_index()
    print("  收益分布:")
    for interval, cnt in dist.items():
        bar = '█' * int(cnt / triggered * 40)
        print("    {:>12s}  {:>3d} ({:>5.1f}%)  {}".format(
            str(interval), cnt, cnt / triggered * 100, bar))


# ============================================================
# 参数网格搜索
# ============================================================
def run_grid_search(all_1d_data: Dict[str, pd.DataFrame],
                    ref_codes: set) -> pd.DataFrame:
    """
    网格搜索不同的买入参数组合，输出汇总表。
    """
    print("\n" + "=" * 70)
    print("🔍 参数网格搜索")
    print("=" * 70)

    # 网格参数
    buy_a_range     = [12.0, 13.0, 14.0]
    buy_b_range     = [13.0, 14.0, 15.0]
    confirm_range   = [16.0, 17.0, 18.0]
    pullback_range  = [14.0, 15.0, 16.0]

    grid_results = []
    total_combos = len(buy_a_range) * len(buy_b_range) * len(confirm_range) * len(pullback_range)
    combo_idx = 0

    for buy_a in buy_a_range:
        for buy_b in buy_b_range:
            if buy_b <= buy_a:
                continue  # B 应该 > A
            for confirm in confirm_range:
                for pullback in pullback_range:
                    if pullback >= confirm:
                        continue  # 回调价应 < 确认价
                    combo_idx += 1
                    print("  [{}/{}] A={}% B={}% C={}%→{}%".format(
                        combo_idx, '?', buy_a, buy_b, confirm, pullback), end='')

                    results = run_single_scan(
                        all_1d_data, ref_codes,
                        buy_a, buy_b, confirm, pullback,
                        verbose=False
                    )
                    if not results:
                        print(" → 0条")
                        continue

                    df_r = pd.DataFrame(results)
                    row = {'buy_a': buy_a, 'buy_b': buy_b,
                           'confirm': confirm, 'pullback': pullback}

                    for prefix, label in [('A', 'A'), ('B', 'B'), ('C', 'C')]:
                        col = '{}_当日收益(%)'.format(prefix)
                        col_nc = '{}_次日收盘收益(%)'.format(prefix)
                        valid = df_r[col].dropna() if col in df_r.columns else pd.Series([], dtype=float)
                        valid_nc = df_r[col_nc].dropna() if col_nc in df_r.columns else pd.Series([], dtype=float)

                        row['{}_触发数'.format(label)] = len(valid)
                        row['{}_当日均值'.format(label)] = round(valid.mean(), 2) if len(valid) > 0 else None
                        row['{}_当日胜率'.format(label)] = round((valid > 0).mean() * 100, 1) if len(valid) > 0 else None
                        row['{}_次日均值'.format(label)] = round(valid_nc.mean(), 2) if len(valid_nc) > 0 else None
                        row['{}_次日胜率'.format(label)] = round((valid_nc > 0).mean() * 100, 1) if len(valid_nc) > 0 else None

                    # 策略C成交率
                    if 'C_成交' in df_r.columns:
                        c_total = len(df_r[df_r['C_确认时间'].notna()])
                        c_filled = len(df_r[df_r['C_成交'] == '是'])
                        row['C_成交率'] = round(c_filled / c_total * 100, 1) if c_total > 0 else None
                    else:
                        row['C_成交率'] = None

                    grid_results.append(row)
                    print(" → {}条  A={}/{:.1f}%  B={}/{:.1f}%  C={}/{}"
                          .format(len(df_r),
                                  row.get('A_触发数', 0), row.get('A_当日胜率', 0) or 0,
                                  row.get('B_触发数', 0), row.get('B_当日胜率', 0) or 0,
                                  row.get('C_触发数', 0), row.get('C_成交率', 0) or 0))

    return pd.DataFrame(grid_results)


# ============================================================
# 单次扫描（供主流程和网格搜索复用）
# ============================================================
def run_single_scan(all_1d_data: Dict[str, pd.DataFrame],
                    ref_codes: set,
                    buy_a_pct: float, buy_b_pct: float,
                    confirm_pct: float, pullback_pct: float,
                    verbose: bool = True) -> List[dict]:
    """
    遍历所有创业板/科创板股票，运行三策略对比。
    """
    min_threshold = min(buy_a_pct, buy_b_pct)
    results = []

    for key, df_1d in sorted(all_1d_data.items()):
        code = key.split('_')[0]

        # 排除新股
        if ref_codes and code not in ref_codes:
            continue

        # 快速过滤：12月是否有峰值涨幅 >= min_threshold
        df_dec = df_1d[(df_1d['date_str'] >= DEC_START) & (df_1d['date_str'] <= DEC_END)]
        if len(df_dec) == 0:
            continue

        for abs_idx, drow in df_dec.iterrows():
            pc = drow.get('preClose', None)
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                pc = float('nan')
            if pd.isna(pc) or pc <= 0:
                pos = df_1d.index.get_loc(abs_idx)
                if pos > 0:
                    pc = df_1d.iloc[pos - 1]['close']
            if pd.isna(pc) or pc <= 0:
                continue
            high_p = drow['high']
            if pd.isna(high_p):
                continue
            if (high_p - pc) / pc * 100 >= min_threshold:
                rec = analyze_one_day(code, drow['date_str'], df_1d,
                                      buy_a_pct, buy_b_pct,
                                      confirm_pct, pullback_pct)
                if rec:
                    results.append(rec)

    return results


# ============================================================
# 数据预加载
# ============================================================
def preload_1d_data() -> Dict[str, pd.DataFrame]:
    """预加载所有创业板/科创板的日线数据"""
    all_1d_files = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    code_files: Dict[str, List[str]] = {}

    for f in all_1d_files:
        bn = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) < 4:
            continue
        code    = parts[0]
        exch    = parts[1]
        start_d = parts[2]
        end_d   = parts[3].replace('.csv', '')

        # 只要创业板 + 科创板
        if not is_cyb_or_star(code):
            continue
        # 排除北交所
        if exch == 'BJ':
            continue
        if start_d <= DEC_END and end_d >= DEC_START:
            key = '{}_{}'.format(code, exch)
            code_files.setdefault(key, []).append(f)

    print("  创业板/科创板日线文件: {} 只".format(len(code_files)))

    all_1d_data: Dict[str, pd.DataFrame] = {}
    for key, files in sorted(code_files.items()):
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
        all_1d_data[key] = df_1d

    print("  成功加载: {} 只".format(len(all_1d_data)))
    return all_1d_data


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='创业板/科创板 买点对比回测')
    parser.add_argument('--buy-a',    type=float, default=BUY_A_PCT,
                        help='策略A买入涨幅%%（默认 {}）'.format(BUY_A_PCT))
    parser.add_argument('--buy-b',    type=float, default=BUY_B_PCT,
                        help='策略B买入涨幅%%（默认 {}）'.format(BUY_B_PCT))
    parser.add_argument('--confirm',  type=float, default=CONFIRM_PCT,
                        help='策略C确认涨幅%%（默认 {}）'.format(CONFIRM_PCT))
    parser.add_argument('--pullback', type=float, default=PULLBACK_PCT,
                        help='策略C回调买入涨幅%%（默认 {}）'.format(PULLBACK_PCT))
    parser.add_argument('--grid', action='store_true',
                        help='启用参数网格搜索')
    args = parser.parse_args()

    buy_a    = args.buy_a
    buy_b    = args.buy_b
    confirm  = args.confirm
    pullback = args.pullback

    print("=" * 70)
    print("🎯 创业板/科创板 买点对比回测")
    print("=" * 70)
    print("  策略A: 涨到 {}% 直接买入".format(buy_a))
    print("  策略B: 涨到 {}% 直接买入".format(buy_b))
    print("  策略C: 涨到 {}% 确认后，回调到 {}% 买入".format(confirm, pullback))
    print("  数据范围: {} ~ {}".format(DEC_START, DEC_END))
    print("=" * 70)

    # Step1: 预加载日线数据
    print("\n📂 加载日线数据...")
    all_1d_data = preload_1d_data()

    # Step2: 加载参考股票列表
    ref_codes = load_reference_codes(REFERENCE_CSV)

    # Step3: 扫描
    print("\n🔍 开始扫描...")
    results = run_single_scan(all_1d_data, ref_codes,
                              buy_a, buy_b, confirm, pullback,
                              verbose=True)

    print("\n✅ 扫描完成  命中 {} 条".format(len(results)))

    if not results:
        print("  ⚠️  未找到满足条件的股票")
        return

    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values(['日期', '峰值涨幅(%)'],
                                       ascending=[True, False]).reset_index(drop=True)

    # ================================================================
    # 统计结果
    # ================================================================
    print("\n" + "=" * 70)
    print("📊 三策略对比统计（共 {} 条 / 创业板+科创板）".format(len(result_df)))
    print("=" * 70)

    print_strategy_stats(result_df, 'A',
                         '策略A: 涨到{}%直接买'.format(buy_a))
    print_strategy_stats(result_df, 'B',
                         '策略B: 涨到{}%直接买'.format(buy_b))
    print_strategy_stats(result_df, 'C',
                         '策略C: 涨到{}%确认→回调到{}%买'.format(confirm, pullback))

    # 策略C成交率分析
    if 'C_成交' in result_df.columns:
        print("\n  ---- 策略C成交分析 ----")
        c_dist = result_df['C_成交'].value_counts()
        for k, v in c_dist.items():
            print("    {}: {} ({:.1f}%)".format(k, v, v / len(result_df) * 100))

    # ================================================================
    # 分组分析：按峰值涨幅区间
    # ================================================================
    print("\n" + "=" * 70)
    print("📊 按峰值涨幅区间分析")
    print("=" * 70)

    peak_bins = [12, 14, 16, 18, 20, 100]
    peak_labels = ['14-16%', '16-18%', '18-20%', '20%+']
    # 只取峰值 >= 14 才有意义
    df_14plus = result_df[result_df['峰值涨幅(%)'] >= 14].copy()
    if len(df_14plus) > 0:
        df_14plus['peak_bin'] = pd.cut(df_14plus['峰值涨幅(%)'],
                                        bins=[14, 16, 18, 20, 100],
                                        labels=['14-16%', '16-18%', '18-20%', '20%+'],
                                        right=False)

        for bin_label in ['14-16%', '16-18%', '18-20%', '20%+']:
            subset = df_14plus[df_14plus['peak_bin'] == bin_label]
            if len(subset) == 0:
                continue
            print("\n  ◆ 峰值涨幅 {} (n={})".format(bin_label, len(subset)))
            for prefix, s_label in [('A', 'A'), ('B', 'B'), ('C', 'C')]:
                col = '{}_当日收益(%)'.format(prefix)
                if col not in subset.columns:
                    continue
                v = subset[col].dropna()
                if len(v) == 0:
                    print("    {}: 无成交".format(s_label))
                    continue
                print("    {}: n={}  均值={:+.2f}%  胜率={:.0f}%".format(
                    s_label, len(v), v.mean(), (v > 0).mean() * 100))

    # ================================================================
    # 分组分析：按买入时间段
    # ================================================================
    print("\n" + "=" * 70)
    print("📊 按买入时间段分析")
    print("=" * 70)

    for prefix, label in [('A', '策略A'), ('B', '策略B')]:
        col_time = '{}_买入时间'.format(prefix)
        col_sd   = '{}_当日收益(%)'.format(prefix)
        if col_time not in result_df.columns:
            continue

        valid_time = result_df[result_df[col_time].notna()].copy()
        if len(valid_time) == 0:
            continue

        valid_time['_hour'] = valid_time[col_time].astype(str).str.split(':').str[0].astype(float)

        print("\n  ◆ {} 按时间段".format(label))
        for trange, tname in [((9, 10), '早盘9-10h'), ((10, 11), '10-11h'),
                               ((11, 14), '午盘11-14h'), ((14, 16), '尾盘14-15h')]:
            t_sub = valid_time[(valid_time['_hour'] >= trange[0]) &
                               (valid_time['_hour'] < trange[1])]
            if len(t_sub) < 2:
                continue
            v = t_sub[col_sd].dropna()
            if len(v) == 0:
                continue
            print("    {}: n={}  均值={:+.2f}%  胜率={:.0f}%".format(
                tname, len(v), v.mean(), (v > 0).mean() * 100))

    # ================================================================
    # 核心对比表
    # ================================================================
    print("\n" + "=" * 70)
    print("📊 策略核心对比（一表总览）")
    print("=" * 70)
    header = "{:<25s} {:>6s} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s}".format(
        '策略', '触发数', '当日均值', '当日胜率', '次日均值', '次日胜率', '成交率')
    print(header)
    print("-" * 75)

    for prefix, label in [('A', '策略A({}%)'.format(buy_a)),
                           ('B', '策略B({}%)'.format(buy_b)),
                           ('C', '策略C({}→{}%)'.format(confirm, pullback))]:
        col_sd = '{}_当日收益(%)'.format(prefix)
        col_nc = '{}_次日收盘收益(%)'.format(prefix)
        v_sd = result_df[col_sd].dropna() if col_sd in result_df.columns else pd.Series([], dtype=float)
        v_nc = result_df[col_nc].dropna() if col_nc in result_df.columns else pd.Series([], dtype=float)

        triggered = len(v_sd)
        total = len(result_df)
        fill_rate = triggered / total * 100 if total > 0 else 0

        sd_mean = "{:+.2f}%".format(v_sd.mean()) if len(v_sd) > 0 else "N/A"
        sd_win  = "{:.1f}%".format((v_sd > 0).mean() * 100) if len(v_sd) > 0 else "N/A"
        nc_mean = "{:+.2f}%".format(v_nc.mean()) if len(v_nc) > 0 else "N/A"
        nc_win  = "{:.1f}%".format((v_nc > 0).mean() * 100) if len(v_nc) > 0 else "N/A"
        fill_s  = "{:.1f}%".format(fill_rate)

        print("{:<25s} {:>6d} {:>8s} {:>8s} {:>8s} {:>8s} {:>8s}".format(
            label, triggered, sd_mean, sd_win, nc_mean, nc_win, fill_s))

    # ================================================================
    # 保存 Excel
    # ================================================================
    out_name = 'buy_point_comparison_{}_{}_{}_{}.xlsx'.format(
        int(buy_a), int(buy_b), int(confirm), int(pullback))
    out_path = os.path.join(OUTPUT_DIR, out_name)
    result_df.to_excel(out_path, index=False)
    print("\n💾 已保存明细: {}".format(out_path))

    # ================================================================
    # 可选：网格搜索
    # ================================================================
    if args.grid:
        grid_df = run_grid_search(all_1d_data, ref_codes)
        if len(grid_df) > 0:
            grid_path = os.path.join(OUTPUT_DIR, 'buy_point_grid_results.xlsx')
            grid_df.to_excel(grid_path, index=False)
            print("\n💾 网格搜索结果: {}".format(grid_path))

            # 打印 top 结果
            print("\n" + "=" * 70)
            print("📊 网格搜索 TOP 10（按策略A当日均值排序）")
            print("=" * 70)
            top = grid_df.sort_values('A_当日均值', ascending=False).head(10)
            print(top.to_string(index=False))

    # 预览
    print("\n📋 数据预览（前30条）:")
    pd.set_option('display.max_columns', 30)
    pd.set_option('display.width', 300)
    preview_cols = ['股票代码', '日期', '峰值涨幅(%)', '收盘涨幅(%)',
                    'A_买入时间', 'A_当日收益(%)',
                    'B_买入时间', 'B_当日收益(%)',
                    'C_成交', 'C_当日收益(%)']
    avail_cols = [c for c in preview_cols if c in result_df.columns]
    print(result_df[avail_cols].head(30).to_string(index=False))


if __name__ == '__main__':
    main()
