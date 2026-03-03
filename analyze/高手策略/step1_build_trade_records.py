#!/usr/bin/env python3
"""
Step 1: 从持仓明细+收益明细推断5位高手的买卖记录，补充价格信息，生成Excel
"""
import os, sys, glob, warnings
import pandas as pd
import numpy as np
from datetime import datetime

warnings.filterwarnings('ignore')

PROJECT_ROOT = '/Users/tq/PycharmProjects/stocks_analysis'
BATCH_DIR    = os.path.join(PROJECT_ROOT, 'output', 'tgb_batch')
OUTPUT_DIR   = os.path.join(PROJECT_ROOT, 'output')
KLINE_DIR    = '/Users/tq/Documents/quant_data/miniqmt_data/1d'

# ─── 工具 ─────────────────────────────────────────────
def clean_code(v):
    return str(v).split('.')[0].zfill(6)

def is_gem(code):
    return code.startswith('300') or code.startswith('688') or code.startswith('301')

def parse_amount(v):
    if pd.isna(v) or str(v).strip() in ('--',''):
        return np.nan
    s = str(v).replace('元','').replace(',','').strip()
    if '万' in s:
        return float(s.replace('万','')) * 10000
    try: return float(s)
    except: return np.nan

# ─── K线索引（只读目标股票，不全量扫描）─────────────────
_kline_cache = {}

def load_kline_for_code(code):
    """直接按代码拼路径读取日线，不走全量索引"""
    if code in _kline_cache:
        return _kline_cache[code]
    
    # 判断交易所
    if code.startswith('6') or code.startswith('9'):
        exch = 'SH'
    else:
        exch = 'SZ'
    
    key = f'{code}_{exch}'
    pattern = os.path.join(KLINE_DIR, f'{key}_*.csv')
    files = sorted(glob.glob(pattern))
    
    if not files:
        _kline_cache[code] = None
        return None
    
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, encoding='utf-8-sig', dtype={'date': str})
            if 'date' in df.columns and 'open' in df.columns:
                df['date_str'] = df['date'].str[:8]
                dfs.append(df[['date_str','open','high','low','close','volume','preClose']]
                           if 'preClose' in df.columns 
                           else df[['date_str','open','high','low','close','volume']])
        except Exception as e:
            pass
    
    if not dfs:
        _kline_cache[code] = None
        return None
    
    result = pd.concat(dfs, ignore_index=True).drop_duplicates('date_str').sort_values('date_str').reset_index(drop=True)
    _kline_cache[code] = result
    return result


def get_price_info(code, date_str):
    """获取某股票某日的行情信息（开/高/低/收/前日涨幅/开盘涨幅/最高涨幅）"""
    kdf = load_kline_for_code(code)
    if kdf is None:
        return {}
    
    d = str(date_str).replace('-','')
    idx_list = kdf.index[kdf['date_str'] == d].tolist()
    if not idx_list:
        return {}
    i = idx_list[0]
    
    row = kdf.iloc[i]
    result = {
        'open':  row['open'],
        'high':  row['high'],
        'low':   row['low'],
        'close': row['close'],
    }
    
    # 前一日收盘
    if i > 0:
        prev_close = kdf.iloc[i-1]['close']
    elif 'preClose' in kdf.columns:
        prev_close = row.get('preClose', None)
    else:
        prev_close = None
    
    if prev_close and prev_close > 0:
        result['open_chg']  = (row['open']  - prev_close) / prev_close * 100
        result['high_chg']  = (row['high']  - prev_close) / prev_close * 100
        result['close_chg'] = (row['close'] - prev_close) / prev_close * 100
        result['prev_close'] = prev_close
    
    # 前一日涨幅
    if i >= 2:
        pp_close = kdf.iloc[i-2]['close']
        if pp_close > 0:
            result['prev_close_chg'] = (prev_close - pp_close) / pp_close * 100 if prev_close else np.nan
    elif i == 1:
        if 'preClose' in kdf.columns:
            pc = kdf.iloc[0].get('preClose', None)
            if pc and pc > 0 and prev_close:
                result['prev_close_chg'] = (prev_close - pc) / pc * 100
    
    return result


