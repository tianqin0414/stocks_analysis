"""
analyze/backtest_dec2025.py — 2025年12月首板策略J回测

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
    /Users/tq/PycharmProjects/stocks_v2/venv/bin/python analyze/backtest_dec2025.py
"""
from __future__ import annotations

import os
import sys
import glob
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import KLINE_ROOT, OUTPUT_DIR

# ============================================================
# 路径
# ============================================================
KLINE_1D_DIR = os.path.join(KLINE_ROOT, '1d')
KLINE_1M_DIR = os.path.join(KLINE_ROOT, '1m', '2512')  # 12月1m数据在子目录

START_DATE = '20251201'
END_DATE = '20251231'

# 买入参数
LIMIT_PCT = 0.10
SEAL_BEFORE = '09:50'
MIN_SEAL = 30
BUY_GAIN_PCT = 7.9

# 策略J卖出参数
J_HIGH_OPEN = 2.0
J_LOW_OPEN = -2.0
J_HIGH_TRAIL = 2.0
J_HIGH_STOP = -2.0
J_MID_T1 = 3.0
J_MID_T2 = 6.0
J_MID_STOP = -3.0
J_LOW_TARGET = 2.0
J_LOW_STOP = -2.0


# ============================================================
# 数据类
# ============================================================
@dataclass
class Trade:
    code: str
    buy_date: str
    buy_price: float
    pre_close: float
    buy_time: str
    seal_time: str
    seal_min: int
    open_time: str
    day1_close_pct: float
    day2_open_pct: Optional[float] = None
    day2_close_pct: Optional[float] = None
    sell_profit: Optional[float] = None
    sell_detail: str = ''


# ============================================================
# 1m K线加载
# ============================================================
_cache_1m: Dict[str, Optional[pd.DataFrame]] = {}


def load_1m(code: str, date_str: str) -> Optional[pd.DataFrame]:
    """加载某只股票某日的1分钟K线"""
    key = f"{code}_{date_str}"
    if key in _cache_1m:
        return _cache_1m[key]

    exch = 'SH' if code.startswith('6') else 'SZ'
    pattern = os.path.join(KLINE_1M_DIR, f'{code}_{exch}_*_*.csv')
    files = glob.glob(pattern)

    if not files:
        _cache_1m[key] = None
        return None

    # 找覆盖该日期的文件
    target_file = None
    for f in files:
        bn = os.path.basename(f).replace('.csv', '')
        parts = bn.split('_')
        if len(parts) >= 4 and parts[2] <= date_str <= parts[3]:
            target_file = f
            break

    if not target_file:
        _cache_1m[key] = None
        return None

    # 加载整个文件（缓存）
    file_key = f"__file__{target_file}"
    if file_key not in _cache_1m:
        try:
            df = pd.read_csv(target_file, encoding='utf-8-sig')
            if not {'date', 'open', 'high', 'low', 'close'}.issubset(df.columns):
                _cache_1m[file_key] = None
            else:
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
                _cache_1m[file_key] = df
        except Exception:
            _cache_1m[file_key] = None

    full_df = _cache_1m.get(file_key)
    if full_df is None:
        _cache_1m[key] = None
        return None

    day_df = full_df[full_df['date_str'] == date_str].copy().reset_index(drop=True)
    result = day_df if len(day_df) > 0 else None
    _cache_1m[key] = result
    return result


# ============================================================
# 主板判断
# ============================================================
def is_main_board(code: str) -> bool:
    c = str(code).strip()
    return (c.startswith('0') or c.startswith('6')) and not c.startswith('688')


