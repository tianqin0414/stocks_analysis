#!/usr/bin/env python3
"""
淘股吧6位高手交易策略深度研究
=================================
分析维度：A.选股特征 B.持仓策略 C.卖出时机 D.收益归因 E.可量化复制性评估
"""

import sys
import os
import warnings
import re
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')

PROJECT_ROOT = '/Users/tq/PycharmProjects/stocks_analysis'
sys.path.insert(0, PROJECT_ROOT)
from data_loader import load_kline, normalize_code

OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
BATCH_DIR = os.path.join(OUTPUT_DIR, 'tgb_batch')

# ============================================================
#  工具函数
# ============================================================

def parse_amount(val):
    """解析金额字段: '8.61万元' -> 86100, '--' -> NaN"""
    if pd.isna(val) or val == '--' or val == '':
        return np.nan
    val = str(val).replace('元', '').strip()
    if '万' in val:
        return float(val.replace('万', '')) * 10000
    return float(val)

def parse_quantity(val):
    """解析数量字段: '1.88万' -> 18800, '8400' -> 8400"""
    if pd.isna(val) or val == '--' or val == '':
        return np.nan
    val = str(val).strip()
    if '万' in val:
        return float(val.replace('万', '')) * 10000
    return float(val)

def clean_code(code_raw):
    """清理股票代码: 600580.0 -> '600580'"""
    s = str(code_raw).split('.')[0]
    return s.zfill(6)

def is_gem_or_star(code):
    """判断是否创业板(300)/科创板(688) -> 20%涨跌幅"""
    return code.startswith('300') or code.startswith('688')

def get_limit_pct(code):
    """获取涨跌幅限制"""
    return 20 if is_gem_or_star(code) else 10


# ============================================================
#  K线数据缓存
# ============================================================
_kline_cache = {}

def get_kline(code):
    """获取K线数据，带缓存"""
    code = normalize_code(code)
    if code not in _kline_cache:
        df = load_kline(code, '1d')
        if df is not None and len(df) > 0:
            df = df.sort_values('date_str').reset_index(drop=True)
            _kline_cache[code] = df
        else:
            _kline_cache[code] = None
    return _kline_cache[code]


def get_prev_day_info(code, buy_date_str):
    """
    获取买入日的行情信息：
    - prev_close_chg: 前一日涨幅%
    - open_chg: 买入日开盘涨幅%
    - high_chg: 买入日最高涨幅%
    - prev_close: 前一日收盘价
    """
    kdf = get_kline(code)
    if kdf is None:
        return {}
    
    # 标准化日期格式
    buy_date = buy_date_str.replace('-', '')
    
    idx = kdf[kdf['date_str'] == buy_date].index
    if len(idx) == 0:
        return {}
    
    i = idx[0]
    if i < 1:
        return {}
    
    result = {}
    
    # 前一日涨幅
    if 'preClose' in kdf.columns:
        prev_preclose = kdf.iloc[i-1].get('preClose', None)
    else:
        prev_preclose = kdf.iloc[i-2]['close'] if i >= 2 else None
    
    prev_close = kdf.iloc[i-1]['close']
    buy_open = kdf.iloc[i]['open']
    buy_high = kdf.iloc[i]['high']
    buy_close = kdf.iloc[i]['close']
    
    # 前一日涨幅 = (前一日close - 前前日close) / 前前日close
    if i >= 2:
        prev_prev_close = kdf.iloc[i-2]['close']
        result['prev_close_chg'] = (prev_close - prev_prev_close) / prev_prev_close * 100
    elif 'preClose' in kdf.columns:
        pc = kdf.iloc[i-1].get('preClose', None)
        if pc and pc > 0:
            result['prev_close_chg'] = (prev_close - pc) / pc * 100
    
    # 买入日开盘涨幅 = (开盘 - 前日close) / 前日close
    if prev_close > 0:
        result['open_chg'] = (buy_open - prev_close) / prev_close * 100
        result['high_chg'] = (buy_high - prev_close) / prev_close * 100
        result['close_chg'] = (buy_close - prev_close) / prev_close * 100
    
    result['prev_close'] = prev_close
    
    return result


# ============================================================
#  数据加载
# ============================================================

def load_zhihe_data():
    """加载只核大学生的买卖记录（专有格式）"""
    path = os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_买卖记录.csv')
    df = pd.read_csv(path, encoding='utf-8-sig')
    df['股票代码'] = df['股票代码'].apply(clean_code)
    return df

def load_zhihe_holdings():
    """加载只核大学生的持仓明细"""
    path = os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_持仓明细.csv')
    df = pd.read_csv(path, encoding='utf-8-sig')
    df['股票代码'] = df['股票代码'].apply(clean_code)
    df['日期'] = df['日期'].astype(str)
    return df

def load_zhihe_revenue():
    """加载只核大学生的收益明细"""
    path = os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_收益明细.csv')
    df = pd.read_csv(path, encoding='utf-8-sig')
    return df

def load_batch_holdings(name, match_id):
    """加载批量高手持仓明细"""
    path = os.path.join(BATCH_DIR, f'{name}_比赛{match_id}_持仓明细.csv')
    df = pd.read_csv(path, encoding='utf-8-sig')
    df['股票代码'] = df['股票代码'].apply(clean_code)
    df['日期'] = df['日期'].astype(str)
    # 解析金额和数量
    if '金额(元)' in df.columns:
        df['金额_num'] = df['金额(元)'].apply(parse_amount)
    elif '金额' in df.columns:
        df['金额_num'] = df['金额'].apply(parse_amount)
    if '数量(股)' in df.columns:
        df['数量_num'] = df['数量(股)'].apply(parse_quantity)
    elif '数量' in df.columns:
        df['数量_num'] = df['数量'].apply(parse_quantity)
    return df

def load_batch_revenue(name, match_id):
    """加载批量高手收益明细"""
    path = os.path.join(BATCH_DIR, f'{name}_比赛{match_id}_收益明细.csv')
    df = pd.read_csv(path, encoding='utf-8-sig')
    return df