# ─── 推断买卖记录 ─────────────────────────────────────
def infer_trades(holdings_df, revenue_df):
    """
    从持仓明细推断买卖交易
    
    holdings_df: 持仓明细 (日期, 股票代码, 股票名称, 金额_num)
    revenue_df:  收益明细 (日期, 当日资产, 仓位, 持股代码 ...)
    
    策略：
    1. 以收益明细的"持股代码"为主（每天实际持有的代码集合）
    2. 持仓明细提供名称映射和金额
    3. 新出现 = 买入, 消失 = 卖出
    """
    # 整理收益明细 -> 每日持仓code集合
    revenue_df = revenue_df.copy()
    revenue_df['日期'] = revenue_df['日期'].astype(str).str[:8]
    revenue_df = revenue_df.sort_values('日期').reset_index(drop=True)
    
    daily_codes = {}
    for _, row in revenue_df.iterrows():
        d = row['日期']
        codes_raw = str(row.get('持股代码', ''))
        if codes_raw and codes_raw.lower() not in ('nan',''):
            codes = {clean_code(c.strip()) for c in codes_raw.split(',') if c.strip()}
        else:
            codes = set()
        # 用仓位过滤：仓位=0说明空仓
        if row.get('仓位(%)', 100) == 0:
            codes = set()
        daily_codes[d] = codes
    
    # 同时也用持仓明细（有时候收益明细缺日期）
    holdings_df = holdings_df.copy()
    holdings_df['日期'] = holdings_df['日期'].astype(str).str[:8]
    
    # 名称映射: code -> name
    code_name_map = {}
    for _, row in holdings_df.iterrows():
        code = clean_code(row['股票代码'])
        code_name_map[code] = row.get('股票名称', code)
    
    # 持仓明细补充daily_codes（某些天持仓明细有但收益明细没有记录）
    for d, grp in holdings_df.groupby('日期'):
        if d not in daily_codes:
            # 过滤金额>0的
            if '金额_num' in grp.columns:
                valid = grp[grp['金额_num'] > 0]
            else:
                valid = grp
            daily_codes[d] = {clean_code(c) for c in valid['股票代码'].unique()}
    
    dates = sorted(daily_codes.keys())
    
    # 推断买入/卖出
    active = {}  # code -> buy_date
    trades = []  # list of trade records
    
    for i, d in enumerate(dates):
        cur = daily_codes[d]
        prev = daily_codes[dates[i-1]] if i > 0 else set()
        
        # 新买入
        for code in cur - prev:
            active[code] = d
            trades.append({
                '操作': '买入',
                '操作日期': d,
                '股票代码': code,
                '股票名称': code_name_map.get(code, ''),
            })
        
        # 卖出
        for code in prev - cur:
            buy_date = active.pop(code, None)
            # 计算持仓天数（交易日数）
            if buy_date:
                b_idx = dates.index(buy_date) if buy_date in dates else None
                hold_days = i - b_idx if b_idx is not None else None
            else:
                hold_days = None
            trades.append({
                '操作': '卖出',
                '操作日期': d,
                '股票代码': code,
                '股票名称': code_name_map.get(code, ''),
                '买入日期': buy_date,
                '持仓天数': hold_days,
            })
    
    return pd.DataFrame(trades), daily_codes, revenue_df