# ============================================================
# 买入信号扫描
# ============================================================
def scan_buy_signals() -> List[Trade]:
    """扫描12月所有主板首板买入信号"""
    all_1d = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    code_files: Dict[str, List[str]] = {}

    for f in all_1d:
        bn = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) < 4:
            continue
        code, exch = parts[0], parts[1]
        f_start = parts[2]
        f_end = parts[3].replace('.csv', '')
        if exch == 'BJ' or not is_main_board(code):
            continue
        if f_start <= END_DATE and f_end >= START_DATE:
            key = f'{code}_{exch}'
            code_files.setdefault(key, []).append(f)

    total = len(code_files)
    print(f"  扫描主板股票: {total} 只")

    trades: List[Trade] = []

    for i, (key, files) in enumerate(sorted(code_files.items())):
        code = key.split('_')[0]
        if (i + 1) % 500 == 0:
            print(f"  进度 {i+1}/{total}  命中: {len(trades)}")

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
                for c in ['open', 'high', 'low', 'close']:
                    df[c] = pd.to_numeric(df[c], errors='coerce')
                if 'preClose' in df.columns:
                    df['preClose'] = pd.to_numeric(df['preClose'], errors='coerce')
                dfs.append(df[cols])
            except Exception:
                continue

        if not dfs:
            continue

        df_1d = (pd.concat(dfs).drop_duplicates('date_str')
                 .sort_values('date_str').reset_index(drop=True))

        # 只看12月的行
        df_dec = df_1d[(df_1d['date_str'] >= START_DATE) & (df_1d['date_str'] <= END_DATE)]

        for abs_idx, row in df_dec.iterrows():
            # 取 preClose
            pc = pd.to_numeric(row.get('preClose', None), errors='coerce')
            if pd.isna(pc) or pc <= 0:
                pos = df_1d.index.get_loc(abs_idx)
                if pos > 0:
                    pc = float(df_1d.iloc[pos - 1]['close'])
            if pd.isna(pc) or pc <= 0:
                continue

            # 是否涨停收盘
            lp = round(pc * 1.10, 2)
            c = row['close']
            if pd.isna(c) or abs(c - lp) / lp > 0.005:
                continue

            # 首板：前一日未涨停
            pos = df_1d.index.get_loc(abs_idx)
            if pos == 0:
                continue
            prev = df_1d.iloc[pos - 1]
            prev_c = pd.to_numeric(prev['close'], errors='coerce')
            prev_pc = pd.to_numeric(prev.get('preClose', None), errors='coerce')
            if pd.isna(prev_pc) or prev_pc <= 0:
                if pos >= 2:
                    prev_pc = float(df_1d.iloc[pos - 2]['close'])
            if pd.isna(prev_pc) or prev_pc <= 0:
                continue
            prev_lp = round(prev_pc * 1.10, 2)
            if not pd.isna(prev_c) and abs(prev_c - prev_lp) / prev_lp <= 0.005:
                continue  # 昨日也涨停，非首板

            # 加载1m K线
            date_str = row['date_str']
            day_1m = load_1m(code, date_str)
            if day_1m is None or len(day_1m) == 0:
                continue

            # 封板检测
            limit_thresh = lp * 0.999
            sealed = day_1m['close'] >= limit_thresh

            if not sealed.any():
                continue
            first_seal_idx = sealed.idxmax()
            if not sealed[first_seal_idx]:
                continue
            seal_time = day_1m.at[first_seal_idx, 'time_str']
            if seal_time > SEAL_BEFORE:
                continue

            # 连续封板时长
            seal_end = first_seal_idx
            for j in range(first_seal_idx + 1, len(day_1m)):
                if sealed[j]:
                    seal_end = j
                else:
                    break
            seal_dur = seal_end - first_seal_idx + 1
            if seal_dur < MIN_SEAL:
                continue

            # 开板
            if seal_end + 1 >= len(day_1m):
                continue
            open_idx = None
            for j in range(seal_end + 1, len(day_1m)):
                if not sealed[j]:
                    open_idx = j
                    break
            if open_idx is None:
                continue
            open_time = day_1m.at[open_idx, 'time_str']

            # 回落至买入点
            buy_price = round(pc * (1 + BUY_GAIN_PCT / 100), 3)
            buy_time = None
            for j in range(open_idx, len(day_1m)):
                if day_1m.iloc[j]['low'] <= buy_price:
                    buy_time = day_1m.iloc[j]['time_str']
                    break
            if buy_time is None:
                continue

            close_gain = (c - pc) / pc * 100

            # Day2 数据
            day2_open_pct = None
            day2_close_pct = None
            day2_1m = None
            if pos + 1 < len(df_1d):
                d2 = df_1d.iloc[pos + 1]
                d2_date = d2['date_str']
                d2_pc = pd.to_numeric(d2.get('preClose', None), errors='coerce')
                if pd.isna(d2_pc) or d2_pc <= 0:
                    d2_pc = float(c)
                d2_open = pd.to_numeric(d2['open'], errors='coerce')
                d2_close = pd.to_numeric(d2['close'], errors='coerce')
                if not pd.isna(d2_open):
                    day2_open_pct = round((d2_open - d2_pc) / d2_pc * 100, 2)
                if not pd.isna(d2_close):
                    day2_close_pct = round((d2_close - d2_pc) / d2_pc * 100, 2)
                day2_1m = load_1m(code, d2_date)

            # 策略J卖出
            profit, detail = strategy_j_sell(buy_price, day2_open_pct, day2_1m)

            trades.append(Trade(
                code=code,
                buy_date=date_str,
                buy_price=buy_price,
                pre_close=round(pc, 3),
                buy_time=buy_time,
                seal_time=seal_time,
                seal_min=seal_dur,
                open_time=open_time,
                day1_close_pct=round(close_gain, 2),
                day2_open_pct=day2_open_pct,
                day2_close_pct=day2_close_pct,
                sell_profit=profit,
                sell_detail=detail,
            ))

    print(f"\n✅ 扫描完成，命中 {len(trades)} 笔交易")
    return trades


