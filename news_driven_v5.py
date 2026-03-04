#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻驱动选股 V5 - 加入技术指标过滤
在V4基础上加入自算RSI和波动率，用于筛选更优信号
核心假设(已验证): RSI高+波动率高=活跃强势股=买入后更容易继续涨

思路:
1. 用日线cache自算每只股票的RSI(14)和波动率(14日)
2. 新闻选股候选出来后，按RSI/波动率过滤
3. 网格搜索找最佳RSI/波动率阈值
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
    '锂电': {'锂电': 3}, '核电': {'核电': 3}, '风电': {'风电': 3},
    '军工': {'军工': 3, '国防': 3, '航空': 2},
    '航天': {'航天': 3, '商业航天': 3, '卫星': 2},
    '歼': {'军工': 3, '航空': 3}, '导弹': {'军工': 3},
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

print("=" * 90)
print("新闻驱动选股 V5 - 技术指标增强版")
print("=" * 90)

# ── 加载数据 ──
print("\n加载K线缓存...")
with open(CACHE_FILE, 'rb') as f:
    daily_data = pickle.load(f)
trade_dates = sorted(daily_data.keys())
print(f"  {trade_dates[0]}~{trade_dates[-1]}, {len(trade_dates)}天")

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

# ── 自算RSI(14)和波动率(14日) ──
print("计算技术指标(RSI14 + 波动率14)...")
# 对每只股票,用日线close序列算RSI和波动率
stock_rsi = {}   # {code: {date: rsi}}
stock_vol = {}   # {code: {date: volatility}}