def build_paired_trades(trades_df, revenue_df, name):
    """
    将买卖配对，补充价格信息，生成完整交易记录
    revenue_df 用于获取总资产/仓位/累计收益
    """
    if len(trades_df) == 0:
        return pd.DataFrame()
    
    # 资产信息映射: 日期 -> row
    rev_map = {str(r['日期'])[:8]: r for _, r in revenue_df.iterrows()}
    
    records = []
    
    sells = trades_df[trades_df['操作'] == '卖出'].copy()
    
    for _, sell in sells.iterrows():
        code = sell['股票代码']
        buy_date = sell.get('买入日期', None)
        sell_date = sell['操作日期']
        hold_days = sell.get('持仓天数', None)
        
        if not buy_date or str(buy_date) == 'None' or str(buy_date) == 'nan':
            continue
        
        buy_date_str = str(buy_date).replace('-', '')
        sell_date_str = str(sell_date).replace('-', '')
        
        # 价格信息
        buy_info  = get_price_info(code, buy_date_str)
        sell_info = get_price_info(code, sell_date_str)
        
        buy_close  = buy_info.get('close',  None)
        sell_close = sell_info.get('close', None)
        
        # 收益 = 用买入日收盘 和 卖出日收盘 近似（实际买卖是在盘中）
        ret = None
        if buy_close and sell_close and buy_close > 0:
            ret = round((sell_close - buy_close) / buy_close * 100 - 0.15, 2)
        
        # 总资产
        sell_rev = rev_map.get(sell_date_str, {})
        total_asset = sell_rev.get('当日资产(万)', sell_rev.get('当日资产(元)', np.nan))
        cumret = sell_rev.get('总收益(%)', np.nan)
        position = sell_rev.get('仓位(%)', np.nan)
        
        # 买入日总资产
        buy_rev = rev_map.get(buy_date_str, {})
        buy_position = buy_rev.get('仓位(%)', np.nan)
        
        records.append({
            '高手名':          name,
            '买入日期':        buy_date_str,
            '卖出日期':        sell_date_str,
            '股票代码':        code,
            '股票名称':        sell.get('股票名称', ''),
            '持仓天数':        hold_days,
            '买入价_收盘':     buy_close,
            '卖出价_收盘':     sell_close,
            '单笔收益%':       ret,
            '买入日开盘涨幅%': round(buy_info.get('open_chg', np.nan), 2),
            '买入日最高涨幅%': round(buy_info.get('high_chg', np.nan), 2),
            '买入日收盘涨幅%': round(buy_info.get('close_chg', np.nan), 2),
            '前一日涨幅%':     round(buy_info.get('prev_close_chg', np.nan), 2),
            '板块':           '20%板' if is_gem(code) else '10%板',
            '卖出时总资产(万)': total_asset if isinstance(total_asset, float) else np.nan,
            '累计收益%':       cumret,
            '卖出时仓位%':     position,
        })
    
    return pd.DataFrame(records)


def load_master_data(name, match_id):
    """加载某高手的持仓明细+收益明细"""
    h_path = os.path.join(BATCH_DIR, f'{name}_比赛{match_id}_持仓明细.csv')
    r_path = os.path.join(BATCH_DIR, f'{name}_比赛{match_id}_收益明细.csv')
    
    holdings = pd.read_csv(h_path, encoding='utf-8-sig')
    holdings['股票代码'] = holdings['股票代码'].apply(clean_code)
    holdings['日期'] = holdings['日期'].astype(str)
    
    # 金额解析
    for col in ['金额(元)', '金额']:
        if col in holdings.columns:
            holdings['金额_num'] = holdings[col].apply(parse_amount)
            break
    
    revenue = pd.read_csv(r_path, encoding='utf-8-sig')
    
    return holdings, revenue


# ─── 主流程 ────────────────────────────────────────────
MASTERS = [
    ('天牌',           '802'),
    ('低调内敛的朋',   '802'),
    ('忘忧阁主',       '802'),
    ('独行侠令狐冲',   '802'),
    ('龙年大叔',       '858'),
]

all_paired = []

print("=" * 60)
print("Step 1: 从持仓明细推断买卖记录并补充价格")
print("=" * 60)

for name, match_id in MASTERS:
    print(f"\n处理: {name} (比赛{match_id})")
    
    holdings, revenue = load_master_data(name, match_id)
    print(f"  持仓明细 {len(holdings)} 行, 收益明细 {len(revenue)} 行")
    
    trades_df, daily_codes, revenue = infer_trades(holdings, revenue)
    buy_cnt  = (trades_df['操作'] == '买入').sum()
    sell_cnt = (trades_df['操作'] == '卖出').sum()
    print(f"  推断买入 {buy_cnt} 次, 卖出 {sell_cnt} 次")
    
    # 补充价格
    paired = build_paired_trades(trades_df, revenue, name)
    print(f"  配对完整交易 {len(paired)} 笔")
    
    if len(paired) > 0:
        hit = paired['单笔收益%'].notna().sum()
        print(f"  价格获取命中率: {hit}/{len(paired)} ({hit/len(paired)*100:.0f}%)")
        if hit > 0:
            avg_ret = paired['单笔收益%'].dropna().mean()
            win_rate = (paired['单笔收益%'].dropna() > 0).mean() * 100
            print(f"  单笔均值: {avg_ret:.2f}%, 胜率: {win_rate:.1f}%")
    
    # 保存单人Excel
    out_path = os.path.join(OUTPUT_DIR, f'tgb_{name}_交易明细.xlsx')
    paired.to_excel(out_path, index=False, engine='openpyxl')
    print(f"  ✅ 已保存: {out_path}")
    
    all_paired.append(paired)

