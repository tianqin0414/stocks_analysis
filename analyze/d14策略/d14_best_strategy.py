"""
D14最优策略 — 稳定型A
======================
条件: 20%板 + 开盘3-5% + 前日涨0-5% + 9:32-9:50首笔 + S8(18%止盈2%止损)
回测结果: 月均+8.33%, Sharpe=3.95, MaxDD=-4.66%, 年化155%

Usage:
    python analyze/d14_best_strategy.py              # 完整回测
    python analyze/d14_best_strategy.py --today       # 今日信号筛选
"""
import os
import sys
import argparse
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# 确保项目路径
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
from data_loader import load_kline, load_klines_batch, normalize_code, _build_kline_index

# ============================================================
#  策略参数
# ============================================================
STRATEGY_PARAMS = {
    'name': '稳定型A: D14+S8',
    'description': '20%板+开盘3-5%+前日涨0-5%+9:32-9:50首笔+18%止盈2%止损',

    # 进场条件
    'board': '20%板',          # 只做20%涨停板
    'open_pct_min': 3.0,       # 开盘涨幅下限(%)
    'open_pct_max': 5.0,       # 开盘涨幅上限(%)
    'prev_day_min': 0.0,       # 前一日涨幅下限(%)
    'prev_day_max': 5.0,       # 前一日涨幅上限(%)
    'buy_time_start': '09:32', # 买入时间窗口开始
    'buy_time_end': '09:50',   # 买入时间窗口结束
    'max_trades_per_day': 1,   # 每天最多做几笔
    'exclude_new_stock': True, # 排除新股(开盘涨幅>20%)

    # 出场规则
    'exit_strategy': 'S8',     # S8 = 目标18%止盈, 2%止损
    'target_pct': 18.0,        # 止盈目标(相对preClose的涨幅%)
    'stop_loss_pct': 2.0,      # 止损幅度(相对买入价%)

    # 成本
    'commission': 0.1,         # 手续费(%)
    'slippage': 0.1,           # 滑点(%)

    # 盈亏计算
    'buy_ratio': 1.14,         # 买入价 = preClose × 1.14
    'target_gain': 3.51,       # 命中止盈: +3.51% (18%/1.14-1)
    'stop_loss': -2.00,        # 命中止损: -2.00%
}

COST = STRATEGY_PARAMS['commission'] + STRATEGY_PARAMS['slippage']


# ============================================================
#  获取前一日涨幅
# ============================================================
def get_prev_day_changes(codes, dates, klines_cache=None):
    """
    批量获取前一日涨幅
    
    Args:
        codes: 股票代码列表 (6位字符串)
        dates: 日期列表 (YYYYMMDD字符串)
        klines_cache: 预加载的K线缓存 {code: DataFrame}
    
    Returns:
        dict: {(code, date): prev_change_pct}
    """
    if klines_cache is None:
        unique_codes = list(set(codes))
        klines_cache = load_klines_batch(unique_codes, freq='1d', show_progress=False)

    result = {}
    for code, date_str in zip(codes, dates):
        kl = klines_cache.get(code)
        if kl is None:
            result[(code, date_str)] = None
            continue
        
        idx_arr = kl.index[kl['date_str'] == date_str].tolist()
        if not idx_arr or idx_arr[0] == 0:
            result[(code, date_str)] = None
            continue
        
        idx = idx_arr[0]
        prev = kl.iloc[idx - 1]
        if 'preClose' in kl.columns and prev['preClose'] > 0:
            result[(code, date_str)] = (prev['close'] - prev['preClose']) / prev['preClose'] * 100
        else:
            result[(code, date_str)] = None

    return result


