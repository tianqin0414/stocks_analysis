#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻驱动选股 V4 - 目标月均20%
核心改进:
1. 大盘过滤: 全市场均涨幅5日均线 < 0 时不交易
2. 连亏暂停: 连续N笔亏损后暂停M天
3. 动态概念: 只做近20日涨停概念前N名的概念(而非固定白名单)
4. 龙头集中: 只选当日信号最强的TOP1/2
5. 灵活持仓: 测试hold1/2/3 + 止盈止损组合
6. 单笔止损: 最大亏损-8%强制平仓(用hold日low模拟)
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

# ── 加载数据 ──
print("=" * 90)
print("新闻驱动选股 V4 - 目标月均20%")
print("=" * 90)

print("\n加载数据...")
with open(CACHE_FILE, 'rb') as f:
    daily_data = pickle.load(f)
trade_dates = sorted(daily_data.keys())
print(f"  交易日: {trade_dates[0]}~{trade_dates[-1]}, {len(trade_dates)}天")

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

# 全市场大盘状态
print("构建大盘状态...")
market_avg = {}
for d, stocks in daily_data.items():
    changes = [s['change_pct'] for s in stocks if abs(s['change_pct']) < 20]
    if changes:
        market_avg[d] = np.mean(changes)

# 5日均线 & 大盘判定
market_ma5 = {}
market_state = {}  # 1=强, 0=中, -1=弱
for i, d in enumerate(trade_dates):
    if d in market_avg:
        vals = []
        for j in range(max(0, i-4), i+1):
            if trade_dates[j] in market_avg:
                vals.append(market_avg[trade_dates[j]])
        if len(vals) >= 5:
            market_ma5[d] = np.mean(vals)
            if market_avg[d] > 0.5:
                market_state[d] = 1  # 强势
            elif market_avg[d] > market_ma5[d]:
                market_state[d] = 0  # 中性偏多
            else:
                market_state[d] = -1  # 弱势
        else:
            market_state[d] = 0
    else:
        market_state[d] = 0

strong_days = sum(1 for v in market_state.values() if v == 1)
weak_days = sum(1 for v in market_state.values() if v == -1)
print(f"  强势{strong_days}天 中性{len(market_state)-strong_days-weak_days}天 弱势{weak_days}天")

# 新闻
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
print(f"  新闻: {len(news)}条")

# 概念
concepts_df = pd.read_excel(CONCEPTS_FILE)
concepts_df['商品代码'] = concepts_df['商品代码'].astype(str).str.zfill(6)
code_to_concepts = {k: str(v) for k, v in zip(concepts_df['商品代码'], concepts_df['同花顺概念old'].fillna(''))}
code_to_name = dict(zip(concepts_df['商品代码'], concepts_df['名称'].fillna('')))

# ── 预计算每日概念涨停排行(动态概念筛选用) ──
print("预计算概念涨停排行...")
# 每日: 哪些概念有涨停股?统计数量
daily_concept_zt = {}  # date -> {concept: zt_count}
for d, stocks in daily_data.items():
    concept_zt = Counter()
    for s in stocks:
        code = s['code']
        if code.startswith('8') or code.startswith('4'):
            continue
        is_20pct = code.startswith('3') or code.startswith('688')
        limit_pct = 20 if is_20pct else 10
        if s['change_pct'] >= limit_pct * 0.98:
            concepts = code_to_concepts.get(code, '')
            for c in concepts.split(';'):
                c = c.strip()
                if c and len(c) <= 8:
                    concept_zt[c] += 1
    daily_concept_zt[d] = concept_zt

# 近N日的热门概念(滚动)
def get_hot_concepts(date_int, lookback=10, top_n=15):
    """获取近lookback个交易日涨停最多的概念"""
    idx = trade_dates.index(date_int)
    total = Counter()
    for i in range(max(0, idx - lookback), idx + 1):
        d = trade_dates[i]
        if d in daily_concept_zt:
            total.update(daily_concept_zt[d])
    return set(c for c, _ in total.most_common(top_n))

# ── 预计算新闻热度 ──
print("预计算新闻热度...")
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

print(f"  有信号: {len(daily_heat)}天")