for code, dates_dict in stock_daily.items():
    dates_sorted = sorted(dates_dict.keys())
    if len(dates_sorted) < 15:
        continue
    
    closes = [dates_dict[d]['close'] for d in dates_sorted]
    
    # RSI(14)
    rsi_dict = {}
    for i in range(14, len(dates_sorted)):
        gains = []
        losses = []
        for j in range(i-13, i+1):
            delta = closes[j] - closes[j-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - 100 / (1 + rs)
        rsi_dict[dates_sorted[i]] = rsi
    stock_rsi[code] = rsi_dict
    
    # 波动率(14日收益率标准差 * sqrt(252) * 100)
    vol_dict = {}
    for i in range(14, len(dates_sorted)):
        rets = []
        for j in range(i-13, i+1):
            if closes[j-1] > 0:
                rets.append((closes[j] / closes[j-1] - 1))
        if len(rets) >= 10:
            vol_dict[dates_sorted[i]] = np.std(rets) * np.sqrt(252) * 100
    stock_vol[code] = vol_dict

print(f"  RSI计算: {len(stock_rsi)}只")

# ── 大盘状态 ──
print("大盘状态...")
market_avg = {}
for d, stocks in daily_data.items():
    changes = [s['change_pct'] for s in stocks if abs(s['change_pct']) < 20]
    if changes:
        market_avg[d] = np.mean(changes)

market_ma5 = {}
market_state = {}
for i, d in enumerate(trade_dates):
    if d in market_avg:
        vals = []
        for j in range(max(0, i-4), i+1):
            if trade_dates[j] in market_avg:
                vals.append(market_avg[trade_dates[j]])
        if len(vals) >= 5:
            market_ma5[d] = np.mean(vals)
            if market_avg[d] > 0.5:
                market_state[d] = 1
            elif market_avg[d] > market_ma5[d]:
                market_state[d] = 0
            else:
                market_state[d] = -1
        else:
            market_state[d] = 0
    else:
        market_state[d] = 0

# ── 新闻 ──
print("加载新闻...")
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
print(f"  {len(news)}条")

# ── 概念 ──
concepts_df = pd.read_excel(CONCEPTS_FILE)
concepts_df['商品代码'] = concepts_df['商品代码'].astype(str).str.zfill(6)
code_to_concepts = {k: str(v) for k, v in zip(concepts_df['商品代码'], concepts_df['同花顺概念old'].fillna(''))}
code_to_name = dict(zip(concepts_df['商品代码'], concepts_df['名称'].fillna('')))

# ── 动态热门概念 ──
print("概念涨停排行...")
daily_concept_zt = {}
for d, stocks in daily_data.items():
    concept_zt = Counter()
    for s in stocks:
        code = s['code']
        if code.startswith('8') or code.startswith('4'):
            continue
        is_20pct = code.startswith('3') or code.startswith('688')
        limit_pct = 20 if is_20pct else 10
        if s['change_pct'] >= limit_pct * 0.98:
            for c in code_to_concepts.get(code, '').split(';'):
                c = c.strip()
                if c and len(c) <= 8:
                    concept_zt[c] += 1
    daily_concept_zt[d] = concept_zt

def get_hot_concepts(date_int, lookback=10, top_n=15):
    idx = trade_dates.index(date_int)
    total = Counter()
    for i in range(max(0, idx - lookback), idx + 1):
        d = trade_dates[i]
        if d in daily_concept_zt:
            total.update(daily_concept_zt[d])
    return set(c for c, _ in total.most_common(top_n))

# ── 新闻热度 ──
print("新闻热度...")
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
print(f"  {len(daily_heat)}天有信号")

# ── 构建候选(含技术指标) ──
print("构建候选...")
all_candidates = []
rsi_missing = 0

for date_int in daily_heat:
    if date_int not in daily_data:
        continue
    
    heat = daily_heat[date_int]
    top_concepts = [c for c, _ in heat.most_common(8)]
    max_heat = heat.most_common(1)[0][1] if heat else 0
    hot_concepts = get_hot_concepts(date_int, lookback=10, top_n=15)
    stocks = daily_data[date_int]
    mstate = market_state.get(date_int, 0)
    
    for s in stocks:
        code = s['code']
        if code.startswith('8') or code.startswith('4'):
            continue
        
        concepts_str = code_to_concepts.get(code, '')
        concept_score = 0
        matched = []
        for hc in top_concepts:
            if hc in concepts_str:
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
        
        prev_change = 0
        prev_d = get_td(date_int, -1)
        if prev_d and code in stock_daily and prev_d in stock_daily[code]:
            prev_change = stock_daily[code][prev_d]['change_pct']
        is_lianban = prev_change >= 9.5 and is_limit_up
        
        buy_date = get_td(date_int, 1)
        if buy_date is None:
            continue
        if code not in stock_daily or buy_date not in stock_daily[code]:
            continue
        buy_data = stock_daily[code][buy_date]
        buy_price = buy_data['open']
        if buy_price <= 0:
            continue
        if buy_data.get('open_pct', 0) >= limit_pct * 0.98:
            continue
        
        in_hot = any(m in hot_concepts for m in matched)
        
        # 技术指标
        rsi14 = None
        vol14 = None
        if code in stock_rsi and date_int in stock_rsi[code]:
            rsi14 = stock_rsi[code][date_int]
        if code in stock_vol and date_int in stock_vol[code]:
            vol14 = stock_vol[code][date_int]
        
        if rsi14 is None:
            rsi_missing += 1
        
        # 周涨幅(近5日)
        week_change = 0
        idx = trade_dates.index(date_int)
        if idx >= 5 and code in stock_daily:
            d5_ago = trade_dates[idx - 5]
            if d5_ago in stock_daily[code]:
                c5 = stock_daily[code][d5_ago]['close']
                if c5 > 0:
                    week_change = (s['close'] / c5 - 1) * 100
        
        # 出场收益
        returns = {}
        sell_d1 = get_td(buy_date, 1)
        if sell_d1 and code in stock_daily and sell_d1 in stock_daily[code]:
            sd1 = stock_daily[code][sell_d1]
            raw1 = (sd1['close'] / buy_price - 1) * 100
            h1 = (sd1['high'] / buy_price - 1) * 100
            l1 = (sd1['low'] / buy_price - 1) * 100
            
            if l1 <= -8:
                returns['hold1'] = -8.15
            else:
                returns['hold1'] = raw1 - 0.15
            
            tp3 = h1 >= 3
            sl5 = l1 <= -5
            if tp3 and not sl5: returns['tp3sl5'] = 2.85
            elif sl5 and not tp3: returns['tp3sl5'] = -5.15
            elif tp3 and sl5: returns['tp3sl5'] = -5.15
            else: returns['tp3sl5'] = raw1 - 0.15
        
        sell_d2 = get_td(buy_date, 2)
        if sell_d2 and code in stock_daily and sell_d2 in stock_daily[code]:
            sd2 = stock_daily[code][sell_d2]
            raw2 = (sd2['close'] / buy_price - 1) * 100
            low_min = 999
            for dd in [get_td(buy_date, 1), sell_d2]:
                if dd and code in stock_daily and dd in stock_daily[code]:
                    low_min = min(low_min, (stock_daily[code][dd]['low'] / buy_price - 1) * 100)
            returns['hold2'] = -8.15 if low_min <= -8 else raw2 - 0.15
        
        sell_d3 = get_td(buy_date, 3)
        if sell_d3 and code in stock_daily and sell_d3 in stock_daily[code]:
            sd3 = stock_daily[code][sell_d3]
            raw3 = (sd3['close'] / buy_price - 1) * 100
            low_min = 999
            for dd_off in [1, 2, 3]:
                dd = get_td(buy_date, dd_off)
                if dd and code in stock_daily and dd in stock_daily[code]:
                    low_min = min(low_min, (stock_daily[code][dd]['low'] / buy_price - 1) * 100)
            returns['hold3'] = -8.15 if low_min <= -8 else raw3 - 0.15
        
        if not returns:
            continue
        
        score = concept_score * (1 + change / 10) * (1 + min(amount_wan, 100000) / 50000)
        if is_limit_up: score *= 1.5
        if is_lianban: score *= 2.0
        if in_hot: score *= 1.5
        if rsi14 and rsi14 > 70: score *= 1.2  # RSI强势加分
        
        all_candidates.append({
            'signal_date': date_int,
            'buy_date': buy_date,
            'code': code,
            'name': code_to_name.get(code, ''),
            'change_pct': change,
            'amount_wan': amount_wan,
            'is_limit_up': is_limit_up,
            'is_lianban': is_lianban,
            'total_score': score,
            'matched': ','.join(matched),
            'market_state': mstate,
            'max_heat': max_heat,
            'in_hot': in_hot,
            'rsi14': rsi14,
            'vol14': vol14,
            'week_change': week_change,
            'returns': returns,
        })

print(f"  候选: {len(all_candidates)}条 (RSI缺失: {rsi_missing})")
cand_df = pd.DataFrame(all_candidates)

# ══ 先看技术指标对收益的影响 ══
print("\n" + "=" * 90)
print("技术指标对收益的影响分析")
print("=" * 90)

# 只看涨停+连板的(我们的主力策略)
lb_mask = cand_df['is_limit_up'] & cand_df['is_lianban']
lb_df = cand_df[lb_mask].copy()
lb_df = lb_df[lb_df['returns'].apply(lambda x: 'hold1' in x)]
lb_df['ret1'] = lb_df['returns'].apply(lambda x: x['hold1'])

print(f"\n涨停+连板候选: {len(lb_df)}条")

# RSI分组
rsi_valid = lb_df[lb_df['rsi14'].notna()].copy()
print(f"有RSI数据: {len(rsi_valid)}条")
if len(rsi_valid) > 20:
    for name, lo, hi in [('RSI<50', 0, 50), ('RSI 50-65', 50, 65), ('RSI 65-75', 65, 75), ('RSI 75-85', 75, 85), ('RSI>85', 85, 101)]:
        sub = rsi_valid[(rsi_valid['rsi14'] >= lo) & (rsi_valid['rsi14'] < hi)]
        if len(sub) >= 3:
            avg = sub['ret1'].mean()
            win = (sub['ret1'] > 0).mean() * 100
            print(f"  {name:<12} {len(sub):>4}条 均{avg:>+6.2f}% 胜{win:>4.0f}%")

# 波动率分组
vol_valid = lb_df[lb_df['vol14'].notna()].copy()
print(f"有波动率数据: {len(vol_valid)}条")
if len(vol_valid) > 20:
    pcts = [0, 25, 50, 75, 100]
    bounds = np.percentile(vol_valid['vol14'], pcts)
    for i in range(4):
        sub = vol_valid[(vol_valid['vol14'] >= bounds[i]) & (vol_valid['vol14'] < bounds[i+1] + 0.01)]
        if len(sub) >= 3:
            avg = sub['ret1'].mean()
            win = (sub['ret1'] > 0).mean() * 100
            print(f"  Vol Q{i+1} ({bounds[i]:.0f}~{bounds[i+1]:.0f}) {len(sub):>4}条 均{avg:>+6.2f}% 胜{win:>4.0f}%")

# 周涨幅分组
print(f"周涨幅分组:")
for name, lo, hi in [('周跌<0%', -999, 0), ('周涨0~10%', 0, 10), ('周涨10~25%', 10, 25), ('周涨25~50%', 25, 50), ('周涨>50%', 50, 999)]:
    sub = lb_df[(lb_df['week_change'] >= lo) & (lb_df['week_change'] < hi)]
    if len(sub) >= 3:
        avg = sub['ret1'].mean()
        win = (sub['ret1'] > 0).mean() * 100
        print(f"  {name:<14} {len(sub):>4}条 均{avg:>+6.2f}% 胜{win:>4.0f}%")

# ═══════════════════════════════════════
# V5 网格搜索
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("V5 网格搜索")
print("=" * 90)

results = []

for top_n in [1, 2, 3]:
    for only_lianban in [True]:  # V5只看连板,已验证最强
        for min_amount in [5000, 10000]:
            for market_filter in ['none', 'no_weak']:
                for use_hot in [False, True]:
                    for rsi_min in [0, 60, 70, 80]:
                        for vol_min in [0, 30, 50, 70]:
                            for week_min in [0, 10, 20]:
                                for exit_strat in ['hold1', 'hold2', 'hold3', 'tp3sl5']:
                                    
                                    mask = cand_df['is_limit_up'] & cand_df['is_lianban']
                                    if min_amount > 0: mask &= cand_df['amount_wan'] >= min_amount
                                    if market_filter == 'no_weak': mask &= cand_df['market_state'] >= 0
                                    if use_hot: mask &= cand_df['in_hot']
                                    if rsi_min > 0: mask &= (cand_df['rsi14'].notna()) & (cand_df['rsi14'] >= rsi_min)
                                    if vol_min > 0: mask &= (cand_df['vol14'].notna()) & (cand_df['vol14'] >= vol_min)
                                    if week_min > 0: mask &= cand_df['week_change'] >= week_min
                                    
                                    filtered = cand_df[mask].copy()
                                    if len(filtered) < 8: continue
                                    has_ret = filtered['returns'].apply(lambda x: exit_strat in x)
                                    filtered = filtered[has_ret]
                                    if len(filtered) < 8: continue
                                    
                                    rets = []
                                    buy_dates_list = []
                                    for sd in sorted(filtered['signal_date'].unique()):
                                        group = filtered[filtered['signal_date'] == sd]
                                        top = group.nlargest(top_n, 'total_score')
                                        for _, row in top.iterrows():
                                            rets.append(row['returns'][exit_strat])
                                            buy_dates_list.append(row['buy_date'])
                                    
                                    if len(rets) < 8: continue
                                    
                                    avg_ret = np.mean(rets)
                                    win_rate = np.mean([1 if r > 0 else 0 for r in rets]) * 100
                                    total = sum(rets)
                                    
                                    months = {}
                                    for r, bd in zip(rets, buy_dates_list):
                                        m = bd // 100
                                        months.setdefault(m, []).append(r)
                                    monthly_sums = [sum(v) for v in months.values()]
                                    pos_m = sum(1 for s in monthly_sums if s > 0)
                                    tot_m = len(monthly_sums)
                                    worst = min(monthly_sums) if monthly_sums else 0
                                    m20 = sum(1 for s in monthly_sums if s >= 20)
                                    
                                    cap = 100000
                                    max_cap = cap
                                    max_dd = 0
                                    for r in rets:
                                        cap *= (1 + r / 100)
                                        max_cap = max(max_cap, cap)
                                        dd = (cap / max_cap - 1) * 100
                                        max_dd = min(max_dd, dd)
                                    compound = (cap / 100000 - 1) * 100
                                    
                                    results.append({
                                        'TOP': top_n, '额': min_amount,
                                        '大盘': market_filter[:6], '热门': use_hot,
                                        'RSI≥': rsi_min, 'Vol≥': vol_min, '周涨≥': week_min,
                                        '出场': exit_strat,
                                        '笔': len(rets), '均': avg_ret, '胜%': win_rate,
                                        '利': total, '复利%': compound, 'DD%': max_dd,
                                        '月+': f"{pos_m}/{tot_m}",
                                        '月均': total / tot_m if tot_m > 0 else 0,
                                        '差月': worst,
                                        '月≥20': f"{m20}/{tot_m}",
                                    })

res_df = pd.DataFrame(results)
print(f"有效组合: {len(res_df)}种")

# ═══════════════════════════════════════
# 排序输出
# ═══════════════════════════════════════
res_df = res_df.sort_values('复利%', ascending=False)

hdr = f"{'T':>1} {'额':>5} {'大盘':>6} {'热':>1} {'RSI':>3} {'Vol':>3} {'周':>2} {'出场':<7} {'笔':>3} {'均':>7} {'胜':>4} {'利':>7} {'复利':>8} {'DD':>6} {'月+':>5} {'月均':>6} {'差':>6} {'≥20':>5}"

print(f"\n{'='*120}")
print("TOP20 复利最大")
print("=" * 120)
print(hdr)
print("-" * 120)
for _, r in res_df.head(20).iterrows():
    ht = 'Y' if r['热门'] else 'N'
    print(f" {int(r['TOP']):>1} {int(r['额']):>5} {r['大盘']:>6} {ht} {int(r['RSI≥']):>3} {int(r['Vol≥']):>3} {int(r['周涨≥']):>2} {r['出场']:<7} {int(r['笔']):>3} {r['均']:>+6.2f}% {r['胜%']:>3.0f}% {r['利']:>+6.0f}% {r['复利%']:>+7.0f}% {r['DD%']:>+5.0f}% {r['月+']:>5} {r['月均']:>+5.0f}% {r['差月']:>+5.0f}% {r['月≥20']:>5}")

# 月正率排序
print(f"\n{'='*120}")
print("TOP20 月正率最高 (≥15笔)")
print("=" * 120)
res15 = res_df[res_df['笔'] >= 15].copy()
res15['月正率'] = res15['月+'].apply(lambda x: int(x.split('/')[0]) / int(x.split('/')[1]) if '/' in str(x) else 0)
res15 = res15.sort_values(['月正率', '均'], ascending=[False, False])
print(hdr)
print("-" * 120)
for _, r in res15.head(20).iterrows():
    ht = 'Y' if r['热门'] else 'N'
    print(f" {int(r['TOP']):>1} {int(r['额']):>5} {r['大盘']:>6} {ht} {int(r['RSI≥']):>3} {int(r['Vol≥']):>3} {int(r['周涨≥']):>2} {r['出场']:<7} {int(r['笔']):>3} {r['均']:>+6.2f}% {r['胜%']:>3.0f}% {r['利']:>+6.0f}% {r['复利%']:>+7.0f}% {r['DD%']:>+5.0f}% {r['月+']:>5} {r['月均']:>+5.0f}% {r['差月']:>+5.0f}% {r['月≥20']:>5}")

# 综合排序: 复利/回撤比
print(f"\n{'='*120}")
print("TOP20 综合(复利/回撤 + 月正率)")
print("=" * 120)
res_all = res_df[res_df['笔'] >= 10].copy()
res_all['月正率'] = res_all['月+'].apply(lambda x: int(x.split('/')[0]) / int(x.split('/')[1]) if '/' in str(x) else 0)
res_all['综合'] = (res_all['复利%'] / (abs(res_all['DD%']) + 1)) * res_all['月正率']
res_all = res_all.sort_values('综合', ascending=False)
print(hdr)
print("-" * 120)
for _, r in res_all.head(20).iterrows():
    ht = 'Y' if r['热门'] else 'N'
    print(f" {int(r['TOP']):>1} {int(r['额']):>5} {r['大盘']:>6} {ht} {int(r['RSI≥']):>3} {int(r['Vol≥']):>3} {int(r['周涨≥']):>2} {r['出场']:<7} {int(r['笔']):>3} {r['均']:>+6.2f}% {r['胜%']:>3.0f}% {r['利']:>+6.0f}% {r['复利%']:>+7.0f}% {r['DD%']:>+5.0f}% {r['月+']:>5} {r['月均']:>+5.0f}% {r['差月']:>+5.0f}% {r['月≥20']:>5}")

# ═══════════════════════════════════════
# 推荐策略详细分析
# ═══════════════════════════════════════
# 选综合排名第1
best = res_all.iloc[0]
print(f"\n{'='*100}")
print(f"★★★ V5推荐策略 ★★★")
print(f"  TOP{int(best['TOP'])} 额≥{int(best['额'])}万 大盘={best['大盘']} 热门={'Y' if best['热门'] else 'N'} RSI≥{int(best['RSI≥'])} Vol≥{int(best['Vol≥'])} 周涨≥{int(best['周涨≥'])}% 出场={best['出场']}")
print(f"  {int(best['笔'])}笔 均{best['均']:+.2f}% 胜{best['胜%']:.0f}% 利{best['利']:+.0f}% 复利{best['复利%']:+.0f}% DD{best['DD%']:.0f}% 月{best['月+']} 月≥20%:{best['月≥20']}")

# 提取详细交易
exit_key = best['出场']
mask = cand_df['is_limit_up'] & cand_df['is_lianban']
if best['额'] > 0: mask &= cand_df['amount_wan'] >= best['额']
if best['大盘'] == 'no_wea': mask &= cand_df['market_state'] >= 0
if best['热门']: mask &= cand_df['in_hot']
if best['RSI≥'] > 0: mask &= (cand_df['rsi14'].notna()) & (cand_df['rsi14'] >= best['RSI≥'])
if best['Vol≥'] > 0: mask &= (cand_df['vol14'].notna()) & (cand_df['vol14'] >= best['Vol≥'])
if best['周涨≥'] > 0: mask &= cand_df['week_change'] >= best['周涨≥']

filtered = cand_df[mask].copy()
filtered = filtered[filtered['returns'].apply(lambda x: exit_key in x)]

trades = []
for sd in sorted(filtered['signal_date'].unique()):
    group = filtered[filtered['signal_date'] == sd]
    top = group.nlargest(int(best['TOP']), 'total_score')
    for _, row in top.iterrows():
        trades.append({
            '信号日': row['signal_date'],
            '买入日': row['buy_date'],
            '代码': row['code'],
            '名称': row['name'],
            '涨幅': round(row['change_pct'], 1),
            '额万': int(row['amount_wan']),
            '概念': row['matched'],
            'RSI': round(row['rsi14'], 1) if row['rsi14'] is not None and not np.isnan(row['rsi14']) else '-',
            '波动': round(row['vol14'], 1) if row['vol14'] is not None and not np.isnan(row['vol14']) else '-',
            '周涨': round(row['week_change'], 1),
            '大盘': '强' if row['market_state'] == 1 else ('中' if row['market_state'] == 0 else '弱'),
            '收益%': round(row['returns'][exit_key], 2),
        })

trade_df = pd.DataFrame(trades)
trade_df['月'] = trade_df['买入日'] // 100

# 月度
print(f"\n月度:")
cap = 100000
monthly = trade_df.groupby('月').agg(
    笔=('收益%', 'count'),
    均值=('收益%', 'mean'),
    胜率=('收益%', lambda x: (x>0).mean()*100),
    利润=('收益%', 'sum'),
).reset_index()

for _, r in monthly.iterrows():
    month_rets = trade_df[trade_df['月'] == r['月']]['收益%'].values
    month_start = cap
    for ret in month_rets:
        cap *= (1 + ret / 100)
    pct = (cap / month_start - 1) * 100
    pnl_wan = (cap - month_start) / 10000
    ok = '✅' if pct >= 20 else ('⚠️' if pct >= 0 else '❌')
    print(f"  {int(r['月'])} {int(r['笔']):>3}笔 均{r['均值']:>+6.2f}% 胜{r['胜率']:>4.0f}% 利{r['利润']:>+7.1f}% 账户{cap/10000:>7.1f}万 月{pct:>+6.1f}% {ok}")

print(f"\n  📊 10万 → {cap/10000:.1f}万 ({(cap/100000-1)*100:+.0f}%)")

# 逐笔
print(f"\n全部交易:")
print(f"{'信号日':>8} {'买入日':>8} {'代码':>6} {'名称':<8} {'涨':>5} {'额万':>7} {'概念':<16} {'RSI':>5} {'波动':>5} {'周涨':>5} {'盘':>1} {'收益':>6}")
print("-" * 110)
cap2 = 100000
for _, row in trade_df.sort_values('买入日').iterrows():
    ret = row['收益%']
    cap2 *= (1 + ret / 100)
    flag = '✅' if ret > 0 else '❌'
    rsi_str = f"{row['RSI']:>5}" if row['RSI'] != '-' else '    -'
    vol_str = f"{row['波动']:>5}" if row['波动'] != '-' else '    -'
    print(f" {row['信号日']:>8} {row['买入日']:>8} {row['代码']:>6} {row['名称']:<8} {row['涨幅']:>+5.1f} {row['额万']:>7} {row['概念']:<16} {rsi_str} {vol_str} {row['周涨']:>+5.1f} {row['大盘']} {ret:>+5.2f}% {flag} [{cap2/10000:.1f}万]")

# 保存
trade_df.to_csv(f'{OUTPUT_DIR}新闻驱动V5_最优信号.csv', index=False, encoding='utf-8-sig')
print(f"\n保存: {OUTPUT_DIR}新闻驱动V5_最优信号.csv")
print("=" * 100)