def infer_trades_from_holdings(holdings_df, revenue_df):
    """
    从持仓明细推断买卖记录
    逻辑：如果某股票今天出现在持仓中、昨天没有 -> 买入
          如果某股票今天不在持仓中、昨天有 -> 卖出
    """
    holdings_df = holdings_df.copy()
    revenue_df = revenue_df.copy()
    
    # 获取所有交易日（时间排序）
    dates = sorted(holdings_df['日期'].unique())
    
    # 构建每日持仓dict: date -> set of codes
    daily_holdings = {}
    for d in dates:
        day_df = holdings_df[holdings_df['日期'] == d]
        # 过滤掉金额为0的（可能是已卖出但还在列表中）
        if '金额_num' in day_df.columns:
            valid = day_df[(day_df['金额_num'] > 0) | (day_df['金额_num'].isna())]
            codes = set(valid['股票代码'].unique())
        else:
            codes = set(day_df['股票代码'].unique())
        daily_holdings[d] = codes
    
    # 也获取revenue中的每日持仓信息
    rev_daily_holdings = {}
    for _, row in revenue_df.iterrows():
        d = str(int(row['日期'])) if not isinstance(row['日期'], str) else str(row['日期'])
        codes_str = str(row.get('持股代码', ''))
        if codes_str and codes_str != 'nan':
            codes = set(clean_code(c.strip()) for c in codes_str.split(',') if c.strip())
            rev_daily_holdings[d] = codes
    
    # 合并：优先用revenue的持仓代码（更准确）
    all_dates = sorted(set(list(daily_holdings.keys()) + list(rev_daily_holdings.keys())))
    
    merged_holdings = {}
    for d in all_dates:
        if d in rev_daily_holdings:
            merged_holdings[d] = rev_daily_holdings[d]
        elif d in daily_holdings:
            merged_holdings[d] = daily_holdings[d]
        else:
            merged_holdings[d] = set()
    
    all_dates = sorted(merged_holdings.keys())
    
    trades = []
    active_positions = {}  # code -> buy_date
    
    for i, d in enumerate(all_dates):
        current_codes = merged_holdings[d]
        prev_codes = merged_holdings[all_dates[i-1]] if i > 0 else set()
        
        # 新买入
        for code in current_codes - prev_codes:
            # 找名称
            name_match = holdings_df[holdings_df['股票代码'] == code]['股票名称']
            name = name_match.iloc[0] if len(name_match) > 0 else code
            active_positions[code] = d
            trades.append({
                '操作': '买入',
                '日期': d,
                '股票代码': code,
                '股票名称': name,
            })
        
        # 卖出
        for code in prev_codes - current_codes:
            buy_date = active_positions.pop(code, None)
            name_match = holdings_df[holdings_df['股票代码'] == code]['股票名称']
            name = name_match.iloc[0] if len(name_match) > 0 else code
            
            # 计算持仓天数
            if buy_date:
                buy_idx = all_dates.index(buy_date) if buy_date in all_dates else None
                sell_idx = i
                hold_days = sell_idx - (buy_idx if buy_idx is not None else sell_idx) 
            else:
                hold_days = 0
            
            trades.append({
                '操作': '卖出',
                '日期': d,
                '股票代码': code,
                '股票名称': name,
                '买入日期': buy_date,
                '持仓天数': hold_days,
            })
    
    return pd.DataFrame(trades)


def compute_trade_returns(trades_df, holdings_df=None):
    """
    使用K线数据计算每笔交易的收益
    """
    results = []
    
    sells = trades_df[trades_df['操作'] == '卖出'].copy()
    
    for _, row in sells.iterrows():
        code = row['股票代码']
        buy_date = str(row.get('买入日期', '')).replace('-', '')
        sell_date = str(row['日期']).replace('-', '')
        hold_days = row.get('持仓天数', 0)
        
        if not buy_date or buy_date == 'nan' or buy_date == 'None':
            continue
        
        kdf = get_kline(code)
        if kdf is None:
            continue
        
        buy_rows = kdf[kdf['date_str'] == buy_date]
        sell_rows = kdf[kdf['date_str'] == sell_date]
        
        if len(buy_rows) == 0 or len(sell_rows) == 0:
            continue
        
        buy_open = buy_rows.iloc[0]['open']
        sell_open = sell_rows.iloc[0]['open']
        
        # 假设买入日以开盘价买入，卖出日以开盘价卖出
        ret = (sell_open - buy_open) / buy_open * 100
        ret_net = ret - 0.15  # 扣手续费
        
        results.append({
            '股票代码': code,
            '股票名称': row.get('股票名称', ''),
            '买入日期': buy_date,
            '卖出日期': sell_date,
            '持仓天数': hold_days,
            '买入价': buy_open,
            '卖出价': sell_open,
            '收益%': round(ret_net, 2),
        })
    
    return pd.DataFrame(results) if results else pd.DataFrame()


# ============================================================
#  分析函数
# ============================================================

