#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻驱动选股 V3 - 终极优化版
优化点:
1. 大盘过滤: 上证指数跌破5日均线时不开仓
2. 只选TOP1龙头(不分散)
3. T+1止盈止损: 次日涨3%卖/跌5%止损/收盘兜底
4. 新闻热度门槛: 只在热度特别高的日子出手
5. 概念过滤: 只做历史胜率高的概念
6. 成交额门槛: 龙头要有大成交额
"""

import pandas as pd
import numpy as np
import os
import pickle
from collections import Counter

# ── 配置 ──
NEWS_DIR = '/Users/tq/Desktop/stocks_data/news-donwloader/news_data/'
CONCEPTS_FILE = '/Users/tq/Documents/quant_data/basic/A_Stocks1010.xlsx'
OUTPUT_DIR = '/Users/tq/PycharmProjects/stocks_analysis/output/'
CACHE_FILE = os.path.join(OUTPUT_DIR, 'daily_data_cache_2025.pkl')
INDEX_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d/'

NEWS_CONCEPT_MAP = {
    '人工智能': {'人工智能': 3, 'AI': 3, '大模型': 2, '算力': 2},
    'DeepSeek': {'人工智能': 3, 'AI': 3, '大模型': 3, '算力': 2},
    '大模型': {'大模型': 3, '人工智能': 2, '算力': 2},
    '算力': {'算力': 3, 'CPO': 3, '光模块': 2, '液冷': 2},
    '芯片': {'芯片': 3, '半导体': 3, '集成电路': 2},
    '半导体': {'半导体': 3, '芯片': 3},
    '机器人': {'机器人': 3, '人形机器人': 3, '减速器': 2},
    '人形机器人': {'人形机器人': 3, '机器人': 3},
    '量子': {'量子': 3, '量子计算': 3},
    '卫星': {'卫星': 3, '卫星互联网': 3, '航天': 2},
    '低空': {'低空经济': 3, '无人机': 3},
    '无人机': {'无人机': 3, '低空经济': 3},
    '自动驾驶': {'自动驾驶': 3, '智能驾驶': 3},
    '华为': {'华为': 3, '鸿蒙': 2},
    '光伏': {'光伏': 3, '新能源': 1},
    '储能': {'储能': 3, '新能源': 1},
    '锂电': {'锂电': 3},
    '核电': {'核电': 3},
    '风电': {'风电': 3},
    '军工': {'军工': 3, '国防': 3, '航空': 2},
    '航天': {'航天': 3, '商业航天': 3, '卫星': 2},
    '歼': {'军工': 3, '航空': 3},
    '导弹': {'军工': 3},
    '关税': {'国产替代': 3, '自主可控': 3, '芯片': 2},
    '制裁': {'国产替代': 3, '自主可控': 3},
    '十五五': {'新能源': 2, '航空航天': 2, '低空经济': 2, '人工智能': 2},
    '消费': {'消费': 2},
    '房地产': {'房地产': 3, '地产': 3},
    '医药': {'生物医药': 2, '创新药': 2},
    '数据': {'数据': 2, '数字经济': 2},
}

IMPORTANCE_KEYWORDS = {
    3: ['习近平', '国务院', '总理', '政治局', '四中全会', '两会', '政府工作报告', '重大突破'],
    2: ['发改委', '工信部', '证监会', '央行', '突破', '首次', '重磅'],
    1: ['利好', '增长', '提速'],
}

# ── 加载 ──
print("加载数据...")

news_list = []
for source in ['cls', 'sina']:
    path = f'{NEWS_DIR}{source}/'
    for f in sorted(os.listdir(path)):
        if f.endswith('.csv') and '2025' in f and 'all' not in f:
            df = pd.read_csv(f'{path}{f}')
            df['source'] = source
            news_list.append(df)
news = pd.concat(news_list, ignore_index=True)
news['datetime'] = pd.to_datetime(news['datetime'], errors='coerce')
news = news.dropna(subset=['datetime'])
news['content'] = news['content'].fillna('') + ' ' + news['title'].fillna('')
news['date'] = news['datetime'].dt.strftime('%Y%m%d').astype(int)
news['hour'] = news['datetime'].dt.hour

concepts_df = pd.read_excel(CONCEPTS_FILE)
concepts_df['商品代码'] = concepts_df['商品代码'].astype(str).str.zfill(6)
code_to_concepts = {k: str(v) for k, v in zip(concepts_df['商品代码'], concepts_df['同花顺概念old'].fillna(''))}
code_to_name = dict(zip(concepts_df['商品代码'], concepts_df['名称'].fillna('')))

with open(CACHE_FILE, 'rb') as f:
    daily_data = pickle.load(f)

trade_dates = sorted(daily_data.keys())
stock_daily = {}
for d, stocks in daily_data.items():
    for s in stocks:
        code = s['code']
        if code not in stock_daily:
            stock_daily[code] = {}
        stock_daily[code][d] = s

def get_td(date_int, offset=1):
    try:
        idx = trade_dates.index(date_int)
        target = idx + offset
        if 0 <= target < len(trade_dates):
            return trade_dates[target]
    except: pass
    return None

# ── 上证指数加载(大盘过滤用) ──
print("加载上证指数...")
sh_index = {}
# 找上证指数文件
for f in os.listdir(INDEX_DIR):
    if f.startswith('000001_') and f.endswith('.csv'):
        idx_df = pd.read_csv(os.path.join(INDEX_DIR, f))
        idx_df['date'] = idx_df['date'].astype(int)
        for _, row in idx_df.iterrows():
            sh_index[int(row['date'])] = row['close']
        break

# 计算5日均线
sh_ma5 = {}
for i, d in enumerate(trade_dates):
    if d in sh_index:
        # 取最近5个交易日的收盘价
        prices = []
        for j in range(max(0, i-4), i+1):
            if trade_dates[j] in sh_index:
                prices.append(sh_index[trade_dates[j]])
        if len(prices) >= 5:
            sh_ma5[d] = np.mean(prices)

print(f"上证指数: {len(sh_index)}天, MA5: {len(sh_ma5)}天")

# ── 预计算每日新闻热度 ──
print("预计算每日新闻热度...")
daily_heat = {}
for date_int in trade_dates:
    if date_int < 20250210 or date_int > 20260110:
        continue
    
    prev_dates = set()
    idx = trade_dates.index(date_int)
    if idx > 0: prev_dates.add(trade_dates[idx - 1])
    if idx > 1: prev_dates.add(trade_dates[idx - 2])
    
    mask = (
        ((news['date'].isin(prev_dates)) & (news['hour'] >= 15)) |
        ((news['date'] == date_int) & (news['hour'] < 10))
    )
    day_news = news[mask]
    if len(day_news) == 0:
        continue
    
    concept_heat = Counter()
    all_text = ' '.join(day_news['content'].tolist())
    
    importance = 1
    for level, keywords in IMPORTANCE_KEYWORDS.items():
        for kw in keywords:
            if kw in all_text:
                importance = max(importance, level)
    
    for news_kw, concept_weights in NEWS_CONCEPT_MAP.items():
        count = all_text.count(news_kw)
        if count > 0:
            for concept, weight in concept_weights.items():
                concept_heat[concept] += count * weight * importance
    
    if concept_heat:
        daily_heat[date_int] = concept_heat

print(f"有新闻信号: {len(daily_heat)}天")

# ── 预计算所有候选 ──
print("预计算候选...")
all_candidates = []  # flat list

for date_int in daily_heat:
    if date_int not in daily_data:
        continue
    
    heat = daily_heat[date_int]
    top_concepts = [c for c, _ in heat.most_common(8)]
    max_heat = heat.most_common(1)[0][1] if heat else 0
    
    stocks = daily_data[date_int]
    
    # 大盘状态
    above_ma5 = True
    if date_int in sh_index and date_int in sh_ma5:
        above_ma5 = sh_index[date_int] >= sh_ma5[date_int]
    
    for s in stocks:
        code = s['code']
        if code.startswith('8') or code.startswith('4'):
            continue
        
        concepts = code_to_concepts.get(code, '')
        concept_score = 0
        matched = []
        for hc in top_concepts:
            if hc in concepts:
                concept_score += heat[hc]
                matched.append(hc)
        
        if concept_score == 0:
            continue
        
        change = s['change_pct']
        if change < 5:
            continue
        
        amount_wan = s['amount'] / 10000 if s['amount'] > 0 else 0
        
        is_20pct = code.startswith('3') or code.startswith('688')
        limit_pct = 20 if is_20pct else 10
        is_limit_up = change >= limit_pct * 0.98
        
        # 前一天涨幅
        prev_change = 0
        prev_d = get_td(date_int, -1)
        if prev_d and code in stock_daily and prev_d in stock_daily[code]:
            prev_change = stock_daily[code][prev_d]['change_pct']
        is_lianban = prev_change >= 9.5 and is_limit_up
        
        # 买入日数据
        buy_date = get_td(date_int, 1)
        if buy_date is None:
            continue
        if code not in stock_daily or buy_date not in stock_daily[code]:
            continue
        buy_data = stock_daily[code][buy_date]
        buy_price = buy_data['open']
        if buy_price <= 0:
            continue
        if buy_data['open_pct'] >= limit_pct * 0.98:
            continue  # 一字涨停
        
        # 计算各种出场收益
        returns = {}
        
        # 持有1天收盘卖
        sell_d1 = get_td(buy_date, 1)
        if sell_d1 and code in stock_daily and sell_d1 in stock_daily[code]:
            sd1 = stock_daily[code][sell_d1]
            returns['hold1_close'] = (sd1['close'] / buy_price - 1) * 100 - 0.15
            
            # T+1止盈3%/止损5%/收盘兜底
            high1 = sd1['high']
            low1 = sd1['low']
            tp_hit = (high1 / buy_price - 1) * 100 >= 3
            sl_hit = (low1 / buy_price - 1) * 100 <= -5
            
            if tp_hit and not sl_hit:
                returns['tp3_sl5'] = 3.0 - 0.15
            elif sl_hit and not tp_hit:
                returns['tp3_sl5'] = -5.0 - 0.15
            elif tp_hit and sl_hit:
                # 都触发了，假设止损先触发（保守）
                returns['tp3_sl5'] = -5.0 - 0.15
            else:
                returns['tp3_sl5'] = (sd1['close'] / buy_price - 1) * 100 - 0.15
            
            # T+1止盈5%/止损3%
            tp5_hit = (high1 / buy_price - 1) * 100 >= 5
            sl3_hit = (low1 / buy_price - 1) * 100 <= -3
            if tp5_hit and not sl3_hit:
                returns['tp5_sl3'] = 5.0 - 0.15
            elif sl3_hit and not tp5_hit:
                returns['tp5_sl3'] = -3.0 - 0.15
            elif tp5_hit and sl3_hit:
                returns['tp5_sl3'] = -3.0 - 0.15
            else:
                returns['tp5_sl3'] = (sd1['close'] / buy_price - 1) * 100 - 0.15
            
            # 持有期最高
            returns['max_high1'] = (high1 / buy_price - 1) * 100
        
        # 持有2天
        sell_d2 = get_td(buy_date, 2)
        if sell_d2 and code in stock_daily and sell_d2 in stock_daily[code]:
            returns['hold2_close'] = (stock_daily[code][sell_d2]['close'] / buy_price - 1) * 100 - 0.15
        
        # 持有3天
        sell_d3 = get_td(buy_date, 3)
        if sell_d3 and code in stock_daily and sell_d3 in stock_daily[code]:
            returns['hold3_close'] = (stock_daily[code][sell_d3]['close'] / buy_price - 1) * 100 - 0.15
        
        if not returns:
            continue
        
        # 综合评分
        score = concept_score
        score *= (1 + change / 10)
        score *= (1 + min(amount_wan, 100000) / 50000)
        if is_limit_up: score *= 1.5
        if is_lianban: score *= 2.0
        
        all_candidates.append({
            'signal_date': date_int,
            'buy_date': buy_date,
            'code': code,
            'name': code_to_name.get(code, ''),
            'change_pct': change,
            'amount_wan': amount_wan,
            'is_limit_up': is_limit_up,
            'is_lianban': is_lianban,
            'concept_score': concept_score,
            'total_score': score,
            'matched': ','.join(matched),
            'above_ma5': above_ma5,
            'max_heat': max_heat,
            'returns': returns,
        })

print(f"总候选: {len(all_candidates)}条")

# 转DataFrame方便后续操作
cand_df = pd.DataFrame(all_candidates)

# ═══════════════════════════════════════
# 网格搜索
# ═══════════════════════════════════════
print("\n网格搜索...\n")

results = []

for top_n in [1, 2, 3]:
    for min_change in [7, 9.5]:
        for min_amount in [5000, 10000, 30000]:
            for only_limit in [False, True]:
                for only_lianban in [False, True]:
                    if only_lianban and not only_limit:
                        continue
                    for use_ma5 in [False, True]:
                        for min_heat in [0, 50, 100]:
                            for exit_strat in ['hold1_close', 'tp3_sl5', 'tp5_sl3', 'hold2_close', 'hold3_close']:
                                
                                # 过滤
                                mask = pd.Series([True] * len(cand_df))
                                if min_change > 5:
                                    mask &= cand_df['change_pct'] >= min_change
                                if min_amount > 0:
                                    mask &= cand_df['amount_wan'] >= min_amount
                                if only_limit:
                                    mask &= cand_df['is_limit_up']
                                if only_lianban:
                                    mask &= cand_df['is_lianban']
                                if use_ma5:
                                    mask &= cand_df['above_ma5']
                                if min_heat > 0:
                                    mask &= cand_df['max_heat'] >= min_heat
                                
                                filtered = cand_df[mask].copy()
                                if len(filtered) < 10:
                                    continue
                                
                                # 检查exit_strat存在
                                has_ret = filtered['returns'].apply(lambda x: exit_strat in x)
                                filtered = filtered[has_ret]
                                if len(filtered) < 10:
                                    continue
                                
                                # 按日选TOP N
                                rets = []
                                buy_dates = []
                                for d, group in filtered.groupby('signal_date'):
                                    top = group.nlargest(top_n, 'total_score')
                                    for _, row in top.iterrows():
                                        rets.append(row['returns'][exit_strat])
                                        buy_dates.append(row['buy_date'])
                                
                                if len(rets) < 10:
                                    continue
                                
                                avg = np.mean(rets)
                                win = np.mean([1 if r > 0 else 0 for r in rets]) * 100
                                total = sum(rets)
                                
                                months = {}
                                for r, bd in zip(rets, buy_dates):
                                    m = bd // 100
                                    months.setdefault(m, []).append(r)
                                monthly_sums = [sum(v) for v in months.values()]
                                pos_m = sum(1 for s in monthly_sums if s > 0)
                                tot_m = len(monthly_sums)
                                
                                # 复利
                                cap = 100000
                                for r in rets:
                                    cap *= (1 + r / 100)
                                compound = (cap / 100000 - 1) * 100
                                
                                results.append({
                                    'TOP': top_n, '涨幅': min_change, '成交额': min_amount,
                                    '涨停': only_limit, '连板': only_lianban,
                                    'MA5': use_ma5, '热度': min_heat, '出场': exit_strat,
                                    '笔数': len(rets), '均值': avg, '胜率': win,
                                    '利润和': total, '复利%': compound,
                                    '月+': f"{pos_m}/{tot_m}",
                                    '月均': total / tot_m if tot_m > 0 else 0,
                                })

res_df = pd.DataFrame(results)

# 按复利排序(利润最大化)
res_df = res_df.sort_values('复利%', ascending=False)

print("=" * 110)
print("TOP30 按复利收益排序")
print("=" * 110)
cols = ['TOP','涨幅','成交额','涨停','连板','MA5','热度','出场','笔数','均值','胜率','利润和','复利%','月+','月均']
header = f"{'T':>1} {'涨':>4} {'额':>5} {'停':>1} {'连':>1} {'MA':>2} {'热':>3} {'出场':<12} {'笔':>3} {'均':>7} {'胜':>4} {'利':>7} {'复利':>8} {'月':>5} {'月均':>6}"
print(header)
print("-" * 110)
for _, r in res_df.head(30).iterrows():
    lt = 'Y' if r['涨停'] else 'N'
    lb = 'Y' if r['连板'] else 'N'
    ma = 'Y' if r['MA5'] else 'N'
    print(f" {int(r['TOP']):>1} {r['涨幅']:>4.1f} {int(r['成交额']):>5} {lt} {lb}  {ma} {int(r['热度']):>3} {r['出场']:<12} {int(r['笔数']):>3} {r['均值']:>+6.2f}% {r['胜率']:>3.0f}% {r['利润和']:>+6.0f}% {r['复利%']:>+7.0f}% {r['月+']:<5} {r['月均']:>+5.0f}%")

# 按月一致性排序
print(f"\n{'='*110}")
print("TOP20 按月一致性+均值 (≥30笔)")
print("=" * 110)
res30 = res_df[res_df['笔数'] >= 30].copy()
res30['月正率'] = res30['月+'].apply(lambda x: int(x.split('/')[0]) / int(x.split('/')[1]) if '/' in str(x) else 0)
res30 = res30.sort_values(['月正率', '均值'], ascending=[False, False])
print(header)
print("-" * 110)
for _, r in res30.head(20).iterrows():
    lt = 'Y' if r['涨停'] else 'N'
    lb = 'Y' if r['连板'] else 'N'
    ma = 'Y' if r['MA5'] else 'N'
    print(f" {int(r['TOP']):>1} {r['涨幅']:>4.1f} {int(r['成交额']):>5} {lt} {lb}  {ma} {int(r['热度']):>3} {r['出场']:<12} {int(r['笔数']):>3} {r['均值']:>+6.2f}% {r['胜率']:>3.0f}% {r['利润和']:>+6.0f}% {r['复利%']:>+7.0f}% {r['月+']:<5} {r['月均']:>+5.0f}%")

# ═══════════════════════════════════════
# 最优策略详细分析
# ═══════════════════════════════════════
best = res_df.iloc[0]
print(f"\n{'='*110}")
print(f"★★★ 最优策略(复利最大化)")
print(f"  TOP{int(best['TOP'])} 涨幅≥{best['涨幅']}% 成交额≥{int(best['成交额'])}万 涨停={'Y' if best['涨停'] else 'N'} 连板={'Y' if best['连板'] else 'N'} MA5={'Y' if best['MA5'] else 'N'} 热度≥{int(best['热度'])} 出场={best['出场']}")
print(f"  {int(best['笔数'])}笔 均值{best['均值']:+.2f}% 胜率{best['胜率']:.0f}% 利润{best['利润和']:+.0f}% 复利{best['复利%']:+.0f}% 月{best['月+']} 月均{best['月均']:+.0f}%")
print(f"{'='*110}")

# 详细提取
exit_key = best['出场']
mask = pd.Series([True] * len(cand_df))
if best['涨幅'] > 5: mask &= cand_df['change_pct'] >= best['涨幅']
if best['成交额'] > 0: mask &= cand_df['amount_wan'] >= best['成交额']
if best['涨停']: mask &= cand_df['is_limit_up']
if best['连板']: mask &= cand_df['is_lianban']
if best['MA5']: mask &= cand_df['above_ma5']
if best['热度'] > 0: mask &= cand_df['max_heat'] >= best['热度']

filtered = cand_df[mask].copy()
filtered = filtered[filtered['returns'].apply(lambda x: exit_key in x)]

trades = []
for d, group in filtered.groupby('signal_date'):
    top = group.nlargest(int(best['TOP']), 'total_score')
    for _, row in top.iterrows():
        trades.append({
            '信号日': row['signal_date'],
            '买入日': row['buy_date'],
            '代码': row['code'],
            '名称': row['name'],
            '信号涨幅': row['change_pct'],
            '涨停': row['is_limit_up'],
            '连板': row['is_lianban'],
            '成交额万': row['amount_wan'],
            '概念分': row['concept_score'],
            '概念': row['matched'],
            '大盘MA5上': row['above_ma5'],
            '收益%': row['returns'][exit_key],
            '最高%': row['returns'].get('max_high1', 0),
        })

trade_df = pd.DataFrame(trades)
trade_df['月'] = trade_df['买入日'] // 100

monthly = trade_df.groupby('月').agg(
    笔=('收益%', 'count'),
    均值=('收益%', 'mean'),
    胜率=('收益%', lambda x: (x>0).mean()*100),
    利润=('收益%', 'sum'),
).reset_index()

print(f"\n月度:")
for _, r in monthly.iterrows():
    marker = ' ★' if r['利润'] > 15 else (' ▼' if r['利润'] < -10 else '')
    print(f"  {int(r['月'])} {int(r['笔']):>3}笔 均{r['均值']:>+6.2f}% 胜{r['胜率']:>4.0f}% 利{r['利润']:>+7.1f}%{marker}")

# 复利曲线
cap = 100000
max_cap = cap
max_dd = 0
for _, r in trade_df.sort_values('买入日').iterrows():
    cap *= (1 + r['收益%'] / 100)
    max_cap = max(max_cap, cap)
    dd = (cap / max_cap - 1) * 100
    max_dd = min(max_dd, dd)

print(f"\n复利: 10万 → {cap/10000:.1f}万 ({(cap/100000-1)*100:+.0f}%) 最大回撤{max_dd:.1f}%")

# 概念表现
print(f"\n概念:")
cs = {}
for _, r in trade_df.iterrows():
    for c in r['概念'].split(','):
        c = c.strip()
        if c:
            cs.setdefault(c, []).append(r['收益%'])
for c, rets in sorted(cs.items(), key=lambda x: sum(x[1]), reverse=True):
    if len(rets) >= 3:
        print(f"  {c:<12} {len(rets):>3}笔 均{np.mean(rets):>+6.2f}% 胜{np.mean([1 if r>0 else 0 for r in rets])*100:>3.0f}% 利{sum(rets):>+6.0f}%")

trade_df.to_csv(f'{OUTPUT_DIR}新闻驱动V3_最优信号.csv', index=False, encoding='utf-8-sig')
print(f"\n保存: {OUTPUT_DIR}新闻驱动V3_最优信号.csv")
print("=" * 110)