# ============================================================
# 策略J卖出
# ============================================================
def strategy_j_sell(buy_price: float, open_pct: Optional[float],
                    minute_bars: Optional[pd.DataFrame]) -> Tuple[float, str]:
    """策略J混合最优卖出"""
    if open_pct is None or minute_bars is None or len(minute_bars) == 0:
        return 0.0, '无Day2数据'

    bp = buy_price

    if open_pct > J_HIGH_OPEN:
        # 高开：移动止盈
        return _trailing_stop(minute_bars, bp, J_HIGH_TRAIL, J_HIGH_STOP,
                              f'高开{open_pct:+.1f}%|移动止盈')
    elif open_pct >= J_LOW_OPEN:
        # 平开：分批止盈
        targets = [(J_MID_T1, 0.5), (J_MID_T2, 0.5)]
        return _batch_sell(minute_bars, bp, targets, J_MID_STOP,
                           f'平开{open_pct:+.1f}%|分批')
    else:
        # 低开：快速脱手
        targets = [(J_LOW_TARGET, 1.0)]
        return _batch_sell(minute_bars, bp, targets, J_LOW_STOP,
                           f'低开{open_pct:+.1f}%|快脱')


def _trailing_stop(bars: pd.DataFrame, bp: float,
                   trail_pct: float, stop_pct: float,
                   label: str) -> Tuple[float, str]:
    """移动止盈"""
    peak = bp
    stop_price = bp * (1 + stop_pct / 100)

    for _, r in bars.iterrows():
        t, h, lo = r['time_str'], r['high'], r['low']
        if h > peak:
            peak = h
        if lo <= stop_price:
            return round(stop_pct, 3), f'[{label}] 止损@{t} {stop_pct:+.1f}%'
        if peak > bp * 1.01:
            trail_price = peak * (1 - trail_pct / 100)
            if lo <= trail_price:
                profit = (trail_price - bp) / bp * 100
                peak_g = (peak - bp) / bp * 100
                return round(profit, 3), f'[{label}] 峰{peak_g:+.1f}%→{profit:+.1f}%@{t}'

    # 收盘卖
    last_c = bars.iloc[-1]['close']
    profit = (last_c - bp) / bp * 100
    return round(profit, 3), f'[{label}] 收盘 {profit:+.1f}%'