def analyze_selection(trades_with_kline, master_name):
    """A. 选股特征分析"""
    report = []
    report.append(f"\n### A. 选股特征分析\n")
    
    buys = trades_with_kline[trades_with_kline['操作'] == '买入'].copy()
    
    if len(buys) == 0:
        report.append("无买入数据\n")
        return '\n'.join(report), buys
    
    # 获取K线信息
    prev_chgs = []
    open_chgs = []
    high_chgs = []
    codes = []
    names = []
    buy_dates = []
    board_types = []
    
    for _, row in buys.iterrows():
        code = row['股票代码']
        buy_date = str(row['日期']).replace('-', '')
        info = get_prev_day_info(code, buy_date)
        
        prev_chgs.append(info.get('prev_close_chg', np.nan))
        open_chgs.append(info.get('open_chg', np.nan))
        high_chgs.append(info.get('high_chg', np.nan))
        codes.append(code)
        names.append(row.get('股票名称', ''))
        buy_dates.append(buy_date)
        board_types.append('20%板' if is_gem_or_star(code) else '10%板')
    
    buys = buys.copy()
    buys['前日涨幅'] = prev_chgs
    buys['开盘涨幅'] = open_chgs
    buys['最高涨幅'] = high_chgs
    buys['板块类型'] = board_types
    
    valid_prev = buys.dropna(subset=['前日涨幅'])
    
    # 1. 前一日涨幅分布
    report.append("#### 1. 前一日涨幅分布\n")
    if len(valid_prev) > 0:
        bins = {
            '涨停追板(>8%)': len(valid_prev[valid_prev['前日涨幅'] > 8]),
            '追大涨(5~8%)': len(valid_prev[(valid_prev['前日涨幅'] > 5) & (valid_prev['前日涨幅'] <= 8)]),
            '小涨(0~5%)': len(valid_prev[(valid_prev['前日涨幅'] >= 0) & (valid_prev['前日涨幅'] <= 5)]),
            '低吸(<0%)': len(valid_prev[valid_prev['前日涨幅'] < 0]),
        }
        total = len(valid_prev)
        report.append("| 类型 | 笔数 | 占比 |")
        report.append("|------|------|------|")
        for k, v in bins.items():
            report.append(f"| {k} | {v} | {v/total*100:.1f}% |")
        report.append(f"| **合计** | **{total}** | **100%** |")
        report.append(f"\n前日涨幅均值: {valid_prev['前日涨幅'].mean():.2f}%, 中位数: {valid_prev['前日涨幅'].median():.2f}%\n")
    
    # 2. 买入日开盘涨幅
    report.append("#### 2. 买入日开盘涨幅\n")
    valid_open = buys.dropna(subset=['开盘涨幅'])
    if len(valid_open) > 0:
        bins2 = {
            '一字板(>8%)': len(valid_open[valid_open['开盘涨幅'] > 8]),
            '中幅高开(3~8%)': len(valid_open[(valid_open['开盘涨幅'] > 3) & (valid_open['开盘涨幅'] <= 8)]),
            '小幅高开(0~3%)': len(valid_open[(valid_open['开盘涨幅'] >= 0) & (valid_open['开盘涨幅'] <= 3)]),
            '低开(<0%)': len(valid_open[valid_open['开盘涨幅'] < 0]),
        }
        total = len(valid_open)
        report.append("| 类型 | 笔数 | 占比 |")
        report.append("|------|------|------|")
        for k, v in bins2.items():
            report.append(f"| {k} | {v} | {v/total*100:.1f}% |")
        report.append(f"| **合计** | **{total}** | **100%** |")
        report.append(f"\n开盘涨幅均值: {valid_open['开盘涨幅'].mean():.2f}%, 中位数: {valid_open['开盘涨幅'].median():.2f}%\n")
    
    # 3. 买入日盘中最高涨幅
    report.append("#### 3. 买入日盘中最高涨幅\n")
    valid_high = buys.dropna(subset=['最高涨幅'])
    if len(valid_high) > 0:
        d14 = len(valid_high[valid_high['最高涨幅'] >= 14])
        d10_14 = len(valid_high[(valid_high['最高涨幅'] >= 10) & (valid_high['最高涨幅'] < 14)])
        d5_10 = len(valid_high[(valid_high['最高涨幅'] >= 5) & (valid_high['最高涨幅'] < 10)])
        d_lt5 = len(valid_high[valid_high['最高涨幅'] < 5])
        total = len(valid_high)
        report.append("| 类型 | 笔数 | 占比 |")
        report.append("|------|------|------|")
        report.append(f"| D14+(≥14%) | {d14} | {d14/total*100:.1f}% |")
        report.append(f"| D10-14(10~14%) | {d10_14} | {d10_14/total*100:.1f}% |")
        report.append(f"| D5-10(5~10%) | {d5_10} | {d5_10/total*100:.1f}% |")
        report.append(f"| <5% | {d_lt5} | {d_lt5/total*100:.1f}% |")
        report.append(f"\n最高涨幅均值: {valid_high['最高涨幅'].mean():.2f}%, 中位数: {valid_high['最高涨幅'].median():.2f}%\n")
    
    # 4. 板块偏好
    report.append("#### 4. 板块偏好\n")
    board_counts = buys['板块类型'].value_counts()
    total = len(buys)
    report.append("| 板块 | 笔数 | 占比 |")
    report.append("|------|------|------|")
    for k, v in board_counts.items():
        report.append(f"| {k} | {v} | {v/total*100:.1f}% |")
    
    # 5. 个股集中度
    report.append("\n#### 5. 个股集中度（Top10最常买）\n")
    stock_counts = buys.groupby(['股票代码', '股票名称']).size().sort_values(ascending=False).head(10)
    report.append("| 排名 | 股票 | 买入次数 |")
    report.append("|------|------|---------|")
    for rank, ((code, name), cnt) in enumerate(stock_counts.items(), 1):
        report.append(f"| {rank} | {name}({code}) | {cnt} |")
    
    unique_stocks = buys['股票代码'].nunique()
    report.append(f"\n共买入 **{unique_stocks}** 只不同股票，总 **{len(buys)}** 笔买入")
    report.append(f"反复交易率: {(len(buys) - unique_stocks)/len(buys)*100:.1f}%\n")
    
    return '\n'.join(report), buys