# ── 构建全部候选 ──
print("构建候选...")
all_candidates = []

for date_int in daily_heat:
    if date_int not in daily_data:
        continue
    
    heat = daily_heat[date_int]
    top_concepts = [c for c, _ in heat.most_common(8)]
    max_heat = heat.most_common(1)[0][1] if heat else 0
    
    # 动态热门概念
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
        
        # 匹配的概念是否在近期热门中
        in_hot = any(m in hot_concepts for m in matched)
        # 匹配的概念中有哪些具体名称（后续概念过滤用）
        concept_names = set(concepts_str.split(';'))
        
        # 各种出场收益 + 单笔最大止损
        returns = {}
        
        # 持1天
        sell_d1 = get_td(buy_date, 1)
        if sell_d1 and code in stock_daily and sell_d1 in stock_daily[code]:
            sd1 = stock_daily[code][sell_d1]
            raw1 = (sd1['close'] / buy_price - 1) * 100
            h1 = (sd1['high'] / buy_price - 1) * 100
            l1 = (sd1['low'] / buy_price - 1) * 100
            
            # 纯持仓(带-8%硬止损)
            if l1 <= -8:
                returns['hold1'] = -8.15
            else:
                returns['hold1'] = raw1 - 0.15
            
            # 止盈3止损5
            tp3 = h1 >= 3
            sl5 = l1 <= -5
            if tp3 and not sl5: returns['tp3sl5'] = 2.85
            elif sl5 and not tp3: returns['tp3sl5'] = -5.15
            elif tp3 and sl5: returns['tp3sl5'] = -5.15
            else: returns['tp3sl5'] = raw1 - 0.15
            
            # 止盈5止损3
            tp5 = h1 >= 5
            sl3 = l1 <= -3
            if tp5 and not sl3: returns['tp5sl3'] = 4.85
            elif sl3 and not tp5: returns['tp5sl3'] = -3.15
            elif tp5 and sl3: returns['tp5sl3'] = -3.15
            else: returns['tp5sl3'] = raw1 - 0.15
            
            returns['max_h1'] = h1
        
        # 持2天
        sell_d2 = get_td(buy_date, 2)
        if sell_d2 and code in stock_daily and sell_d2 in stock_daily[code]:
            sd2 = stock_daily[code][sell_d2]
            raw2 = (sd2['close'] / buy_price - 1) * 100
            # 需要检查两天的low
            low_min = 999
            for dd in [get_td(buy_date, 1), sell_d2]:
                if dd and code in stock_daily and dd in stock_daily[code]:
                    low_min = min(low_min, (stock_daily[code][dd]['low'] / buy_price - 1) * 100)
            if low_min <= -8:
                returns['hold2'] = -8.15
            else:
                returns['hold2'] = raw2 - 0.15
        
        # 持3天
        sell_d3 = get_td(buy_date, 3)
        if sell_d3 and code in stock_daily and sell_d3 in stock_daily[code]:
            sd3 = stock_daily[code][sell_d3]
            raw3 = (sd3['close'] / buy_price - 1) * 100
            low_min = 999
            for dd_offset in [1, 2, 3]:
                dd = get_td(buy_date, dd_offset)
                if dd and code in stock_daily and dd in stock_daily[code]:
                    low_min = min(low_min, (stock_daily[code][dd]['low'] / buy_price - 1) * 100)
            if low_min <= -8:
                returns['hold3'] = -8.15
            else:
                returns['hold3'] = raw3 - 0.15
        
        if not returns:
            continue
        
        # 评分
        score = concept_score
        score *= (1 + change / 10)
        score *= (1 + min(amount_wan, 100000) / 50000)
        if is_limit_up: score *= 1.5
        if is_lianban: score *= 2.0
        if in_hot: score *= 1.5
        
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
            'market_state': mstate,
            'max_heat': max_heat,
            'in_hot': in_hot,
            'returns': returns,
        })

print(f"  候选: {len(all_candidates)}条")
cand_df = pd.DataFrame(all_candidates)

# ═══════════════════════════════════════
# V4 网格搜索 - 加入大盘过滤 + 连亏暂停 + 动态概念
# ═══════════════════════════════════════
print("\n" + "=" * 90)
print("V4 网格搜索")
print("=" * 90)

