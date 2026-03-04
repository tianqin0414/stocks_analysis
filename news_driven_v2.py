#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻驱动选股 V2 - 利润最大化版 (优化版: 预计算)
"""

import pandas as pd
import numpy as np
import os
import pickle
from collections import Counter

# ── 配置 ──
NEWS_DIR = '/Users/tq/Desktop/stocks_data/news-donwloader/news_data/'
KLINE_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d/'
CONCEPTS_FILE = '/Users/tq/Documents/quant_data/basic/A_Stocks1010.xlsx'
OUTPUT_DIR = '/Users/tq/PycharmProjects/stocks_analysis/output/'
CACHE_FILE = os.path.join(OUTPUT_DIR, 'daily_data_cache_2025.pkl')

# 新闻→概念映射
NEWS_CONCEPT_MAP = {
    '人工智能': {'人工智能': 3, 'AI': 3, 'AIGC': 2, '大模型': 2, '算力': 2},
    'DeepSeek': {'人工智能': 3, 'AI': 3, '大模型': 3, '算力': 2},
    '大模型': {'大模型': 3, '人工智能': 2, 'AI': 2, '算力': 2},
    '算力': {'算力': 3, 'CPO': 3, '光模块': 2, '液冷': 2, '服务器': 2},
    '芯片': {'芯片': 3, '半导体': 3, '集成电路': 2},
    '半导体': {'半导体': 3, '芯片': 3, '集成电路': 2},
    '机器人': {'机器人': 3, '人形机器人': 3, '减速器': 2},
    '人形机器人': {'人形机器人': 3, '机器人': 3, '减速器': 2},
    '量子': {'量子': 3, '量子计算': 3},
    '卫星': {'卫星': 3, '卫星互联网': 3, '北斗': 2, '航天': 2},
    '低空': {'低空经济': 3, '无人机': 3},
    '无人机': {'无人机': 3, '低空经济': 3},
    '自动驾驶': {'自动驾驶': 3, '智能驾驶': 3},
    '华为': {'华为': 3, '鸿蒙': 2},
    '鸿蒙': {'鸿蒙': 3, '华为': 2},
    '光伏': {'光伏': 3, '新能源': 1},
    '储能': {'储能': 3, '电池': 2, '新能源': 1},
    '锂电': {'锂电': 3, '锂电池': 2},
    '氢能': {'氢能': 3, '燃料电池': 3},
    '核电': {'核电': 3, '核能': 2},
    '风电': {'风电': 3, '海上风电': 2},
    '军工': {'军工': 3, '国防': 3, '航空': 2},
    '航天': {'航天': 3, '商业航天': 3, '火箭': 2, '卫星': 2},
    '歼': {'军工': 3, '航空': 3},
    '舰': {'军工': 2, '舰船': 3},
    '导弹': {'军工': 3, '导弹': 3},
    '关税': {'国产替代': 3, '自主可控': 3, '芯片': 2, '半导体': 2},
    '制裁': {'国产替代': 3, '自主可控': 3},
    '十五五': {'新能源': 2, '航空航天': 2, '低空经济': 2, '数字经济': 2, '人工智能': 2},
    '降准': {'券商': 2, '地产': 2},
    '降息': {'券商': 2, '地产': 2},
    '消费': {'消费': 2, '白酒': 1, '家电': 1},
    '房地产': {'房地产': 3, '地产': 3},
    '医药': {'生物医药': 2, '创新药': 2},
    '数据': {'数据': 2, '数字经济': 2},
    '6G': {'6G': 3, '通信': 2},
}

IMPORTANCE_KEYWORDS = {
    3: ['习近平', '国务院', '总理', '政治局', '四中全会', '两会', '政府工作报告', '重大突破'],
    2: ['发改委', '工信部', '证监会', '央行', '突破', '首次', '重磅', '全面'],
    1: ['利好', '增长', '提速'],
}

# ── 加载数据 ──
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
print(f"新闻: {len(news)}条")

concepts_df = pd.read_excel(CONCEPTS_FILE)
concepts_df['商品代码'] = concepts_df['商品代码'].astype(str).str.zfill(6)
code_to_concepts = {k: str(v) for k, v in zip(concepts_df['商品代码'], concepts_df['同花顺概念old'].fillna(''))}
code_to_name = dict(zip(concepts_df['商品代码'], concepts_df['名称'].fillna('')))

print("从缓存加载K线...")
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
    except:
        pass
    return None

# ═══════════════════════════════════════
# 预计算: 每天的板块热度 + 候选股票池
# ═══════════════════════════════════════
print("预计算每日板块热度...")

daily_heat = {}  # date -> Counter

for date_int in trade_dates:
    if date_int < 20250210 or date_int > 20260110:
        continue
    
    # 收集前一天盘后 + 当天盘前新闻
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
    
    # 批量处理新闻文本
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

print(f"有新闻信号的交易日: {len(daily_heat)}天")

# 预计算候选股票
print("预计算每日候选股票...")

# 对每天的股票, 标记: 涨幅, 是否涨停, 概念匹配, 成交额, 前一日涨幅
daily_candidates = {}  # date -> list of candidate dicts

for date_int in daily_heat:
    if date_int not in daily_data:
        continue
    
    stocks = daily_data[date_int]
    heat = daily_heat[date_int]
    top_concepts = [c for c, _ in heat.most_common(8)]
    
    cands = []
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
        if change < 5:  # 至少涨5%才考虑
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
        # 一字涨停买不到
        if buy_data['open_pct'] >= limit_pct * 0.98:
            continue
        
        # 计算各持有期收益
        returns = {}
        max_highs = {}
        for hold in [1, 2, 3, 5]:
            sell_d = get_td(buy_date, hold)
            if sell_d and code in stock_daily and sell_d in stock_daily[code]:
                sell_price = stock_daily[code][sell_d]['close']
                returns[hold] = (sell_price / buy_price - 1) * 100 - 0.15
                
                mh = 0
                for h_off in range(1, hold + 1):
                    cd = get_td(buy_date, h_off)
                    if cd and code in stock_daily and cd in stock_daily[code]:
                        mh = max(mh, stock_daily[code][cd]['high'])
                max_highs[hold] = (mh / buy_price - 1) * 100 if mh > 0 else 0
        
        if not returns:
            continue
        
        cands.append({
            'code': code,
            'name': code_to_name.get(code, ''),
            'signal_date': date_int,
            'buy_date': buy_date,
            'change_pct': change,
            'amount_wan': amount_wan,
            'is_limit_up': is_limit_up,
            'is_lianban': is_lianban,
            'concept_score': concept_score,
            'matched': ','.join(matched),
            'buy_price': buy_price,
            'returns': returns,
            'max_highs': max_highs,
            'prev_change': prev_change,
        })
    
    if cands:
        daily_candidates[date_int] = cands

print(f"有候选股票的交易日: {len(daily_candidates)}天")
total_cands = sum(len(v) for v in daily_candidates.values())
print(f"总候选: {total_cands}只次\n")

# ═══════════════════════════════════════
# 快速网格搜索
# ═══════════════════════════════════════
print("网格搜索最优参数...\n")

param_results = []

for max_stocks in [1, 2, 3, 5]:
    for min_change in [5, 7, 9, 9.5]:
        for min_amount in [0, 3000, 5000, 10000, 30000]:
            for hold_days in [1, 2, 3, 5]:
                for only_limit in [False, True]:
                    for only_lianban in [False, True]:
                        if only_lianban and not only_limit:
                            continue
                        
                        all_rets = []
                        buy_dates = []
                        
                        for date_int, cands in daily_candidates.items():
                            # 过滤
                            filtered = cands
                            if min_change > 5:
                                filtered = [c for c in filtered if c['change_pct'] >= min_change]
                            if min_amount > 0:
                                filtered = [c for c in filtered if c['amount_wan'] >= min_amount]
                            if only_limit:
                                filtered = [c for c in filtered if c['is_limit_up']]
                            if only_lianban:
                                filtered = [c for c in filtered if c['is_lianban']]
                            
                            if not filtered:
                                continue
                            
                            # 排序选TOP
                            filtered.sort(key=lambda x: x['concept_score'] * (1 + x['change_pct']/10) * (1 + min(x['amount_wan'],100000)/50000) * (2 if x['is_lianban'] else 1) * (1.5 if x['is_limit_up'] else 1), reverse=True)
                            
                            for c in filtered[:max_stocks]:
                                if hold_days in c['returns']:
                                    all_rets.append(c['returns'][hold_days])
                                    buy_dates.append(c['buy_date'])
                        
                        if len(all_rets) < 15:
                            continue
                        
                        avg = np.mean(all_rets)
                        win = np.mean([1 if r > 0 else 0 for r in all_rets]) * 100
                        total = np.sum(all_rets)
                        
                        # 月度
                        months_data = {}
                        for ret, bd in zip(all_rets, buy_dates):
                            m = bd // 100
                            if m not in months_data:
                                months_data[m] = []
                            months_data[m].append(ret)
                        
                        monthly_sums = [sum(v) for v in months_data.values()]
                        pos_months = sum(1 for s in monthly_sums if s > 0)
                        total_months = len(monthly_sums)
                        
                        param_results.append({
                            'TOP': max_stocks,
                            '涨幅': min_change,
                            '成交额': min_amount,
                            '天数': hold_days,
                            '涨停': only_limit,
                            '连板': only_lianban,
                            '笔数': len(all_rets),
                            '均值': avg,
                            '胜率': win,
                            '利润和': total,
                            '月+': f"{pos_months}/{total_months}",
                            '月均': total / total_months if total_months > 0 else 0,
                        })

param_df = pd.DataFrame(param_results)

# 按利润和排序
param_df = param_df.sort_values('利润和', ascending=False)

print("=" * 100)
print("参数搜索 TOP30 (按利润总和)")
print("=" * 100)
print(f"{'TOP':>3} {'涨幅':>5} {'成交额':>6} {'天':>2} {'涨停':>3} {'连板':>3} {'笔数':>4} {'均值':>7} {'胜率':>5} {'利润和':>8} {'月+':>6} {'月均':>7}")
print("-" * 100)
for _, row in param_df.head(30).iterrows():
    lt = 'Y' if row['涨停'] else 'N'
    lb = 'Y' if row['连板'] else 'N'
    print(f"  {int(row['TOP']):>2} {row['涨幅']:>5.1f} {int(row['成交额']):>5}万 {int(row['天数']):>2}  {lt}    {lb}   {int(row['笔数']):>4} {row['均值']:>+6.2f}% {row['胜率']:>4.0f}% {row['利润和']:>+7.1f}% {row['月+']:<5} {row['月均']:>+6.1f}%")

# 按均值排序(利润密度)
param_df2 = param_df[param_df['笔数'] >= 20].sort_values('均值', ascending=False)
print(f"\n{'='*100}")
print("参数搜索 TOP20 (按单笔均值, ≥20笔)")
print("=" * 100)
print(f"{'TOP':>3} {'涨幅':>5} {'成交额':>6} {'天':>2} {'涨停':>3} {'连板':>3} {'笔数':>4} {'均值':>7} {'胜率':>5} {'利润和':>8} {'月+':>6} {'月均':>7}")
print("-" * 100)
for _, row in param_df2.head(20).iterrows():
    lt = 'Y' if row['涨停'] else 'N'
    lb = 'Y' if row['连板'] else 'N'
    print(f"  {int(row['TOP']):>2} {row['涨幅']:>5.1f} {int(row['成交额']):>5}万 {int(row['天数']):>2}  {lt}    {lb}   {int(row['笔数']):>4} {row['均值']:>+6.2f}% {row['胜率']:>4.0f}% {row['利润和']:>+7.1f}% {row['月+']:<5} {row['月均']:>+6.1f}%")

# ═══════════════════════════════════════
# 最优参数详细分析
# ═══════════════════════════════════════
# 选利润总和最高的
best = param_df.iloc[0]
print(f"\n{'='*100}")
print(f"★ 利润最大化参数: TOP{int(best['TOP'])} 涨幅≥{best['涨幅']}% 成交额≥{int(best['成交额'])}万 持有{int(best['天数'])}天 涨停={'Y' if best['涨停'] else 'N'} 连板={'Y' if best['连板'] else 'N'}")
print(f"{'='*100}")

# 重新提取最优参数的所有交易
best_trades = []
for date_int, cands in daily_candidates.items():
    filtered = cands
    if best['涨幅'] > 5:
        filtered = [c for c in filtered if c['change_pct'] >= best['涨幅']]
    if best['成交额'] > 0:
        filtered = [c for c in filtered if c['amount_wan'] >= best['成交额']]
    if best['涨停']:
        filtered = [c for c in filtered if c['is_limit_up']]
    if best['连板']:
        filtered = [c for c in filtered if c['is_lianban']]
    
    if not filtered:
        continue
    
    filtered.sort(key=lambda x: x['concept_score'] * (1 + x['change_pct']/10) * (1 + min(x['amount_wan'],100000)/50000) * (2 if x['is_lianban'] else 1) * (1.5 if x['is_limit_up'] else 1), reverse=True)
    
    hold = int(best['天数'])
    for c in filtered[:int(best['TOP'])]:
        if hold in c['returns']:
            best_trades.append({
                '信号日': c['signal_date'],
                '买入日': c['buy_date'],
                '代码': c['code'],
                '名称': c['name'],
                '信号日涨幅': c['change_pct'],
                '涨停': c['is_limit_up'],
                '连板': c['is_lianban'],
                '成交额万': c['amount_wan'],
                '概念分': c['concept_score'],
                '概念': c['matched'],
                '收益%': c['returns'][hold],
                '最高收益%': c['max_highs'].get(hold, 0),
            })

best_df = pd.DataFrame(best_trades)

# 月度
best_df['月'] = best_df['买入日'] // 100
monthly = best_df.groupby('月').agg(
    笔数=('收益%', 'count'),
    均值=('收益%', 'mean'),
    胜率=('收益%', lambda x: (x>0).mean()*100),
    利润和=('收益%', 'sum'),
    最高可能=('最高收益%', 'mean'),
).reset_index()

print(f"\n月度明细:")
print(f"{'月':<8} {'笔':>4} {'均值':>7} {'胜率':>5} {'利润':>8} {'最高':>7}")
print('-' * 50)
for _, row in monthly.iterrows():
    marker = ' ★' if row['利润和'] > 15 else (' ▼' if row['利润和'] < -10 else '')
    print(f"  {int(row['月']):<6} {int(row['笔数']):>3}  {row['均值']:>+6.2f}%  {row['胜率']:>4.0f}% {row['利润和']:>+7.1f}% {row['最高可能']:>+6.2f}%{marker}")

# 概念
concept_stats = {}
for _, row in best_df.iterrows():
    for c in row['概念'].split(','):
        c = c.strip()
        if c:
            if c not in concept_stats:
                concept_stats[c] = []
            concept_stats[c].append(row['收益%'])

print(f"\n概念表现:")
concept_list = [(c, rets) for c, rets in concept_stats.items() if len(rets) >= 3]
concept_list.sort(key=lambda x: sum(x[1]), reverse=True)
for c, rets in concept_list[:10]:
    print(f"  {c:<12} {len(rets):>3}笔 均值{np.mean(rets):>+6.2f}% 胜率{np.mean([1 if r>0 else 0 for r in rets])*100:>4.0f}% 利润{np.sum(rets):>+7.1f}%")

# 复利
print(f"\n复利模拟:")
capital = 100000
max_cap = capital
max_dd = 0
for _, row in best_df.sort_values('买入日').iterrows():
    capital *= (1 + row['收益%'] / 100)
    max_cap = max(max_cap, capital)
    dd = (capital / max_cap - 1) * 100
    max_dd = min(max_dd, dd)

print(f"  10万 → {capital/10000:.1f}万 ({(capital/100000-1)*100:+.1f}%)")
print(f"  最大回撤: {max_dd:.1f}%")

# TOP交易
print(f"\n最赚钱的10笔:")
top10 = best_df.nlargest(10, '收益%')
for _, row in top10.iterrows():
    print(f"  {row['信号日']} {row['名称']:<8} 信号涨{row['信号日涨幅']:>+5.1f}% → 收益{row['收益%']:>+6.2f}% 概念:{row['概念']}")

print(f"\n最亏钱的10笔:")
bot10 = best_df.nsmallest(10, '收益%')
for _, row in bot10.iterrows():
    print(f"  {row['信号日']} {row['名称']:<8} 信号涨{row['信号日涨幅']:>+5.1f}% → 收益{row['收益%']:>+6.2f}% 概念:{row['概念']}")

# 保存
best_df.to_csv(f'{OUTPUT_DIR}新闻驱动V2_最优信号.csv', index=False, encoding='utf-8-sig')
print(f"\n保存: {OUTPUT_DIR}新闻驱动V2_最优信号.csv")
print("=" * 100)