def analyze_holding(trade_returns, revenue_df, master_name):
    """B. 持仓策略分析"""
    report = []
    report.append(f"\n### B. 持仓策略分析\n")
    
    if len(trade_returns) == 0:
        report.append("无交易数据\n")
        return '\n'.join(report)
    
    # 1. 持仓天数分布
    report.append("#### 1. 持仓天数分布\n")
    tr = trade_returns.copy()
    tr['持仓天数'] = tr['持仓天数'].astype(int)
    
    hold_bins = {
        'T+1(1天)': tr[tr['持仓天数'] == 1],
        'T+2(2天)': tr[tr['持仓天数'] == 2],
        '3-5天': tr[(tr['持仓天数'] >= 3) & (tr['持仓天数'] <= 5)],
        '6-10天': tr[(tr['持仓天数'] >= 6) & (tr['持仓天数'] <= 10)],
        '10天+': tr[tr['持仓天数'] > 10],
    }
    
    report.append("| 持仓天数 | 笔数 | 占比 | 平均收益% | 胜率 |")
    report.append("|---------|------|------|----------|------|")
    total = len(tr)
    for label, sub in hold_bins.items():
        if len(sub) > 0:
            avg_ret = sub['收益%'].mean()
            win_rate = (sub['收益%'] > 0).sum() / len(sub) * 100
            report.append(f"| {label} | {len(sub)} | {len(sub)/total*100:.1f}% | {avg_ret:.2f}% | {win_rate:.1f}% |")
    
    report.append(f"\n持仓天数均值: {tr['持仓天数'].mean():.1f}天, 中位数: {tr['持仓天数'].median():.0f}天\n")
    
    # 2. 同时持股数量（从revenue_df获取）
    report.append("#### 2. 同时持股数量\n")
    if '持股数' in revenue_df.columns:
        rev = revenue_df[revenue_df['持股数'] > 0]
        report.append(f"- 日均持股: {rev['持股数'].mean():.1f}只\n")
        report.append(f"- 持股中位数: {rev['持股数'].median():.0f}只\n")
        report.append(f"- 最多同时持: {rev['持股数'].max():.0f}只\n")
        
        # 持股数分布
        hold_cnt = rev['持股数'].value_counts().sort_index()
        report.append("\n| 同时持股数 | 天数 | 占比 |")
        report.append("|-----------|------|------|")
        total_days = len(rev)
        for cnt, days in hold_cnt.items():
            report.append(f"| {int(cnt)}只 | {days} | {days/total_days*100:.1f}% |")
    
    # 3. 仓位管理
    report.append("\n#### 3. 仓位管理\n")
    if '仓位(%)' in revenue_df.columns:
        rev = revenue_df[revenue_df['仓位(%)'] > 0]
        if len(rev) > 0:
            report.append(f"- 平均仓位: {rev['仓位(%)'].mean():.1f}%\n")
            report.append(f"- 仓位中位数: {rev['仓位(%)'].median():.0f}%\n")
            report.append(f"- 满仓(>90%)天数占比: {(rev['仓位(%)'] > 90).sum()/len(rev)*100:.1f}%\n")
            report.append(f"- 半仓以下(<50%)天数占比: {(rev['仓位(%)'] < 50).sum()/len(rev)*100:.1f}%\n")
    
    return '\n'.join(report)


def analyze_sell_timing(trade_returns, master_name):
    """C. 卖出时机分析"""
    report = []
    report.append(f"\n### C. 卖出时机分析\n")
    
    if len(trade_returns) == 0:
        report.append("无交易数据\n")
        return '\n'.join(report)
    
    tr = trade_returns.copy()
    
    # 1. 止盈点位
    report.append("#### 1. 收益分布（止盈/止损点位）\n")
    winners = tr[tr['收益%'] > 0]
    losers = tr[tr['收益%'] <= 0]
    
    report.append(f"- 总交易: {len(tr)}笔\n")
    report.append(f"- 盈利: {len(winners)}笔 ({len(winners)/len(tr)*100:.1f}%), 平均盈利: +{winners['收益%'].mean():.2f}%\n")
    report.append(f"- 亏损: {len(losers)}笔 ({len(losers)/len(tr)*100:.1f}%), 平均亏损: {losers['收益%'].mean():.2f}%\n")
    report.append(f"- 盈亏比: {abs(winners['收益%'].mean() / losers['收益%'].mean()):.2f}\n" if len(losers) > 0 and losers['收益%'].mean() != 0 else "")
    report.append(f"- 单笔平均收益: {tr['收益%'].mean():.2f}%\n")
    
    # 收益区间分布
    ret_bins = {
        '大赚(>10%)': len(tr[tr['收益%'] > 10]),
        '中赚(5~10%)': len(tr[(tr['收益%'] > 5) & (tr['收益%'] <= 10)]),
        '小赚(0~5%)': len(tr[(tr['收益%'] > 0) & (tr['收益%'] <= 5)]),
        '小亏(0~-5%)': len(tr[(tr['收益%'] <= 0) & (tr['收益%'] > -5)]),
        '中亏(-5~-10%)': len(tr[(tr['收益%'] <= -5) & (tr['收益%'] > -10)]),
        '大亏(<-10%)': len(tr[tr['收益%'] <= -10]),
    }
    total = len(tr)
    report.append("\n| 收益区间 | 笔数 | 占比 |")
    report.append("|---------|------|------|")
    for k, v in ret_bins.items():
        report.append(f"| {k} | {v} | {v/total*100:.1f}% |")
    
    # 2. 盈利vs亏损票持仓时间
    report.append("\n#### 2. 盈利票vs亏损票持仓时间\n")
    if '持仓天数' in tr.columns and len(winners) > 0 and len(losers) > 0:
        report.append(f"- 盈利票平均持仓: {winners['持仓天数'].mean():.1f}天\n")
        report.append(f"- 亏损票平均持仓: {losers['持仓天数'].mean():.1f}天\n")
        if winners['持仓天数'].mean() > losers['持仓天数'].mean():
            report.append("→ **让利润奔跑**：盈利票拿得更久\n")
        else:
            report.append("→ 亏损票拿的时间更长（不太好）\n")
    
    return '\n'.join(report)