results = []

for top_n in [1, 2, 3]:
    for only_limit in [True]:  # 涨停是必须的
        for only_lianban in [False, True]:
            for min_amount in [5000, 10000, 30000]:
                for market_filter in ['none', 'no_weak', 'only_strong']:
                    for use_hot in [False, True]:  # 动态概念
                        for pause_after in [0, 2, 3]:  # 连亏N笔后暂停
                            for pause_days in [0, 1, 2] if pause_after > 0 else [0]:
                                for exit_strat in ['hold1', 'hold2', 'hold3', 'tp3sl5', 'tp5sl3']:
                                    
                                    mask = pd.Series([True] * len(cand_df))
                                    mask &= cand_df['is_limit_up']
                                    if only_lianban: mask &= cand_df['is_lianban']
                                    if min_amount > 0: mask &= cand_df['amount_wan'] >= min_amount
                                    
                                    if market_filter == 'no_weak':
                                        mask &= cand_df['market_state'] >= 0
                                    elif market_filter == 'only_strong':
                                        mask &= cand_df['market_state'] >= 1
                                    
                                    if use_hot:
                                        mask &= cand_df['in_hot']
                                    
                                    filtered = cand_df[mask].copy()
                                    if len(filtered) < 10: continue
                                    
                                    has_ret = filtered['returns'].apply(lambda x: exit_strat in x)
                                    filtered = filtered[has_ret]
                                    if len(filtered) < 10: continue
                                    
                                    # 按日期排序选股 + 连亏暂停逻辑
                                    rets = []
                                    buy_dates_list = []
                                    consec_loss = 0
                                    pause_until = 0  # 暂停到这个日期
                                    
                                    signal_dates_sorted = sorted(filtered['signal_date'].unique())
                                    for sd in signal_dates_sorted:
                                        group = filtered[filtered['signal_date'] == sd]
                                        top = group.nlargest(top_n, 'total_score')
                                        
                                        for _, row in top.iterrows():
                                            bd = row['buy_date']
                                            
                                            # 连亏暂停检查
                                            if pause_after > 0 and bd < pause_until:
                                                continue
                                            
                                            ret = row['returns'][exit_strat]
                                            rets.append(ret)
                                            buy_dates_list.append(bd)
                                            
                                            # 更新连亏
                                            if ret < 0:
                                                consec_loss += 1
                                                if pause_after > 0 and consec_loss >= pause_after:
                                                    # 暂停pause_days个交易日
                                                    pd_target = get_td(bd, pause_days)
                                                    if pd_target:
                                                        pause_until = pd_target
                                                    consec_loss = 0
                                            else:
                                                consec_loss = 0
                                    
                                    if len(rets) < 8: continue
                                    
                                    avg = np.mean(rets)
                                    win_rate = np.mean([1 if r > 0 else 0 for r in rets]) * 100
                                    total = sum(rets)
                                    
                                    months = {}
                                    for r, bd in zip(rets, buy_dates_list):
                                        m = bd // 100
                                        months.setdefault(m, []).append(r)
                                    monthly_sums = [sum(v) for v in months.values()]
                                    pos_m = sum(1 for s in monthly_sums if s > 0)
                                    tot_m = len(monthly_sums)
                                    neg_months = [s for s in monthly_sums if s < 0]
                                    worst_month = min(monthly_sums) if monthly_sums else 0
                                    
                                    # 月均达标率(>=20%)
                                    m20_count = sum(1 for s in monthly_sums if s >= 20)
                                    
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
                                        'TOP': top_n, '连板': only_lianban,
                                        '成交额': min_amount, '大盘': market_filter,
                                        '热门': use_hot,
                                        '连亏停': f"{pause_after}/{pause_days}" if pause_after > 0 else 'N',
                                        '出场': exit_strat,
                                        '笔': len(rets), '均': avg, '胜%': win_rate,
                                        '利': total, '复利%': compound, 'DD%': max_dd,
                                        '月+': f"{pos_m}/{tot_m}",
                                        '月均': total / tot_m if tot_m > 0 else 0,
                                        '最差月': worst_month,
                                        '月≥20%': f"{m20_count}/{tot_m}",
                                    })