def _batch_sell(bars: pd.DataFrame, bp: float,
                targets: List[Tuple[float, float]], stop_pct: float,
                label: str) -> Tuple[float, str]:
    """分批止盈"""
    remaining = 1.0
    total_profit = 0.0
    details = []
    t_idx = 0
    stop_price = bp * (1 + stop_pct / 100)

    for _, r in bars.iterrows():
        if remaining <= 0.001:
            break
        t, h, lo = r['time_str'], r['high'], r['low']

        # 止损
        if lo <= stop_price:
            total_profit += stop_pct * remaining
            details.append(f'止损@{t}({remaining:.0%})')
            remaining = 0
            break

        # 止盈
        while t_idx < len(targets) and remaining > 0.001:
            tgt_pct, sell_ratio = targets[t_idx]
            tgt_price = bp * (1 + tgt_pct / 100)
            if h >= tgt_price:
                sell = min(sell_ratio, remaining)
                total_profit += tgt_pct * sell
                remaining -= sell
                details.append(f'+{tgt_pct}%@{t}({sell:.0%})')
                t_idx += 1
            else:
                break

    # 尾盘卖剩余
    if remaining > 0.001:
        last_c = bars.iloc[-1]['close']
        p = (last_c - bp) / bp * 100
        total_profit += p * remaining
        details.append(f'收盘{p:+.1f}%({remaining:.0%})')

    return round(total_profit, 3), f'[{label}] {" | ".join(details)}'


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 70)
    print("🎯 2025年12月 首板策略J回测")
    print(f"   买入: 首板(主板) | {SEAL_BEFORE}前封板≥{MIN_SEAL}分钟 | 开板回落至+{BUY_GAIN_PCT}%")
    print(f"   卖出: 策略J(Day2) | 高开移动止盈 | 平开分批 | 低开快脱")
    print(f"   时间: {START_DATE} ~ {END_DATE}")
    print("=" * 70)

    trades = scan_buy_signals()
    if not trades:
        print("  ⚠️ 无交易信号")
        return

    # 构建 DataFrame
    rows = []
    for t in trades:
        rows.append({
            '股票代码': t.code,
            '涨停日': t.buy_date,
            'preClose': t.pre_close,
            '买入价': t.buy_price,
            '买入时间': t.buy_time,
            '封板时间': t.seal_time,
            '封板(分)': t.seal_min,
            '开板时间': t.open_time,
            'Day1收盘涨(%)': t.day1_close_pct,
            'Day2开盘涨(%)': t.day2_open_pct,
            'Day2收盘涨(%)': t.day2_close_pct,
            '策略J盈亏(%)': t.sell_profit,
            '策略J详情': t.sell_detail,
        })

    df = pd.DataFrame(rows).sort_values(['涨停日', '封板时间']).reset_index(drop=True)

    # 打印交易明细
    print("\n📋 交易明细")
    print("-" * 70)
    pd.set_option('display.width', 300)
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.float_format', '{:.2f}'.format)

    show = ['股票代码', '涨停日', '买入价', '买入时间', '封板时间',
            'Day1收盘涨(%)', 'Day2开盘涨(%)', '策略J盈亏(%)', '策略J详情']
    print(df[show].to_string(index=False))

    # 统计
    pnl = df['策略J盈亏(%)'].dropna()
    if len(pnl) == 0:
        print("  ⚠️ 无有效盈亏数据")
        return

    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0

    print("\n" + "=" * 70)
    print("📊 回测统计")
    print("=" * 70)
    print(f"  交易笔数:   {len(pnl)}")
    print(f"  胜率:       {(pnl > 0).mean() * 100:.1f}%  ({len(wins)} 盈 / {len(losses)} 亏)")
    print(f"  平均盈亏:   {pnl.mean():+.3f}%")
    print(f"  中位盈亏:   {pnl.median():+.3f}%")
    print(f"  最大盈利:   {pnl.max():+.2f}%")
    print(f"  最大亏损:   {pnl.min():+.2f}%")
    print(f"  总收益:     {pnl.sum():+.2f}%")
    if avg_loss != 0:
        print(f"  盈亏比:     {abs(avg_win / avg_loss):.2f}")
    if pnl.std() > 0:
        print(f"  夏普(简):   {pnl.mean() / pnl.std():.3f}")

    # 按开盘分类
    if 'Day2开盘涨(%)' in df.columns:
        print("\n  📈 按Day2开盘分类:")
        for lo, hi, lab in [(-999, -2, '低开(<-2%)'), (-2, 0, '平低(-2%~0%)'),
                            (0, 2, '平高(0%~+2%)'), (2, 999, '高开(>+2%)')]:
            sub = df[(df['Day2开盘涨(%)'] >= lo) & (df['Day2开盘涨(%)'] < hi)]
            if len(sub) == 0:
                continue
            sp = sub['策略J盈亏(%)'].dropna()
            if len(sp) == 0:
                continue
            print(f"    {lab}: {len(sp)}笔  "
                  f"胜率={((sp > 0).mean() * 100):.0f}%  "
                  f"均盈={sp.mean():+.2f}%  "
                  f"总收={sp.sum():+.2f}%")

    print("=" * 70)

    # 保存
    out = os.path.join(OUTPUT_DIR, 'backtest_dec2025_strategyJ.xlsx')
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='交易明细', index=False)
        summary = pd.DataFrame([{
            '总笔数': len(pnl), '盈利': len(wins), '亏损': len(losses),
            '胜率(%)': round((pnl > 0).mean() * 100, 1),
            '均盈亏(%)': round(pnl.mean(), 3),
            '总收益(%)': round(pnl.sum(), 2),
            '盈亏比': round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None,
            '夏普': round(pnl.mean() / pnl.std(), 3) if pnl.std() > 0 else 0,
        }])
        summary.to_excel(w, sheet_name='统计', index=False)

    print(f"\n💾 已保存: {out}")


if __name__ == '__main__':
    main()