# ─── 汇总Excel ────────────────────────────────────────
print("\n合并所有高手数据...")

# 加入只核大学生
zhihe_path = os.path.join(OUTPUT_DIR, 'tgb_zhihedaxuesheng_买卖记录.csv')
zhihe = pd.read_csv(zhihe_path, encoding='utf-8-sig')
zhihe['股票代码'] = zhihe['股票代码'].astype(str).apply(clean_code)

# 获取只核大学生的价格信息
zhihe_paired = []
sells_zh = zhihe[zhihe['操作'] == '卖出'].copy()
for _, row in sells_zh.iterrows():
    code = row['股票代码']
    buy_date = str(row.get('买入日期', '')).replace('-','').replace(' ','')
    sell_date = str(row['日期']).replace('-','').replace(' ','')
    hold_days = row.get('持仓天数', None)
    
    if not buy_date or buy_date in ('nan','None'):
        continue
    
    buy_info  = get_price_info(code, buy_date)
    sell_info = get_price_info(code, sell_date)
    
    buy_close  = buy_info.get('close',  None)
    sell_close = sell_info.get('close', None)
    
    ret = None
    if buy_close and sell_close and buy_close > 0:
        ret = round((sell_close - buy_close) / buy_close * 100 - 0.15, 2)
    
    zhihe_paired.append({
        '高手名':          '只核大学生',
        '买入日期':        buy_date,
        '卖出日期':        sell_date,
        '股票代码':        code,
        '股票名称':        row.get('股票名称', ''),
        '持仓天数':        hold_days,
        '买入价_收盘':     buy_close,
        '卖出价_收盘':     sell_close,
        '单笔收益%':       ret,
        '买入日开盘涨幅%': round(buy_info.get('open_chg', np.nan), 2),
        '买入日最高涨幅%': round(buy_info.get('high_chg', np.nan), 2),
        '买入日收盘涨幅%': round(buy_info.get('close_chg', np.nan), 2),
        '前一日涨幅%':     round(buy_info.get('prev_close_chg', np.nan), 2),
        '板块':           '20%板' if is_gem(code) else '10%板',
        '单笔盈亏%(记录)': row.get('当日收益(%)', np.nan),
        '累计收益%':       row.get('累计收益(%)', np.nan),
    })

zhihe_df = pd.DataFrame(zhihe_paired)
if len(zhihe_df) > 0:
    zhihe_df.to_excel(os.path.join(OUTPUT_DIR, 'tgb_只核大学生_交易明细_新.xlsx'), index=False)
    print(f"只核大学生: {len(zhihe_df)} 笔，命中率 {zhihe_df['单笔收益%'].notna().sum()}/{len(zhihe_df)}")
all_paired.insert(0, zhihe_df)

all_df = pd.concat([df for df in all_paired if len(df) > 0], ignore_index=True)
summary_path = os.path.join(OUTPUT_DIR, 'tgb_全部高手_交易汇总.xlsx')
all_df.to_excel(summary_path, index=False, engine='openpyxl')
print(f"\n✅ 汇总表已保存: {summary_path}")
print(f"   总计 {len(all_df)} 笔交易记录")

# 打印各高手汇总
print("\n📊 各高手交易统计:")
print(f"{'高手名':<12} {'笔数':>5} {'命中':>5} {'单笔均值':>9} {'胜率':>8} {'持仓天数中位':>12}")
for g, sub in all_df.groupby('高手名'):
    valid = sub.dropna(subset=['单笔收益%'])
    n = len(sub)
    hit = len(valid)
    avg = valid['单笔收益%'].mean() if hit > 0 else float('nan')
    wr  = (valid['单笔收益%'] > 0).mean() * 100 if hit > 0 else float('nan')
    if '持仓天数' in sub.columns:
        med_hold = sub['持仓天数'].dropna().median()
    else:
        med_hold = float('nan')
    print(f"{g:<12} {n:>5} {hit:>5} {avg:>+9.2f}% {wr:>7.1f}% {med_hold:>12.0f}")

print("\n✅ Step 1 完成！")
