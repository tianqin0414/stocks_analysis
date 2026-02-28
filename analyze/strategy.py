"""
analyze/strategy.py — 策略回测框架

用法:
    python analyze/strategy.py --date 2026-02-13   # 单日回测
    python analyze/strategy.py --start 2026-01-01 --end 2026-02-13  # 区间回测
    python analyze/strategy.py --preset daban      # 使用预设策略
"""
import os
import sys
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import last_trading_day, OUTPUT_DIR
from data_loader import (
    load_snapshot, load_kline, load_klines_batch,
    calc_forward_returns, normalize_code, list_snapshot_dates
)


# ============================================================
#  预设策略
# ============================================================
PRESET_STRATEGIES = {
    # 基础策略：高分 + 非涨停
    'base': {
        'name':      '基础高分策略',
        'conditions': lambda df: (
            (pd.to_numeric(df.get('总分', pd.Series()), errors='coerce') >= 5) &
            (pd.to_numeric(df.get('macd', pd.Series()), errors='coerce') >= 1) &
            (pd.to_numeric(df.get('价格变动 % 1天', pd.Series()), errors='coerce') < 9.8)
        ),
    },

    # 打板策略：昨日高分 + 当日涨停
    'daban': {
        'name':      '打板策略（当日涨停）',
        'conditions': lambda df: (
            (pd.to_numeric(df.get('最高涨幅', pd.Series()), errors='coerce') >= 9.5) &
            (pd.to_numeric(df.get('总分', pd.Series()), errors='coerce') >= 3)
        ),
    },

    # 低位反转：RSI超卖 + 价格回升
    'reversal': {
        'name':      '低位反转策略',
        'conditions': lambda df: (
            (pd.to_numeric(df.get('相对强弱指标（RSI） (14) 1天', pd.Series()), errors='coerce') < 35) &
            (pd.to_numeric(df.get('价格变动 % 1天', pd.Series()), errors='coerce') > 0) &
            (pd.to_numeric(df.get('总分', pd.Series()), errors='coerce') >= 2)
        ),
    },

    # 强势趋势：月线表现好 + RSI健康区间
    'trend': {
        'name':      '强势趋势策略',
        'conditions': lambda df: (
            (pd.to_numeric(df.get('表现 % 1个月', pd.Series()), errors='coerce') > 10) &
            (pd.to_numeric(df.get('相对强弱指标（RSI） (14) 1天', pd.Series()), errors='coerce').between(50, 80)) &
            (pd.to_numeric(df.get('总分', pd.Series()), errors='coerce') >= 4)
        ),
    },
}


# ============================================================
#  单日回测
# ============================================================
def backtest_day(date_str: str, strategy_key: str = 'base',
                 hold_days: int = 3, stop_loss: float = 5.0) -> pd.DataFrame:
    """
    对单日快照筛选买入候选，并用 K 线计算后续收益。

    返回:
        含前向收益的 DataFrame
    """
    strategy = PRESET_STRATEGIES.get(strategy_key)
    if not strategy:
        print(f"  ❌ 未知策略: {strategy_key}  可用: {list(PRESET_STRATEGIES.keys())}")
        return pd.DataFrame()

    # 1. 加载快照 & 筛选
    df = load_snapshot(date_str)
    if df is None or len(df) == 0:
        return pd.DataFrame()

    # 数值列转换
    num_cols = ['总分', 'to13', 'macd', '最高涨幅', '价格变动 % 1天',
                '相对强弱指标（RSI） (14) 1天', '表现 % 1个月', '价格']
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    mask = strategy['conditions'](df)
    candidates = df[mask].copy()

    if len(candidates) == 0:
        print(f"  ⚠️  {date_str}: 无满足条件的股票")
        return pd.DataFrame()

    codes = candidates['证券代码'].tolist()

    # 2. 批量加载 K 线
    klines = load_klines_batch(codes, '1d', show_progress=False)

    # 3. 计算前向收益
    rows = []
    for _, row in candidates.iterrows():
        code = row['证券代码']
        kline = klines.get(code)
        ret = calc_forward_returns(kline, date_str, hold_days, stop_loss_pct=stop_loss)
        r = {
            '证券代码':    code,
            '描述':        row.get('描述', ''),
            '所属行业':    row.get('所属行业', ''),
            '分析日期':    date_str,
            '总分':        row.get('总分'),
            'to13':        row.get('to13'),
            'macd':        row.get('macd'),
            '价格':        row.get('价格'),
            '当日涨幅%':  row.get('价格变动 % 1天'),
            '最高涨幅%':  row.get('最高涨幅'),
        }
        if ret:
            r.update({
                f'最高涨幅_{hold_days}d%':  ret['max_high_pct'],
                f'收盘涨幅_{hold_days}d%':  ret['close_pct'],
                f'止损收益_{hold_days}d%':  ret['stop_pct'],
            })
        rows.append(r)

    return pd.DataFrame(rows)