def analyze_attribution(trade_returns, revenue_df, master_name):
    """D. 收益归因"""
    report = []
    report.append(f"\n### D. 收益归因\n")
    
    if len(trade_returns) == 0:
        report.append("无交易数据\n")
        return '\n'.join(report)
    
    tr = trade_returns.copy()
    
    # 1. 大赚交易特征
    report.append("#### 1. 大赚交易（>10%）\n")
    big_wins = tr[tr['收益%'] > 10].sort_values('收益%', ascending=False)
    if len(big_wins) > 0:
        report.append(f"共 **{len(big_wins)}** 笔大赚交易，平均收益 +{big_wins['收益%'].mean():.2f}%\n")
        report.append("| 股票 | 买入日 | 卖出日 | 持仓天数 | 收益% |")
        report.append("|------|--------|--------|---------|-------|")
        for _, row in big_wins.head(15).iterrows():
            report.append(f"| {row['股票名称']}({row['股票代码']}) | {row['买入日期']} | {row['卖出日期']} | {row['持仓天数']} | +{row['收益%']:.1f}% |")
        
        # 大赚交易的共同特征
        report.append(f"\n大赚交易平均持仓: {big_wins['持仓天数'].mean():.1f}天")
        gem_pct = sum(1 for c in big_wins['股票代码'] if is_gem_or_star(c)) / len(big_wins) * 100
        report.append(f"大赚交易中20%板占比: {gem_pct:.1f}%\n")
    else:
        report.append("无大赚交易\n")
    
    # 2. 大亏交易特征
    report.append("#### 2. 大亏交易（<-10%）\n")
    big_losses = tr[tr['收益%'] < -10].sort_values('收益%')
    if len(big_losses) > 0:
        report.append(f"共 **{len(big_losses)}** 笔大亏交易，平均亏损 {big_losses['收益%'].mean():.2f}%\n")
        report.append("| 股票 | 买入日 | 卖出日 | 持仓天数 | 收益% |")
        report.append("|------|--------|--------|---------|-------|")
        for _, row in big_losses.head(10).iterrows():
            report.append(f"| {row['股票名称']}({row['股票代码']}) | {row['买入日期']} | {row['卖出日期']} | {row['持仓天数']} | {row['收益%']:.1f}% |")
    else:
        report.append("无大亏交易(>-10%)，风控优秀！\n")
    
    # 3. 按月份分析
    report.append("\n#### 3. 按月份收益分析\n")
    tr['月份'] = tr['卖出日期'].astype(str).str[:6]
    monthly = tr.groupby('月份').agg(
        笔数=('收益%', 'count'),
        平均收益=('收益%', 'mean'),
        胜率=('收益%', lambda x: (x > 0).sum() / len(x) * 100),
        总收益=('收益%', 'sum'),
    ).round(2)
    
    report.append("| 月份 | 笔数 | 平均收益% | 胜率% | 总收益% |")
    report.append("|------|------|----------|-------|---------|")
    for month, row in monthly.iterrows():
        report.append(f"| {month} | {int(row['笔数'])} | {row['平均收益']:.2f}% | {row['胜率']:.1f}% | {row['总收益']:.1f}% |")
    
    return '\n'.join(report)


# ============================================================
#  只核大学生专用分析（有完整买卖记录）
# ============================================================

def analyze_zhihe():
    """分析只核大学生（有完整买卖记录）"""
    print("=" * 60)
    print("分析: 只核大学生")
    print("=" * 60)
    
    trades_df = load_zhihe_data()
    holdings_df = load_zhihe_holdings()
    revenue_df = load_zhihe_revenue()
    
    # 计算交易收益
    trade_returns = compute_trade_returns(trades_df)
    
    # A. 选股特征
    section_a, buys_enhanced = analyze_selection(trades_df, '只核大学生')
    
    # B. 持仓策略
    section_b = analyze_holding(trade_returns, revenue_df, '只核大学生')
    
    # C. 卖出时机
    section_c = analyze_sell_timing(trade_returns, '只核大学生')
    
    # D. 收益归因
    section_d = analyze_attribution(trade_returns, revenue_df, '只核大学生')
    
    report = f"""
## 1. 只核大学生 (+794%, 冠军)

**概览**: 总收益+794%, 2025全年比赛冠军。以T+1短线为主，追涨停板+小幅高开买入是核心打法。

{section_a}
{section_b}
{section_c}
{section_d}
"""
    
    return report, trade_returns


# ============================================================
#  批量高手分析（从持仓明细推断）
# ============================================================

def analyze_batch_master(name, match_id, rank_info):
    """分析批量高手"""
    print("=" * 60)
    print(f"分析: {name}")
    print("=" * 60)
    
    holdings_df = load_batch_holdings(name, match_id)
    revenue_df = load_batch_revenue(name, match_id)
    
    # 推断交易
    trades_df = infer_trades_from_holdings(holdings_df, revenue_df)
    
    if len(trades_df) == 0:
        return f"\n## {name}\n\n无法推断交易记录\n", pd.DataFrame()
    
    print(f"  推断出 {len(trades_df)} 条交易记录（买+卖）")
    
    # 计算收益
    trade_returns = compute_trade_returns(trades_df, holdings_df)
    print(f"  计算出 {len(trade_returns)} 笔完整交易收益")
    
    # A. 选股特征
    section_a, buys_enhanced = analyze_selection(trades_df, name)
    
    # B. 持仓策略
    section_b = analyze_holding(trade_returns, revenue_df, name)
    
    # C. 卖出时机
    section_c = analyze_sell_timing(trade_returns, name)
    
    # D. 收益归因
    section_d = analyze_attribution(trade_returns, revenue_df, name)
    
    report = f"""
## {rank_info}

{section_a}
{section_b}
{section_c}
{section_d}
"""
    
    return report, trade_returns


# ============================================================
#  E. 回测
# ============================================================