res_df = pd.DataFrame(results)
print(f"有效组合: {len(res_df)}种")

# ═══════════════════════════════════════
# 排序1: 复利最大
# ═══════════════════════════════════════
res_df = res_df.sort_values('复利%', ascending=False)
print(f"\n{'='*120}")
print("TOP15 复利最大")
print("=" * 120)
hdr = f"{'T':>1} {'连':>1} {'额':>5} {'大盘':<11} {'热':>1} {'亏停':<5} {'出场':<7} {'笔':>3} {'均':>7} {'胜':>4} {'利':>7} {'复利':>8} {'DD':>6} {'月+':>5} {'月均':>6} {'差月':>6} {'≥20%':>5}"
print(hdr)
print("-" * 120)
for _, r in res_df.head(15).iterrows():
    lb = 'Y' if r['连板'] else 'N'
    ht = 'Y' if r['热门'] else 'N'
    print(f" {int(r['TOP']):>1} {lb} {int(r['成交额']):>5} {r['大盘']:<11} {ht} {r['连亏停']:<5} {r['出场']:<7} {int(r['笔']):>3} {r['均']:>+6.2f}% {r['胜%']:>3.0f}% {r['利']:>+6.0f}% {r['复利%']:>+7.0f}% {r['DD%']:>+5.0f}% {r['月+']:>5} {r['月均']:>+5.0f}% {r['最差月']:>+5.0f}% {r['月≥20%']:>5}")

# ═══════════════════════════════════════
# 排序2: 月均≥20%且回撤最小
# ═══════════════════════════════════════
print(f"\n{'='*120}")
print("月均≥15% 且 回撤最小 TOP15")
print("=" * 120)
good = res_df[res_df['月均'] >= 15].copy()
good = good.sort_values(['DD%'], ascending=[False])  # DD%是负数, 越大(接近0)越好
print(hdr)
print("-" * 120)
for _, r in good.head(15).iterrows():
    lb = 'Y' if r['连板'] else 'N'
    ht = 'Y' if r['热门'] else 'N'
    print(f" {int(r['TOP']):>1} {lb} {int(r['成交额']):>5} {r['大盘']:<11} {ht} {r['连亏停']:<5} {r['出场']:<7} {int(r['笔']):>3} {r['均']:>+6.2f}% {r['胜%']:>3.0f}% {r['利']:>+6.0f}% {r['复利%']:>+7.0f}% {r['DD%']:>+5.0f}% {r['月+']:>5} {r['月均']:>+5.0f}% {r['最差月']:>+5.0f}% {r['月≥20%']:>5}")

# ═══════════════════════════════════════
# 排序3: 月正率最高 + 均值高
# ═══════════════════════════════════════
print(f"\n{'='*120}")
print("月正率最高 (≥20笔) TOP15")
print("=" * 120)
res20 = res_df[res_df['笔'] >= 20].copy()
res20['月正率'] = res20['月+'].apply(lambda x: int(x.split('/')[0]) / int(x.split('/')[1]) if '/' in str(x) else 0)
res20 = res20.sort_values(['月正率', '均'], ascending=[False, False])
print(hdr)
print("-" * 120)
for _, r in res20.head(15).iterrows():
    lb = 'Y' if r['连板'] else 'N'
    ht = 'Y' if r['热门'] else 'N'
    print(f" {int(r['TOP']):>1} {lb} {int(r['成交额']):>5} {r['大盘']:<11} {ht} {r['连亏停']:<5} {r['出场']:<7} {int(r['笔']):>3} {r['均']:>+6.2f}% {r['胜%']:>3.0f}% {r['利']:>+6.0f}% {r['复利%']:>+7.0f}% {r['DD%']:>+5.0f}% {r['月+']:>5} {r['月均']:>+5.0f}% {r['最差月']:>+5.0f}% {r['月≥20%']:>5}")

# ═══════════════════════════════════════
# 选出3个推荐策略做详细分析
# ═══════════════════════════════════════
strategies = []

# 策略A: 复利最大
strategies.append(('A·激进(复利最大)', res_df.iloc[0]))