# ============================================================
#  区间回测
# ============================================================
def backtest_range(start: str, end: str, strategy_key: str = 'base',
                   hold_days: int = 3, stop_loss: float = 5.0) -> pd.DataFrame:
    """对日期区间内所有快照日执行回测，汇总统计结果。"""
    dates = [d for d in list_snapshot_dates()
             if start <= d <= end]
    dates = sorted(dates)

    if not dates:
        print(f"  ⚠️  {start} ~ {end} 范围内无快照数据")
        return pd.DataFrame()

    print(f"  📅 共找到 {len(dates)} 个交易日: {dates[0]} ~ {dates[-1]}")

    all_results = []
    for d in dates:
        day_result = backtest_day(d, strategy_key, hold_days, stop_loss)
        if len(day_result) > 0:
            all_results.append(day_result)

    if not all_results:
        return pd.DataFrame()

    return pd.concat(all_results, ignore_index=True)


# ============================================================
#  统计摘要
# ============================================================
def print_backtest_summary(df: pd.DataFrame, hold_days: int = 3):
    """打印回测统计摘要。"""
    ret_col = f'止损收益_{hold_days}d%'
    max_col = f'最高涨幅_{hold_days}d%'

    if ret_col not in df.columns:
        print("  ⚠️  无前向收益数据（K线缺失）")
        return

    valid = df[df[ret_col].notna()]
    if len(valid) == 0:
        print("  ⚠️  所有条目均无K线数据")
        return

    print(f"\n{'='*55}")
    print(f"  📊 回测摘要  持仓 {hold_days} 天")
    print(f"{'='*55}")
    print(f"  总买入信号: {len(df)}  有效计算: {len(valid)}")

    rets = valid[ret_col]
    win_rate = (rets > 0).mean() * 100
    avg_ret  = rets.mean()
    med_ret  = rets.median()
    max_ret  = rets.max()
    min_ret  = rets.min()

    print(f"  胜率:       {win_rate:.1f}%")
    print(f"  平均收益:   {avg_ret:+.2f}%")
    print(f"  中位收益:   {med_ret:+.2f}%")
    print(f"  最大盈利:   {max_ret:+.2f}%")
    print(f"  最大亏损:   {min_ret:+.2f}%")

    if max_col in valid.columns:
        print(f"  最高涨幅均: {valid[max_col].mean():+.2f}%")

    # 按行业统计
    if '所属行业' in valid.columns:
        ind = (valid.groupby('所属行业')[ret_col]
               .agg(['mean', 'count'])
               .sort_values('mean', ascending=False)
               .head(10))
        print(f"\n  按行业 Top10:")
        for idx, row in ind.iterrows():
            print(f"    {idx:<15}  均收益{row['mean']:+.2f}%  {int(row['count'])}笔")

    print('=' * 55)


def main():
    parser = argparse.ArgumentParser(description='策略回测')
    parser.add_argument('--date',   '-d', default=None, help='单日回测日期')
    parser.add_argument('--start',  default=None, help='区间起始（YYYY-MM-DD）')
    parser.add_argument('--end',    default=None, help='区间结束（YYYY-MM-DD）')
    parser.add_argument('--preset', '-p', default='base',
                        choices=list(PRESET_STRATEGIES.keys()),
                        help=f'预设策略 (默认: base)  可选: {list(PRESET_STRATEGIES.keys())}')
    parser.add_argument('--hold',   type=int,   default=3,   help='持仓天数（默认 3）')
    parser.add_argument('--stop',   type=float, default=5.0, help='止损回撤%（默认 5.0）')
    parser.add_argument('--save',   '-s', action='store_true', help='保存结果到 Excel')
    args = parser.parse_args()

    strategy = PRESET_STRATEGIES[args.preset]
    print(f"🎯 策略: {strategy['name']}")
    print(f"⚙️  持仓 {args.hold} 天 | 止损 {args.stop}%")
    print('=' * 55)

    if args.start and args.end:
        result = backtest_range(args.start, args.end, args.preset, args.hold, args.stop)
    else:
        date_str = args.date or last_trading_day()
        print(f"📅 单日回测: {date_str}")
        result = backtest_day(date_str, args.preset, args.hold, args.stop)
        if len(result) > 0:
            print(f"  筛选出 {len(result)} 只候选股票")

    if len(result) > 0:
        print_backtest_summary(result, args.hold)

        if args.save:
            label = f"{args.start or args.date or last_trading_day()}_{args.preset}"
            path = os.path.join(OUTPUT_DIR, f'backtest_{label}_hold{args.hold}d.xlsx')
            result.to_excel(path, index=False)
            print(f"\n  💾 已保存: {path}")
    else:
        print("  ⚠️  没有回测结果")


if __name__ == '__main__':
    main()