def backtest_strategy(strategy_name, select_fn, hold_days=1, start_date='20250101', end_date='20251231'):
    """
    通用回测框架
    select_fn(kline_today, kline_yesterday) -> bool  是否买入
    hold_days: 持仓交易日天数
    """
    # 加载全部股票列表
    from glob import glob
    kline_dir = '/Users/tq/Documents/quant_data/miniqmt_data/1d/'
    files = glob(os.path.join(kline_dir, '*_20250101_20251231.csv'))
    
    all_trades = []
    
    for f in files:
        code = os.path.basename(f).split('_')[0]
        
        try:
            df = pd.read_csv(f, encoding='utf-8-sig')
        except:
            continue
        
        if len(df) < 10:
            continue
        
        df['date_str'] = df['date'].astype(str).str[:8]
        df = df[(df['date_str'] >= start_date) & (df['date_str'] <= end_date)].reset_index(drop=True)
        
        if len(df) < 5:
            continue
        
        for i in range(2, len(df) - hold_days):
            today = df.iloc[i]
            yesterday = df.iloc[i-1]
            day_before = df.iloc[i-2]
            
            # 计算指标
            prev_chg = (yesterday['close'] - day_before['close']) / day_before['close'] * 100
            open_chg = (today['open'] - yesterday['close']) / yesterday['close'] * 100
            high_chg = (today['high'] - yesterday['close']) / yesterday['close'] * 100
            
            info = {
                'prev_chg': prev_chg,
                'open_chg': open_chg,
                'high_chg': high_chg,
                'code': code,
                'date': today['date_str'],
                'today_open': today['open'],
                'today_close': today['close'],
                'today_high': today['high'],
                'today_low': today['low'],
                'yesterday_close': yesterday['close'],
                'yesterday_volume': yesterday.get('volume', 0),
            }
            
            if select_fn(info):
                # 以今日开盘价买入
                buy_price = today['open']
                # 持仓hold_days个交易日后卖出
                sell_idx = i + hold_days
                if sell_idx >= len(df):
                    continue
                sell_price = df.iloc[sell_idx]['open']
                
                ret = (sell_price - buy_price) / buy_price * 100 - 0.15
                
                all_trades.append({
                    'code': code,
                    'buy_date': today['date_str'],
                    'sell_date': df.iloc[sell_idx]['date_str'],
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'return': round(ret, 2),
                    'prev_chg': round(prev_chg, 2),
                    'open_chg': round(open_chg, 2),
                })
    
    return pd.DataFrame(all_trades)


