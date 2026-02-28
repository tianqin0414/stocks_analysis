"""
analyze/param_optimizer.py — 首板策略参数网格搜索优化器

在以下参数范围内进行全量网格搜索，找出盈亏最优的参数组合：
  - buy_gain_pct : 开板回落至 X% 买入（相对 preClose）
  - seal_before  : 封板截止时间（早于此时必须封板）
  - min_seal     : 最短连续封板分钟数
  - exit_mode    : 出场方式（次日收盘 / 当日收盘）

输出：
  1. 控制台实时进度 + 汇总排行榜
  2. output/param_grid_results.xlsx
     - Sheet "排行榜"   : 每组参数的汇总指标，按加权评分排序
     - Sheet "全部明细" : 每笔交易详情，含参数标签

用法:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 \\
        analyze/param_optimizer.py

    # 只测试指定出场方式:
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 \\
        analyze/param_optimizer.py --exit next
"""
from __future__ import annotations

import os
import sys
import argparse
import itertools
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from config import OUTPUT_DIR
# 复用 first_limitup_strategy 的核心回测函数
from analyze.first_limitup_strategy import run_backtest

# ============================================================
# 参数搜索空间（可按需修改）
# ============================================================
PARAM_GRID = {
    # 开板后买入点（涨幅%）
    'buy_gain_pct': [5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 7.9, 8.5, 9.0],
    # 封板截止时间
    'seal_before':  ['09:35', '09:40', '09:45', '09:50', '09:55', '10:00'],
    # 最短连续封板分钟数
    'min_seal':     [15, 20, 30, 45, 60],
    # 出场方式
    'exit_mode':    ['next', 'same'],
}