# 策略B: 月均≥15%且回撤最小
if len(good) > 0:
    strategies.append(('B·平衡(月均≥15%+低回撤)', good.iloc[0]))

# 策略C: 月正率最高
if len(res20) > 0:
    strategies.append(('C·稳健(月正率最高)', res20.iloc[0]))

for strat_name, strat in strategies:
    exit_key = strat['出场']
    pause_str = strat['连亏停']
    if pause_str != 'N':
        pa, pd_val = int(pause_str.split('/')[0]), int(pause_str.split('/')[1])
    else:
        pa, pd_val = 0, 0
    
    mask = pd.Series([True] * len(cand_df))
    mask &= cand_df['is_limit_up']
    if strat['连板']: mask &= cand_df['is_lianban']
    if strat['成交额'] > 0: mask &= cand_df['amount_wan'] >= strat['成交额']
    if strat['大盘'] == 'no_weak': mask &= cand_df['market_state'] >= 0
    elif strat['大盘'] == 'only_strong': mask &= cand_df['market_state'] >= 1
    if strat['热门']: mask &= cand_df['in_hot']
    
    filtered = cand_df[mask].copy()
    filtered = filtered[filtered['returns'].apply(lambda x: exit_key in x)]
    
    trades = []
    consec_loss = 0
    pause_until = 0
    
    for sd in sorted(filtered['signal_date'].unique()):
        group = filtered[filtered['signal_date'] == sd]
        top = group.nlargest(int(strat['TOP']), 'total_score')
        for _, row in top.iterrows():
            bd = row['buy_date']
            if pa > 0 and bd < pause_until:
                continue
            
            ret = row['returns'][exit_key]
            
            if ret < 0:
                consec_loss += 1
                if pa > 0 and consec_loss >= pa:
                    pt = get_td(bd, pd_val)
                    if pt: pause_until = pt
                    consec_loss = 0
            else:
                consec_loss = 0
            
            trades.append({
                '信号日': row['signal_date'],
                '买入日': bd,
                '代码': row['code'],
                '名称': row['name'],
                '涨幅': round(row['change_pct'], 1),
                '连板': 'Y' if row['is_lianban'] else 'N',
                '成交额万': int(row['amount_wan']),
                '概念': row['matched'],
                '大盘': '强' if row['market_state'] == 1 else ('中' if row['market_state'] == 0 else '弱'),
                '收益%': round(ret, 2),
            })
    
    trade_df = pd.DataFrame(trades)
    trade_df['月'] = trade_df['买入日'] // 100
    
    print(f"\n{'='*100}")
    print(f"★ {strat_name}")
    print(f"  条件: TOP{int(strat['TOP'])} 连板={'Y' if strat['连板'] else 'N'} 额≥{int(strat['成交额'])}万 大盘={strat['大盘']} 热门={'Y' if strat['热门'] else 'N'} 连亏停={strat['连亏停']} 出场={exit_key}")
    print(f"  {int(strat['笔'])}笔 均{strat['均']:+.2f}% 胜{strat['胜%']:.0f}% 利{strat['利']:+.0f}% 复利{strat['复利%']:+.0f}% DD{strat['DD%']:.0f}% 月{strat['月+']} 月≥20%:{strat['月≥20%']}")
    print("-" * 100)
    
    # 月度
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
        pnl_wan = (cap - month_start) / 10000
        pct = (cap / month_start - 1) * 100
        ok = '✅' if pct >= 20 else ('⚠️' if pct >= 0 else '❌')
        print(f"  {int(r['月'])} {int(r['笔']):>3}笔 均{r['均值']:>+6.2f}% 胜{r['胜率']:>4.0f}% 利{r['利润']:>+7.1f}% 账户{cap/10000:>7.1f}万 月{pct:>+6.1f}% {ok}")
    
    print(f"\n  📊 10万 → {cap/10000:.1f}万 ({(cap/100000-1)*100:+.0f}%)")
    
    # 保存
    fname = f'{OUTPUT_DIR}新闻驱动V4_{strat_name[:3]}_信号.csv'
    trade_df.to_csv(fname, index=False, encoding='utf-8-sig')

print(f"\n{'='*100}")
print("完成!")