def run_backtests():
    """运行所有回测策略"""
    results = {}
    report = []
    report.append("\n## 六、策略回测结果\n")
    
    # 策略1：只核大学生 - 昨日涨停+今日小幅高开
    print("回测策略1: 只核大学生式 - 昨日涨停+小幅高开+T1卖出")
    def zhihe_strategy(info):
        # 昨日涨停(涨幅>9.5% for 10%板, >19% for 20%板)
        limit = 19 if is_gem_or_star(info['code']) else 9.5
        if info['prev_chg'] < limit:
            return False
        # 今日小幅高开(0~3%)
        if info['open_chg'] < 0 or info['open_chg'] > 3:
            return False
        return True
    
    bt1 = backtest_strategy('只核大学生式', zhihe_strategy, hold_days=1)
    results['zhihe_v1'] = bt1
    
    # 策略1b: 只核大学生 - 仅10%板
    print("回测策略1b: 只核大学生式(仅10%板) - 昨日涨停+小幅高开+T1卖出")
    def zhihe_strategy_10(info):
        if is_gem_or_star(info['code']):
            return False
        if info['prev_chg'] < 9.5:
            return False
        if info['open_chg'] < 0 or info['open_chg'] > 3:
            return False
        return True
    
    bt1b = backtest_strategy('只核大学生式(10%板)', zhihe_strategy_10, hold_days=1)
    results['zhihe_v1_10pct'] = bt1b
    
    # 策略2: 天牌式 - 昨日下跌+今日低开反弹+T1
    print("回测策略2: 天牌式 - 昨日下跌+今日低开+T1卖出")
    def tianpai_strategy(info):
        # 昨日下跌(-1%~-5%)
        if info['prev_chg'] > -1 or info['prev_chg'] < -5:
            return False
        # 今日低开但不太多
        if info['open_chg'] > 0 or info['open_chg'] < -3:
            return False
        # 盘中反弹(最高涨幅>2%)
        if info['high_chg'] < 2:
            return False
        return True
    
    bt2 = backtest_strategy('天牌式', tianpai_strategy, hold_days=1)
    results['tianpai'] = bt2
    
    # 策略3: 低调内敛的朋 - 昨日下跌+买入+持5天
    print("回测策略3: 低调式 - 昨日下跌+买入+持5天卖出")
    def didiao_strategy(info):
        # 昨日下跌(-2%~-8%)
        if info['prev_chg'] > -2 or info['prev_chg'] < -8:
            return False
        # 今日继续低开
        if info['open_chg'] > 1:
            return False
        return True
    
    bt3 = backtest_strategy('低调式', didiao_strategy, hold_days=5)
    results['didiao'] = bt3
    
    # 策略4: 独行侠令狐冲 - 精选强势+中线持有
    print("回测策略4: 令狐冲式 - 昨日大涨+今日小幅高开+持10天")
    def linghu_strategy(info):
        if is_gem_or_star(info['code']):
            return False
        # 昨日大涨(5%~9%)
        if info['prev_chg'] < 5 or info['prev_chg'] > 9:
            return False
        # 今日小幅高开(0~2%)
        if info['open_chg'] < 0 or info['open_chg'] > 2:
            return False
        return True
    
    bt4 = backtest_strategy('令狐冲式', linghu_strategy, hold_days=10)
    results['linghu'] = bt4
    
    # 策略5: 只核大学生加强版 - 涨停+低开
    print("回测策略5: 只核加强版 - 昨日涨停+今日低开买入+T1卖出")
    def zhihe_v2_strategy(info):
        limit = 19 if is_gem_or_star(info['code']) else 9.5
        if info['prev_chg'] < limit:
            return False
        # 今日低开(-3%~0%)
        if info['open_chg'] > 0 or info['open_chg'] < -3:
            return False
        return True
    
    bt5 = backtest_strategy('只核加强版', zhihe_v2_strategy, hold_days=1)
    results['zhihe_v2'] = bt5
    
    # 策略6: 只核大学生 开盘0~5%高开
    print("回测策略6: 只核宽松版 - 昨日涨停+今日0~5%高开+T1卖出")
    def zhihe_v3_strategy(info):
        limit = 19 if is_gem_or_star(info['code']) else 9.5
        if info['prev_chg'] < limit:
            return False
        if info['open_chg'] < 0 or info['open_chg'] > 5:
            return False
        return True
    
    bt6 = backtest_strategy('只核宽松版', zhihe_v3_strategy, hold_days=1)
    results['zhihe_v3'] = bt6
    
    # 汇总回测结果
    report.append("### 各策略回测对比\n")
    report.append("| 策略 | 交易笔数 | 平均收益% | 胜率% | 盈亏比 | 大赚>10%占比 | 大亏<-10%占比 |")
    report.append("|------|---------|----------|-------|--------|------------|------------|")
    
    strategy_labels = {
        'zhihe_v1': '只核式(涨停+高开0~3%+T1)',
        'zhihe_v1_10pct': '只核式仅10%板',
        'tianpai': '天牌式(跌+低开反弹+T1)',
        'didiao': '低调式(跌+低开+持5天)',
        'linghu': '令狐冲式(大涨+高开+持10天)',
        'zhihe_v2': '只核加强(涨停+低开+T1)',
        'zhihe_v3': '只核宽松(涨停+高开0~5%+T1)',
    }
    
    good_strategies = []
    
    for key, label in strategy_labels.items():
        bt = results.get(key, pd.DataFrame())
        if len(bt) == 0:
            report.append(f"| {label} | 0 | - | - | - | - | - |")
            continue
        
        n = len(bt)
        avg_ret = bt['return'].mean()
        win_rate = (bt['return'] > 0).sum() / n * 100
        winners = bt[bt['return'] > 0]
        losers = bt[bt['return'] <= 0]
        pl_ratio = abs(winners['return'].mean() / losers['return'].mean()) if len(losers) > 0 and losers['return'].mean() != 0 else 999
        big_win = (bt['return'] > 10).sum() / n * 100
        big_loss = (bt['return'] < -10).sum() / n * 100
        
        report.append(f"| {label} | {n} | {avg_ret:.2f}% | {win_rate:.1f}% | {pl_ratio:.2f} | {big_win:.1f}% | {big_loss:.1f}% |")
        
        if avg_ret > 2 and win_rate > 55:
            good_strategies.append((key, label, bt))
    
    # 月度表现分析
    for key, label in strategy_labels.items():
        bt = results.get(key, pd.DataFrame())
        if len(bt) == 0 or len(bt) < 10:
            continue
        
        report.append(f"\n#### {label} - 月度表现\n")
        bt_copy = bt.copy()
        bt_copy['month'] = bt_copy['buy_date'].str[:6]
        monthly = bt_copy.groupby('month').agg(
            笔数=('return', 'count'),
            平均收益=('return', 'mean'),
            胜率=('return', lambda x: (x > 0).sum() / len(x) * 100),
        ).round(2)
        
        report.append("| 月份 | 笔数 | 平均收益% | 胜率% |")
        report.append("|------|------|----------|-------|")
        for month, row in monthly.iterrows():
            report.append(f"| {month} | {int(row['笔数'])} | {row['平均收益']:.2f}% | {row['胜率']:.1f}% |")
    
    return '\n'.join(report), results, good_strategies


# ============================================================
#  主函数
# ============================================================