# ============================================================
# 单组参数的摘要统计
# ============================================================
def summarize(df: pd.DataFrame, params: dict) -> Optional[dict]:
    """从 run_backtest 的结果 DataFrame 提取绩效指标，返回 dict。"""
    if df is None or len(df) == 0:
        return {
            **params,
            '交易笔数': 0,
            '胜率(%)': None,
            '平均盈亏(%)': None,
            '中位盈亏(%)': None,
            '最大盈利(%)': None,
            '最大亏损(%)': None,
            '盈亏比': None,
            '夏普(简)': None,
            '总收益(等权%)': None,
            '评分': -999,
        }

    pnl = df['盈亏(%)'].dropna()
    n = len(pnl)
    if n == 0:
        return {**params, '交易笔数': len(df), '胜率(%)': None,
                '平均盈亏(%)': None, '中位盈亏(%)': None,
                '最大盈利(%)': None, '最大亏损(%)': None,
                '盈亏比': None, '夏普(简)': None, '总收益(等权%)': None, '评分': -999}

    wins    = pnl[pnl > 0]
    losses  = pnl[pnl <= 0]
    avg_win  = wins.mean()  if len(wins)   > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0

    win_rate    = (pnl > 0).mean() * 100
    avg_pnl     = pnl.mean()
    med_pnl     = pnl.median()
    max_pnl     = pnl.max()
    min_pnl     = pnl.min()
    total       = pnl.sum()
    std         = pnl.std() if len(pnl) > 1 else 0
    sharpe      = avg_pnl / std if std > 1e-6 else 0
    # 盈亏比 = 平均盈利 / |平均亏损|
    pnl_ratio   = abs(avg_win / avg_loss) if avg_loss != 0 else float('nan')

    # 综合评分：胜率×0.3 + 平均盈亏×5 + 夏普×2 + log(笔数+1)×1
    # 鼓励：样本量多、胜率高、夏普高、平均盈亏高
    score = (win_rate * 0.3
             + avg_pnl * 5
             + sharpe * 2
             + np.log(n + 1) * 1)

    return {
        **params,
        '交易笔数':      n,
        '胜率(%)':       round(win_rate, 1),
        '平均盈亏(%)':   round(avg_pnl, 3),
        '中位盈亏(%)':   round(med_pnl, 3),
        '最大盈利(%)':   round(max_pnl, 3),
        '最大亏损(%)':   round(min_pnl, 3),
        '盈亏比':        round(pnl_ratio, 2) if not pd.isna(pnl_ratio) else None,
        '夏普(简)':      round(sharpe, 3),
        '总收益(等权%)': round(total, 2),
        '评分':          round(score, 3),
    }


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='首板策略参数优化器')
    parser.add_argument('--exit', default=None, choices=['next', 'same', 'both'],
                        help='限定出场方式（默认 both = 两种都测）')
    parser.add_argument('--sort-by', default='评分',
                        choices=['评分', '平均盈亏(%)', '总收益(等权%)', '胜率(%)', '夏普(简)'],
                        help='排行榜排序依据（默认 评分）')
    parser.add_argument('--top', type=int, default=30,
                        help='显示前N组参数（默认 30）')
    args = parser.parse_args()

    # 构建参数组合
    grid = dict(PARAM_GRID)
    if args.exit == 'next':
        grid['exit_mode'] = ['next']
    elif args.exit == 'same':
        grid['exit_mode'] = ['same']

    keys   = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total  = len(combos)

    print("🔍 参数网格搜索  共 {} 组参数组合".format(total))
    print("   参数空间：")
    for k in keys:
        print("     {}: {}".format(k, grid[k]))
    print("=" * 70)

    summary_rows = []
    all_details: List[pd.DataFrame] = []

    for idx, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        tag = "buy{buy_gain_pct}%_seal{seal_before}_min{min_seal}_{exit_mode}".format(**params)

        if (idx + 1) % 20 == 0 or idx == 0:
            print("  进度 {}/{} …  {}".format(idx + 1, total, tag))

        try:
            df = run_backtest(
                buy_gain_pct=params['buy_gain_pct'],
                exit_mode=params['exit_mode'],
                seal_before=params['seal_before'],
                min_seal=params['min_seal'],
                verbose=False,
            )
        except Exception as e:
            print("  ⚠️  参数 {} 出错: {}".format(tag, e))
            df = pd.DataFrame()

        row = summarize(df, params)
        summary_rows.append(row)

        # 给明细打标签
        if df is not None and len(df) > 0:
            df_copy = df.copy()
            df_copy.insert(0, '参数组', tag)
            all_details.append(df_copy)

    # ---- 排行榜 ----
    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values(args.sort_by, ascending=False).reset_index(drop=True)
    summary_df.index = summary_df.index + 1  # 从1开始排名

    print("\n" + "=" * 70)
    print("🏆 参数排行榜  排序依据：{}  （Top {}）".format(args.sort_by, args.top))
    print("=" * 70)
    pd.set_option('display.width', 280)
    pd.set_option('display.max_columns', 30)
    pd.set_option('display.float_format', '{:.3f}'.format)
    show_cols = ['buy_gain_pct', 'seal_before', 'min_seal', 'exit_mode',
                 '交易笔数', '胜率(%)', '平均盈亏(%)', '中位盈亏(%)',
                 '最大盈利(%)', '最大亏损(%)', '盈亏比', '夏普(简)', '总收益(等权%)', '评分']
    print(summary_df[show_cols].head(args.top).to_string())

    # ---- 保存 Excel ----
    out_path = os.path.join(OUTPUT_DIR, 'param_grid_results.xlsx')
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        summary_df.reset_index().rename(columns={'index': '排名'}).to_excel(
            writer, sheet_name='排行榜', index=False)

        if all_details:
            detail_df = pd.concat(all_details, ignore_index=True)
            detail_df.to_excel(writer, sheet_name='全部明细', index=False)

        # 额外：各参数维度的边际分析
        for col in ['buy_gain_pct', 'seal_before', 'min_seal', 'exit_mode']:
            grp = (summary_df[summary_df['交易笔数'] > 0]
                   .groupby(col)[['平均盈亏(%)', '胜率(%)', '交易笔数', '评分']]
                   .mean()
                   .round(3)
                   .sort_values('评分', ascending=False))
            grp.to_excel(writer, sheet_name='边际_{}'.format(col))

    print("\n💾 已保存: {}".format(out_path))
    print("   Sheets: 排行榜 | 全部明细 | 边际_buy_gain_pct | 边际_seal_before | 边际_min_seal | 边际_exit_mode")


if __name__ == '__main__':
    main()
