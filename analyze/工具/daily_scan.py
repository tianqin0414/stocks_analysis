"""
analyze/daily_scan.py — 每日选股扫描（基于原始 TradingView 快照格式）

用法:
    python analyze/daily_scan.py                     # 扫描最近一个交易日
    python analyze/daily_scan.py --date 2026-02-13   # 扫描指定日期
    python analyze/daily_scan.py --top 30            # 输出前30只
    python analyze/daily_scan.py --rsi-min 60        # RSI下限
    python analyze/daily_scan.py --save              # 保存结果到 Excel
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config import last_trading_day, OUTPUT_DIR
from data_loader import load_snapshot

# ============================================================
#  列名常量（TradingView 导出格式）
# ============================================================
RSI_COL    = '相对强弱指标（RSI） (14) 1天'
CHANGE_COL = '价格变动 % 1天'
VOL_COL    = '相对成交量(Relative Vol) 1天'
TECH_COL   = '技术评级 1天'

# ============================================================
#  默认筛选条件
# ============================================================
SCAN_CONFIG = {
    'rsi_min':         50.0,  # RSI(14) 下限（偏强）
    'rsi_max':         85.0,  # RSI(14) 上限（未超买）
    'min_change_pct':   1.0,  # 当日涨幅下限（%）
    'max_change_pct':   9.5,  # 当日涨幅上限（排除涨停）
    'min_price':        3.0,  # 最低价格（元）
    'max_price':      200.0,  # 最高价格（元）
    'min_rel_vol':      1.5,  # 最低相对成交量倍数（放量）
    'exclude_st':       True, # 排除 ST 股
    'tech_rating_1d':  '买入', # 技术评级：'买入' | '强烈买入' | None(不限)
}


def scan_day(date_str: str, config: dict = None) -> pd.DataFrame:
    """
    对单日快照执行选股扫描（TradingView 原始格式）。

    返回: 满足条件的 DataFrame（按涨幅降序）
    """
    cfg = config or SCAN_CONFIG
    df = load_snapshot(date_str)
    if df is None or len(df) == 0:
        return pd.DataFrame()

    if '证券代码' not in df.columns:
        print("  ✗ 快照无证券代码列（商品代码映射失败）")
        return pd.DataFrame()

    # 排除 ST
    if cfg.get('exclude_st') and '描述' in df.columns:
        df = df[~df['描述'].astype(str).str.contains(r'\bST\b|\*ST', na=False)]

    # 数值转换
    for col in [RSI_COL, CHANGE_COL, VOL_COL, '价格']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    mask = pd.Series(True, index=df.index)

    if RSI_COL in df.columns:
        mask &= df[RSI_COL] >= cfg['rsi_min']
        mask &= df[RSI_COL] <= cfg['rsi_max']

    if CHANGE_COL in df.columns:
        mask &= df[CHANGE_COL] >= cfg['min_change_pct']
        mask &= df[CHANGE_COL] <  cfg['max_change_pct']

    if '价格' in df.columns:
        mask &= df['价格'] >= cfg['min_price']
        mask &= df['价格'] <= cfg['max_price']

    if VOL_COL in df.columns and cfg.get('min_rel_vol'):
        mask &= df[VOL_COL] >= cfg['min_rel_vol']

    if TECH_COL in df.columns and cfg.get('tech_rating_1d'):
        wanted = cfg['tech_rating_1d']
        ratings = ['买入', '强烈买入'] if wanted == '买入' else [wanted]
        mask &= df[TECH_COL].isin(ratings)

    result = df[mask].copy()

    sort_cols = [c for c in [CHANGE_COL, RSI_COL] if c in result.columns]
    if sort_cols:
        result = result.sort_values(sort_cols, ascending=False)

    return result.reset_index(drop=True)


def print_scan_result(df: pd.DataFrame, top_n: int = 20):
    """格式化打印选股结果。"""
    if len(df) == 0:
        print("  ⚠️  没有满足条件的股票")
        return

    print(f"\n  ✅ 共 {len(df)} 只，显示前 {min(top_n, len(df))} 只：\n")

    display_cols = ['证券代码', '描述', '价格', CHANGE_COL, RSI_COL,
                    VOL_COL, TECH_COL, '最高涨幅', '板块']
    display_cols = [c for c in display_cols if c in df.columns]

    sub = df[display_cols].head(top_n).rename(columns={
        CHANGE_COL: '涨幅%',
        RSI_COL:    'RSI14',
        VOL_COL:    '相对量',
        TECH_COL:   '评级',
    })

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 220)
    pd.set_option('display.float_format', '{:.2f}'.format)
    print(sub.to_string(index=False))


def save_result(df: pd.DataFrame, date_str: str):
    if len(df) == 0:
        return
    path = os.path.join(OUTPUT_DIR, f'{date_str}_daily_scan.xlsx')
    df.to_excel(path, index=False)
    print(f"\n  💾 已保存: {path}")


def main():
    parser = argparse.ArgumentParser(description='每日选股扫描')
    parser.add_argument('--date',    '-d', default=None,
                        help='分析日期 (YYYY-MM-DD)，默认最近交易日')
    parser.add_argument('--top',     '-n', type=int, default=20,
                        help='显示前 N 只（默认 20）')
    parser.add_argument('--rsi-min', type=float, default=SCAN_CONFIG['rsi_min'],
                        help=f'RSI 下限（默认 {SCAN_CONFIG["rsi_min"]}）')
    parser.add_argument('--rsi-max', type=float, default=SCAN_CONFIG['rsi_max'],
                        help=f'RSI 上限（默认 {SCAN_CONFIG["rsi_max"]}）')
    parser.add_argument('--min-change', type=float, default=SCAN_CONFIG['min_change_pct'],
                        help=f'最低涨幅%（默认 {SCAN_CONFIG["min_change_pct"]}）')
    parser.add_argument('--no-rating', action='store_true',
                        help='不过滤技术评级')
    parser.add_argument('--save',    '-s', action='store_true', help='保存 Excel')
    args = parser.parse_args()

    date_str = args.date or last_trading_day()
    print(f"📅 扫描日期: {date_str}")
    print(f"🔍 条件: RSI {args.rsi_min}~{args.rsi_max}, 涨幅≥{args.min_change}%, 放量≥{SCAN_CONFIG['min_rel_vol']}x")
    print("=" * 60)

    cfg = {
        **SCAN_CONFIG,
        'rsi_min':        args.rsi_min,
        'rsi_max':        args.rsi_max,
        'min_change_pct': args.min_change,
        'tech_rating_1d': None if args.no_rating else SCAN_CONFIG['tech_rating_1d'],
    }

    result = scan_day(date_str, cfg)
    print_scan_result(result, args.top)

    if args.save:
        save_result(result, date_str)


if __name__ == '__main__':
    main()