def main():
    all_reports = []
    all_returns = {}
    
    # 报告头
    all_reports.append("# 淘股吧6位高手交易策略深度研究\n")
    all_reports.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    all_reports.append("---\n")
    all_reports.append("## 目录\n")
    all_reports.append("1. 只核大学生 (+794%, 冠军)")
    all_reports.append("2. 天牌 (+631%)")
    all_reports.append("3. 低调内敛的朋 (+470%)")
    all_reports.append("4. 独行侠令狐冲 (+229%)")
    all_reports.append("5. 忘忧阁主 (+162%)")
    all_reports.append("6. 龙年大叔 (+90%)")
    all_reports.append("7. 策略回测")
    all_reports.append("8. 策略可复制性评分")
    all_reports.append("9. 推荐策略\n")
    all_reports.append("---\n")
    
    # 1. 只核大学生
    report1, returns1 = analyze_zhihe()
    all_reports.append(report1)
    all_returns['只核大学生'] = returns1
    
    # 2-6. 其他5位高手
    masters = [
        ('天牌', '802', '2. 天牌 (+631%)'),
        ('低调内敛的朋', '802', '3. 低调内敛的朋 (+470%)'),
        ('独行侠令狐冲', '802', '4. 独行侠令狐冲 (+229%)'),
        ('忘忧阁主', '802', '5. 忘忧阁主 (+162%)'),
        ('龙年大叔', '858', '6. 龙年大叔 (+90%)'),
    ]
    
    for name, match_id, rank_info in masters:
        report, returns = analyze_batch_master(name, match_id, rank_info)
        all_reports.append(report)
        all_returns[name] = returns
    
    # 汇总对比表
    all_reports.append("\n---\n")
    all_reports.append("## 总体对比\n")
    all_reports.append("| 高手 | 交易笔数 | 平均收益% | 胜率% | 盈亏比 | 平均持仓天数 | 20%板占比 |")
    all_reports.append("|------|---------|----------|-------|--------|------------|----------|")
    
    for name, returns in all_returns.items():
        if len(returns) == 0:
            continue
        n = len(returns)
        avg_ret = returns['收益%'].mean()
        win_rate = (returns['收益%'] > 0).sum() / n * 100
        winners = returns[returns['收益%'] > 0]
        losers = returns[returns['收益%'] <= 0]
        pl_ratio = abs(winners['收益%'].mean() / losers['收益%'].mean()) if len(losers) > 0 and losers['收益%'].mean() != 0 else 999
        avg_hold = returns['持仓天数'].mean() if '持仓天数' in returns.columns else 0
        gem_pct = sum(1 for c in returns['股票代码'] if is_gem_or_star(c)) / n * 100
        all_reports.append(f"| {name} | {n} | {avg_ret:.2f}% | {win_rate:.1f}% | {pl_ratio:.2f} | {avg_hold:.1f} | {gem_pct:.1f}% |")
    
    # 回测
    all_reports.append("\n---\n")
    bt_report, bt_results, good_strategies = run_backtests()
    all_reports.append(bt_report)
    
    # 策略可复制性评分
    all_reports.append("\n---\n")
    all_reports.append("## 七、策略可复制性评分\n")
    all_reports.append("| 高手 | 策略清晰度 | 执行难度 | 回测验证 | 可复制性评分 | 推荐度 |")
    all_reports.append("|------|-----------|---------|---------|------------|--------|")
    
    scores = [
        ('只核大学生', '★★★★★', '★★★☆☆', '待验证', '4/5', '⭐⭐⭐⭐'),
        ('天牌', '★★★☆☆', '★★★★☆', '待验证', '3/5', '⭐⭐⭐'),
        ('低调内敛的朋', '★★★★☆', '★★☆☆☆', '待验证', '3.5/5', '⭐⭐⭐'),
        ('独行侠令狐冲', '★★☆☆☆', '★☆☆☆☆', '待验证', '2/5', '⭐⭐'),
        ('忘忧阁主', '★★★☆☆', '★★★★☆', '待验证', '2.5/5', '⭐⭐'),
        ('龙年大叔', '★★☆☆☆', '★☆☆☆☆', '待验证', '2/5', '⭐⭐'),
    ]
    
    # 根据回测结果更新评分
    for name, clarity, difficulty, _, _, _ in scores:
        # 这里根据实际回测结果动态更新
        bt_verified = '待验证'
        for key, label, bt in good_strategies:
            if name in label or (name == '只核大学生' and '只核' in label):
                bt_verified = f'✅ 单笔{bt["return"].mean():.1f}%'
                break
        
    for name, clarity, difficulty, _, score, rec in scores:
        all_reports.append(f"| {name} | {clarity} | {difficulty} | 见回测 | {score} | {rec} |")
    
    # 推荐策略
    all_reports.append("\n## 八、推荐策略\n")
    all_reports.append("### 基于回测结果的推荐\n")
    
    if good_strategies:
        all_reports.append("以下策略回测效果达标（单笔>2%, 胜率>55%）：\n")
        for key, label, bt in good_strategies:
            avg_ret = bt['return'].mean()
            win_rate = (bt['return'] > 0).sum() / len(bt) * 100
            all_reports.append(f"- **{label}**: 单笔{avg_ret:.2f}%, 胜率{win_rate:.1f}%, {len(bt)}笔")
    else:
        all_reports.append("无策略达到（单笔>2%, 胜率>55%）的门槛。")
        all_reports.append("\n最接近的策略：\n")
        # 列出最好的策略
        best_results = []
        for key, bt in bt_results.items():
            if len(bt) > 0:
                avg_ret = bt['return'].mean()
                win_rate = (bt['return'] > 0).sum() / len(bt) * 100
                best_results.append((key, avg_ret, win_rate, len(bt)))
        best_results.sort(key=lambda x: x[1], reverse=True)
        for key, avg_ret, win_rate, n in best_results[:3]:
            all_reports.append(f"- {key}: 单笔{avg_ret:.2f}%, 胜率{win_rate:.1f}%, {n}笔")
    
    all_reports.append("\n### 策略改进方向\n")
    all_reports.append("1. **增加选股过滤**：加入市值、换手率、板块等过滤条件")
    all_reports.append("2. **优化买入时机**：结合分时图选择更好的介入点")
    all_reports.append("3. **动态止损/止盈**：根据持仓天数和浮盈调整")
    all_reports.append("4. **仓位管理**：根据胜率和赔率调整单笔仓位\n")
    
    # 写入报告
    report_path = os.path.join(OUTPUT_DIR, '淘股吧高手策略深度研究.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_reports))
    
    print(f"\n✅ 报告已保存到: {report_path}")
    
    # 保存优秀策略代码
    if good_strategies:
        for key, label, bt in good_strategies:
            save_strategy(key, label, bt)
    
    return all_returns, bt_results


def save_strategy(key, label, bt):
    """保存优秀策略代码到 analyze/ 目录"""
    strategy_path = os.path.join(PROJECT_ROOT, 'analyze', f'strategy_{key}.py')
    
    avg_ret = bt['return'].mean()
    win_rate = (bt['return'] > 0).sum() / len(bt) * 100
    
    code = f'''#!/usr/bin/env python3
"""
策略: {label}
回测结果: 单笔{avg_ret:.2f}%, 胜率{win_rate:.1f}%, {len(bt)}笔
"""

def select(prev_chg, open_chg, high_chg, code):
    """
    选股条件
    prev_chg: 前一日涨幅%
    open_chg: 今日开盘涨幅%
    high_chg: 今日盘中最高涨幅%
    code: 股票代码
    """
    # TODO: 根据具体策略填入条件
    pass

if __name__ == "__main__":
    print("策略: {label}")
    print("回测结果: 单笔{avg_ret:.2f}%, 胜率{win_rate:.1f}%")
'''
    
    os.makedirs(os.path.dirname(strategy_path), exist_ok=True)
    with open(strategy_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print(f"策略代码已保存: {strategy_path}")


if __name__ == '__main__':
    all_returns, bt_results = main()
