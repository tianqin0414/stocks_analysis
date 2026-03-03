"""
analyze/kline_stats.py — K线统计分析

用法:
    python analyze/kline_stats.py 000001          # 平安银行日线分析
    python analyze/kline_stats.py 000001 --freq 5m  # 5分钟K线
    python analyze/kline_stats.py --codes 000001 000002 600000  # 多只对比
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import OUTPUT_DIR
from data_loader import load_kline, load_klines_batch, normalize_code


# ============================================================
#  技术指标计算
# ============================================================
def add_ma(df: pd.DataFrame, periods: list[int] = [5, 10, 20, 60]) -> pd.DataFrame:
    """添加均线 MA5/10/20/60。"""
    for p in periods:
        df[f'MA{p}'] = df['close'].rolling(p).mean().round(4)
    return df


def add_rsi(df: pd.DataFrame, periods: list[int] = [6, 14]) -> pd.DataFrame:
    """添加 RSI。"""
    for p in periods:
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(p).mean()
        loss = (-delta.clip(upper=0)).rolling(p).mean()
        rs = gain / loss.replace(0, np.nan)
        df[f'RSI{p}'] = (100 - 100 / (1 + rs)).round(2)
    return df


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    """添加 MACD (12, 26, 9)。"""
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = (ema12 - ema26).round(4)
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean().round(4)
    df['MACD_bar'] = (2 * (df['DIF'] - df['DEA'])).round(4)
    return df


def add_bollinger(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    """添加布林带。"""
    mid = df['close'].rolling(period).mean()
    std = df['close'].rolling(period).std()
    df['BOLL_MID'] = mid.round(4)
    df['BOLL_UP']  = (mid + std_mult * std).round(4)
    df['BOLL_LOW'] = (mid - std_mult * std).round(4)
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """添加 ATR（平均真实波幅）。"""
    if 'preClose' in df.columns:
        prev_close = df['preClose']
    else:
        prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(period).mean().round(4)
    return df


def compute_stats(df: pd.DataFrame) -> pd.DataFrame:
    """计算完整的技术指标集。"""
    df = df.copy()
    df = add_ma(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger(df)
    df = add_atr(df)

    # 涨跌幅
    df['change_pct'] = (df['close'].pct_change() * 100).round(3)
    # 振幅
    df['amplitude']  = ((df['high'] - df['low']) / df['close'].shift(1) * 100).round(3)

    return df


# ============================================================
#  统计摘要
# ============================================================
def summarize(code: str, df: pd.DataFrame, freq: str = '1d'):
    """打印单只股票的统计摘要。"""
    if df is None or len(df) == 0:
        print(f"  ⚠️  {code}: 无数据")
        return

    df = compute_stats(df)
    latest = df.iloc[-1]

    print(f"\n{'='*55}")
    print(f"  📈 {code}  [{freq}]  共 {len(df)} 根K线")
    print(f"  最新: {latest['date_str']}  收盘 {latest['close']:.3f}")
    print(f"{'='*55}")

    # 价格统计
    print(f"  价格区间:  最高 {df['high'].max():.3f} / 最低 {df['low'].min():.3f}")
    print(f"  均线(最新): MA5={latest.get('MA5','N/A'):.3f}  MA10={latest.get('MA10','N/A'):.3f}  MA20={latest.get('MA20','N/A'):.3f}  MA60={latest.get('MA60','N/A'):.3f}")
    print(f"  RSI:        RSI6={latest.get('RSI6','N/A'):.1f}  RSI14={latest.get('RSI14','N/A'):.1f}")
    print(f"  MACD:       DIF={latest.get('DIF','N/A'):.4f}  DEA={latest.get('DEA','N/A'):.4f}  bar={latest.get('MACD_bar','N/A'):.4f}")
    print(f"  布林带:     UP={latest.get('BOLL_UP','N/A'):.3f}  MID={latest.get('BOLL_MID','N/A'):.3f}  LOW={latest.get('BOLL_LOW','N/A'):.3f}")
    print(f"  ATR(14):    {latest.get('ATR','N/A'):.3f}   振幅(最新): {latest.get('amplitude','N/A'):.2f}%")

    # 近N日涨跌统计
    for n in [5, 10, 20]:
        seg = df['change_pct'].dropna().tail(n)
        if len(seg) > 0:
            win = (seg > 0).sum()
            avg = seg.mean()
            print(f"  近{n:3d}日:    上涨{win}/{len(seg)} 天  平均涨跌 {avg:+.2f}%")

    print()


def compare_codes(codes: list[str], freq: str = '1d',
                  metric: str = 'change_pct', tail_n: int = 20):
    """多只股票横向对比（最近 tail_n 根K线的某指标）。"""
    klines = load_klines_batch(codes, freq, show_progress=False)

    data = {}
    for code in codes:
        df = klines.get(code)
        if df is None:
            continue
        df = compute_stats(df)
        data[code] = df[metric].tail(tail_n).values

    dates = None
    for code in codes:
        df = klines.get(code)
        if df is not None:
            dates = df['date_str'].tail(tail_n).tolist()
            break

    if not data:
        print("  ⚠️  所有股票均无数据")
        return

    cmp = pd.DataFrame(data, index=dates or range(tail_n))
    print(f"\n📊 多股对比 [{metric}]，最近 {tail_n} 根K线：")
    print(cmp.tail(10).to_string())


# ============================================================
#  入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='K线统计分析')
    parser.add_argument('codes', nargs='+', help='股票代码（可多只）')
    parser.add_argument('--freq', '-f', default='1d',
                        choices=['1d', '5m', '15m', '30m', '60m'],
                        help='K线频率（默认 1d）')
    parser.add_argument('--compare', '-c', action='store_true',
                        help='多只股票对比模式')
    parser.add_argument('--save', '-s', action='store_true',
                        help='保存带技术指标的 K线到 Excel')
    args = parser.parse_args()

    codes = [normalize_code(c) for c in args.codes]

    if args.compare and len(codes) > 1:
        compare_codes(codes, args.freq)
    else:
        for code in codes:
            df = load_kline(code, args.freq)
            summarize(code, df, args.freq)
            if args.save and df is not None:
                df2 = compute_stats(df)
                path = os.path.join(OUTPUT_DIR, f'{code}_{args.freq}_stats.xlsx')
                df2.to_excel(path, index=False)
                print(f"  💾 已保存: {path}")


if __name__ == '__main__':
    main()