# ============================================================
#  回测主函数
# ============================================================
def run_backtest(data_path=None, params=None):
    """
    运行D14策略回测
    
    Args:
        data_path: d14_full_backtest.xlsx 路径
        params: 策略参数字典 (默认使用STRATEGY_PARAMS)
    
    Returns:
        dict: 回测结果
    """
    if params is None:
        params = STRATEGY_PARAMS
    if data_path is None:
        data_path = os.path.join(PROJECT_DIR, 'output', 'd14_full_backtest.xlsx')

    print(f'📊 加载数据: {data_path}')
    df = pd.read_excel(data_path)
    
    # 解析买入时间
    df['buy_minute'] = (
        pd.to_datetime(df['买入时间'], format='%H:%M').dt.hour * 60 +
        pd.to_datetime(df['买入时间'], format='%H:%M').dt.minute
    )
    
    # 排除新股
    if params.get('exclude_new_stock', True):
        before = len(df)
        df = df[df['开盘涨幅%'] <= 20].copy()
        print(f'  排除新股: {before} → {len(df)} (-{before-len(df)})')
    
    # 基础条件: 20%板
    df = df[df['板块'] == params['board']].copy()
    print(f'  {params["board"]}筛选: {len(df)}笔')
    
    # 时间窗口
    t_start = int(params['buy_time_start'].replace(':', ''))
    t_end = int(params['buy_time_end'].replace(':', ''))
    start_min = (t_start // 100) * 60 + (t_start % 100)
    end_min = (t_end // 100) * 60 + (t_end % 100)
    df = df[(df['buy_minute'] >= start_min) & (df['buy_minute'] < end_min)].copy()
    print(f'  时间窗口 {params["buy_time_start"]}-{params["buy_time_end"]}: {len(df)}笔')
    
    # 开盘涨幅
    df = df[
        (df['开盘涨幅%'] >= params['open_pct_min']) & 
        (df['开盘涨幅%'] < params['open_pct_max'])
    ].copy()
    print(f'  开盘涨幅 {params["open_pct_min"]}-{params["open_pct_max"]}%: {len(df)}笔')
    
    # 获取前一日涨幅
    print('  获取前一日涨幅...')
    _build_kline_index('1d')
    codes = df['股票代码'].astype(str).str.zfill(6).tolist()
    dates = df['日期'].astype(str).tolist()
    prev_changes = get_prev_day_changes(codes, dates)
    df['code_str'] = df['股票代码'].astype(str).str.zfill(6)
    df['date_str'] = df['日期'].astype(str)
    df['前一日涨幅%'] = df.apply(
        lambda r: prev_changes.get((r['code_str'], r['date_str'])), axis=1
    )
    
    # 前一日涨幅筛选
    df = df[
        (df['前一日涨幅%'] >= params['prev_day_min']) & 
        (df['前一日涨幅%'] < params['prev_day_max'])
    ].copy()
    print(f'  前一日涨幅 {params["prev_day_min"]}-{params["prev_day_max"]}%: {len(df)}笔')
    
    # 每天取最早的N笔
    max_t = params['max_trades_per_day']
    df = df.sort_values(['日期', 'buy_minute'])
    df = df.groupby('日期').head(max_t).reset_index(drop=True)
    print(f'  每日最多{max_t}笔: {len(df)}笔')
    
    # 策略列
    exit_col = f'S{params["exit_strategy"][1:]}_目标{int(params["target_pct"])}%_止损{int(params["stop_loss_pct"])}%'
    if exit_col not in df.columns:
        # 尝试匹配
        for c in df.columns:
            if params['exit_strategy'] in c:
                exit_col = c
                break
    
    print(f'  出场策略列: {exit_col}')
    df['净收益%'] = df[exit_col] - COST
    
    # ============================================================
    #  月度统计
    # ============================================================
    monthly_results = []
    for month in sorted(df['月份'].unique()):
        ms = df[df['月份'] == month]
        daily = ms.groupby('日期')['净收益%'].mean()
        cum_ret = ((1 + daily / 100).prod() - 1) * 100
        
        monthly_results.append({
            '月份': month,
            '交易天数': len(daily),
            '交易笔数': len(ms),
            '单笔均收益%': round(ms['净收益%'].mean(), 3),
            '胜率': round((ms['净收益%'] > 0).mean(), 3),
            '月复利收益%': round(cum_ret, 2),
        })
    
    mdf = pd.DataFrame(monthly_results)
    complete = mdf[mdf['月份'] != mdf['月份'].max()]  # 排除最后不完整月
    m_rets = complete['月复利收益%'].values
    
    # 风险指标
    cum_nav = np.cumprod([1 + r / 100 for r in m_rets])
    peak_nav = np.maximum.accumulate(cum_nav)
    drawdowns = (cum_nav - peak_nav) / peak_nav * 100
    
    sharpe = (m_rets.mean() / (m_rets.std(ddof=1) + 1e-9) * np.sqrt(12)) if len(m_rets) > 1 else 0
    
    summary = {
        'strategy': params['name'],
        'description': params['description'],
        'total_trades': len(df),
        'complete_months': len(complete),
        'monthly_avg_trades': round(complete['交易笔数'].mean(), 1),
        'avg_ret_per_trade': round(complete['单笔均收益%'].mean(), 3),
        'avg_win_rate': round(complete['胜率'].mean(), 3),
        'monthly_mean': round(m_rets.mean(), 2),
        'monthly_median': round(np.median(m_rets), 2),
        'monthly_min': round(m_rets.min(), 2),
        'monthly_max': round(m_rets.max(), 2),
        'positive_months': int((m_rets > 0).sum()),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(drawdowns.min(), 2),
        'annual_return': round((cum_nav[-1] - 1) * 100, 1),
        'final_nav': round(cum_nav[-1], 4),
    }
    
    return {
        'summary': summary,
        'monthly': mdf,
        'trades': df,
        'params': params,
    }


# ============================================================
#  打印报告
# ============================================================
def print_report(result):
    """打印回测结果"""
    s = result['summary']
    m = result['monthly']
    
    print(f'\n{"="*60}')
    print(f'📈 {s["strategy"]}')
    print(f'   {s["description"]}')
    print(f'{"="*60}')
    
    print(f'\n📊 概要:')
    print(f'  总交易笔数: {s["total_trades"]}')
    print(f'  完整月份数: {s["complete_months"]}')
    print(f'  月均交易笔数: {s["monthly_avg_trades"]}')
    print(f'  单笔均收益: {s["avg_ret_per_trade"]:+.3f}%')
    print(f'  单笔胜率: {s["avg_win_rate"]:.1%}')
    
    print(f'\n💰 收益:')
    print(f'  月均收益: {s["monthly_mean"]:+.2f}%')
    print(f'  月中位收益: {s["monthly_median"]:+.2f}%')
    print(f'  最差月: {s["monthly_min"]:+.2f}%')
    print(f'  最好月: {s["monthly_max"]:+.2f}%')
    print(f'  盈利月: {s["positive_months"]}/{s["complete_months"]}')
    print(f'  年化收益: {s["annual_return"]:+.1f}%')
    
    print(f'\n⚠️ 风险:')
    print(f'  夏普比率: {s["sharpe"]:.2f}')
    print(f'  最大回撤: {s["max_drawdown"]:+.2f}%')
    
    print(f'\n📅 月度明细:')
    print(m.to_string(index=False))
    
    # 净值曲线
    complete = m[m['月份'] != m['月份'].max()]
    cum = np.cumprod([1 + r / 100 for r in complete['月复利收益%']])
    print(f'\n💹 净值曲线:')
    for i, (_, row) in enumerate(complete.iterrows()):
        bar = '█' * int(cum[i] * 10)
        print(f'  {row["月份"]}: {cum[i]:.4f} {bar}')


# ============================================================
#  参数敏感性分析
# ============================================================
def sensitivity_analysis(data_path=None):
    """测试不同参数组合的稳健性"""
    print('\n📐 参数敏感性分析')
    print('='*80)
    
    base_params = STRATEGY_PARAMS.copy()
    
    variations = [
        ('开盘2-5%', {'open_pct_min': 2.0, 'open_pct_max': 5.0}),
        ('开盘3-5%（默认）', {'open_pct_min': 3.0, 'open_pct_max': 5.0}),
        ('开盘3-8%', {'open_pct_min': 3.0, 'open_pct_max': 8.0}),
        ('开盘2-8%', {'open_pct_min': 2.0, 'open_pct_max': 8.0}),
        ('前日-5~5%', {'prev_day_min': -5.0, 'prev_day_max': 5.0}),
        ('前日0-5%（默认）', {'prev_day_min': 0.0, 'prev_day_max': 5.0}),
        ('前日<5%', {'prev_day_min': -999.0, 'prev_day_max': 5.0}),
        ('前日<10%', {'prev_day_min': -999.0, 'prev_day_max': 10.0}),
        ('时间9:32-9:40', {'buy_time_start': '09:32', 'buy_time_end': '09:40'}),
        ('时间9:32-9:50（默认）', {'buy_time_start': '09:32', 'buy_time_end': '09:50'}),
        ('时间9:32-10:00', {'buy_time_start': '09:32', 'buy_time_end': '10:00'}),
        ('每日1笔（默认）', {'max_trades_per_day': 1}),
        ('每日2笔', {'max_trades_per_day': 2}),
        ('每日3笔', {'max_trades_per_day': 3}),
    ]
    
    results = []
    for v_name, v_params in variations:
        p = base_params.copy()
        p.update(v_params)
        r = run_backtest(data_path, p)
        s = r['summary']
        results.append({
            '变体': v_name,
            '笔数': s['total_trades'],
            '月均%': s['monthly_mean'],
            '最差月%': s['monthly_min'],
            'Sharpe': s['sharpe'],
            'MaxDD%': s['max_drawdown'],
        })
    
    rdf = pd.DataFrame(results)
    print(rdf.to_string(index=False))


# ============================================================
#  主入口
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='D14最优策略回测')
    parser.add_argument('--sensitivity', action='store_true', help='运行参数敏感性分析')
    parser.add_argument('--data', type=str, default=None, help='数据文件路径')
    args = parser.parse_args()
    
    data_path = args.data or os.path.join(PROJECT_DIR, 'output', 'd14_full_backtest.xlsx')
    
    if args.sensitivity:
        sensitivity_analysis(data_path)
    else:
        result = run_backtest(data_path)
        print_report(result)
        
        # 保存结果
        output_path = os.path.join(PROJECT_DIR, 'output', 'best_strategy_result.xlsx')
        result['trades'].to_excel(output_path, index=False)
        print(f'\n💾 交易明细已保存: {output_path}')
