#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
新闻驱动选股回测
逻辑：
1. 每天扫描前一天收盘后+当天盘前的重大新闻
2. 从新闻中提取关键概念/板块方向
3. 在对应概念板块中，选当天涨停（或大涨）的龙头股
4. T+1买入（次日开盘买），持有N天后卖出
5. 统计收益

核心问题：新闻→概念匹配→选股 这条链路能不能产生alpha？
"""

import pandas as pd
import numpy as np
import os
import re
from collections import Counter

# ── 配置 ──
NEWS_DIR = '/Users/tq/Desktop/stocks_data/news-donwloader/news_data/'
KLINE_DIR = '/Users/tq/Documents/quant_data/miniqmt_data/1d/'
CONCEPTS_FILE = '/Users/tq/Documents/quant_data/basic/A_Stocks1010.xlsx'
OUTPUT_DIR = '/Users/tq/PycharmProjects/stocks_analysis/output/'

# ── 新闻→概念映射表 ──
# 新闻关键词 → 同花顺概念关键词
NEWS_TO_CONCEPT = {
    # 科技
    '人工智能': ['人工智能', 'AI', 'ChatGPT', 'AIGC', '大模型'],
    'DeepSeek': ['人工智能', 'AI', '大模型', '算力'],
    '芯片': ['芯片', '半导体', '集成电路', '光刻'],
    '半导体': ['半导体', '芯片', '集成电路'],
    '算力': ['算力', 'CPO', '光模块', '液冷', '服务器'],
    '机器人': ['机器人', '人形机器人', '减速器'],
    '量子': ['量子', '量子计算', '量子通信'],
    '6G': ['6G', '通信'],
    '卫星': ['卫星', '卫星互联网', '卫星导航', '北斗'],
    '低空': ['低空经济', '无人机', 'eVTOL'],
    '自动驾驶': ['自动驾驶', '智能驾驶', '车路协同'],
    
    # 能源
    '光伏': ['光伏', 'HJT', 'TOPCon', 'BC电池'],
    '储能': ['储能', '电池'],
    '锂电': ['锂电', '锂电池', '电解液', '正极', '负极'],
    '氢能': ['氢能', '燃料电池'],
    '核电': ['核电', '核能', '核聚变'],
    '风电': ['风电', '海上风电'],
    
    # 军工
    '军工': ['军工', '国防', '航空', '导弹', '舰船'],
    '航天': ['航天', '商业航天', '火箭', '卫星'],
    '歼': ['军工', '航空', '战斗机', '中航'],
    '舰': ['军工', '舰船', '海军'],
    
    # 政策
    '关税': ['国产替代', '自主可控', '芯片', '半导体'],
    '制裁': ['国产替代', '自主可控', '信创'],
    '消费': ['消费', '白酒', '家电', '旅游'],
    '房地产': ['房地产', '地产'],
    '基建': ['基建', '水泥', '钢铁'],
    '医药': ['生物医药', '创新药', '中药'],
    '华为': ['华为', '鸿蒙', '华为概念'],
    
    # 事件
    '座谈会': ['民营经济'],
    '两会': ['新质生产力'],
    '十五五': ['新能源', '航空航天', '低空经济', '数字经济'],
}

# ── 加载数据 ──
import pickle

print("加载数据...")

# 1. 加载新闻
news_list = []
for source in ['cls', 'sina']:  # 用财联社和新浪，华尔街见闻重复多
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
# 盘前新闻(当天9:30前) 和 前一天盘后新闻(15:00后)
news['hour'] = news['datetime'].dt.hour
print(f"新闻: {len(news)}条")

# 2. 加载概念
concepts_df = pd.read_excel(CONCEPTS_FILE)
concepts_df['商品代码'] = concepts_df['商品代码'].astype(str).str.zfill(6)
code_to_concepts = dict(zip(concepts_df['商品代码'], concepts_df['同花顺概念old'].fillna('')))
code_to_name = dict(zip(concepts_df['商品代码'], concepts_df['名称'].fillna('')))

# 3. 加载全A日线数据（带缓存）
CACHE_FILE = os.path.join(OUTPUT_DIR, 'daily_data_cache_2025.pkl')

if os.path.exists(CACHE_FILE):
    print("从缓存加载K线数据...")
    with open(CACHE_FILE, 'rb') as f:
        daily_data = pickle.load(f)
    print(f"缓存加载完成: {len(daily_data)}个交易日")
else:
    print("加载K线数据(首次，后续走缓存)...")
    kline_files = [f for f in os.listdir(KLINE_DIR) if f.endswith('.csv')]
    print(f"K线文件: {len(kline_files)}个")
    
    daily_data = {}
    loaded = 0
    
    for kf in kline_files:
        parts = kf.replace('.csv', '').split('_')
        code = parts[0]
        if code.startswith('8') or code.startswith('4'):
            continue
        
        filepath = os.path.join(KLINE_DIR, kf)
        try:
            df = pd.read_csv(filepath)
            if len(df) < 20:
                continue
            
            df['date'] = df['date'].astype(int)
            df = df[df['date'] >= 20250201]
            
            for _, row in df.iterrows():
                d = int(row['date'])
                if d not in daily_data:
                    daily_data[d] = []
                
                pre = row['preClose']
                if pre <= 0:
                    continue
                
                daily_data[d].append({
                    'code': code,
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'preClose': pre,
                    'volume': row['volume'],
                    'amount': row.get('amount', 0),
                    'change_pct': (row['close'] / pre - 1) * 100,
                    'open_pct': (row['open'] / pre - 1) * 100,
                })
            loaded += 1
        except:
            continue
        
        if loaded % 500 == 0:
            print(f"  已加载{loaded}个...")
    
    print(f"加载完成: {loaded}只股票, {len(daily_data)}个交易日")
    
    # 保存缓存
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(daily_data, f)
    print(f"缓存已保存: {CACHE_FILE}")

# ── 每天新闻→概念提取 ──
def extract_concepts_from_news(date_int, news_df):
    """提取某天盘前+前一天盘后的重大新闻中的概念"""
    # 前一天盘后(15:00后)的新闻
    prev_date = date_int - 1
    # 简单处理：周末跳过
    prev_news = news_df[(news_df['date'] == prev_date) & (news_df['hour'] >= 15)]
    # 当天盘前(9:30前)
    today_news = news_df[(news_df['date'] == date_int) & (news_df['hour'] < 10)]
    
    all_news = pd.concat([prev_news, today_news])
    if len(all_news) == 0:
        return []
    
    # 统计新闻中出现的关键词
    all_text = ' '.join(all_news['content'].tolist())
    
    matched_concepts = []
    concept_scores = Counter()
    
    for news_kw, concept_list in NEWS_TO_CONCEPT.items():
        count = all_text.count(news_kw)
        if count >= 3:  # 至少出现3次才算热点
            for c in concept_list:
                concept_scores[c] += count
    
    # 返回得分最高的概念
    top_concepts = [c for c, _ in concept_scores.most_common(10)]
    return top_concepts

# ── 选股逻辑 ──
def select_stocks(date_int, hot_concepts, daily_data, max_stocks=5):
    """在热门概念中选当天涨停/大涨的龙头股"""
    if date_int not in daily_data or not hot_concepts:
        return []
    
    stocks = daily_data[date_int]
    candidates = []
    
    for s in stocks:
        code = s['code']
        concepts = str(code_to_concepts.get(code, ''))
        
        # 检查是否匹配热门概念
        matched = False
        for hc in hot_concepts:
            if hc in concepts:
                matched = True
                break
        
        if not matched:
            continue
        
        # 选涨停或大涨的（当天收盘涨幅>=7%）
        change = s['change_pct']
        
        # 判断涨停板类型
        is_20pct = code.startswith('3') or code.startswith('688')
        limit = 20 if is_20pct else 10
        
        # 涨停判定
        is_limit_up = change >= limit * 0.98
        
        if change >= 7:  # 至少涨7%才入选
            score = change  # 涨幅越大得分越高
            if is_limit_up:
                score += 5  # 涨停加分
            
            candidates.append({
                'code': code,
                'name': code_to_name.get(code, ''),
                'close': s['close'],
                'change_pct': change,
                'amount': s['amount'],
                'is_limit_up': is_limit_up,
                'score': score,
            })
    
    # 按得分排序，取前N只
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:max_stocks]

# ── 构建K线查询索引 ──
print("构建查询索引...")
# code -> {date -> row_data}
stock_daily = {}
for d, stocks in daily_data.items():
    for s in stocks:
        code = s['code']
        if code not in stock_daily:
            stock_daily[code] = {}
        stock_daily[code][d] = s

# 获取排序的交易日列表
trade_dates = sorted(daily_data.keys())

def get_next_trade_date(date_int, offset=1):
    """获取后N个交易日"""
    try:
        idx = trade_dates.index(date_int)
        if idx + offset < len(trade_dates):
            return trade_dates[idx + offset]
    except:
        pass
    return None

# ── 回测主循环 ──
print("\n开始回测...")
print("策略：新闻热点概念 → 当天涨停龙头 → T+1开盘买入 → 持有N天卖出\n")

results = []
all_signals = []

for date_int in trade_dates:
    if date_int < 20250210 or date_int > 20260110:
        continue
    
    # 1. 提取当天热门概念
    hot_concepts = extract_concepts_from_news(date_int, news)
    if not hot_concepts:
        continue
    
    # 2. 在热门概念中选涨停/大涨龙头
    selected = select_stocks(date_int, hot_concepts, daily_data, max_stocks=3)
    if not selected:
        continue
    
    # 3. 计算T+1买入收益
    buy_date = get_next_trade_date(date_int, 1)
    if buy_date is None:
        continue
    
    for stock in selected:
        code = stock['code']
        
        if code not in stock_daily or buy_date not in stock_daily[code]:
            continue
        
        buy_data = stock_daily[code][buy_date]
        buy_price = buy_data['open']  # T+1开盘价买入
        
        if buy_price <= 0:
            continue
        
        # 如果T+1开盘就涨停，无法买入
        is_20pct = code.startswith('3') or code.startswith('688')
        limit = 20 if is_20pct else 10
        if buy_data['open_pct'] >= limit * 0.98:
            continue  # 一字涨停，买不到
        
        # 计算不同持有期的收益
        for hold_days in [1, 2, 3, 5]:
            sell_date = get_next_trade_date(buy_date, hold_days)
            if sell_date is None:
                continue
            
            if code in stock_daily and sell_date in stock_daily[code]:
                sell_data = stock_daily[code][sell_date]
                sell_price = sell_data['close']
                ret = (sell_price / buy_price - 1) * 100 - 0.15  # 扣手续费
                
                results.append({
                    '信号日': date_int,
                    '买入日': buy_date,
                    '卖出日': sell_date,
                    '代码': code,
                    '名称': stock['name'],
                    '信号日涨幅': stock['change_pct'],
                    '涨停': stock['is_limit_up'],
                    '买入价': buy_price,
                    '卖出价': sell_price,
                    '收益%': ret,
                    '持有天数': hold_days,
                    '热门概念': ','.join(hot_concepts[:3]),
                })

results_df = pd.DataFrame(results)
print(f"总信号数: {len(results_df)}")

# ── 按持有天数分析 ──
print("\n" + "=" * 72)
print("一、不同持有天数的收益对比")
print("=" * 72)

for hold in [1, 2, 3, 5]:
    sub = results_df[results_df['持有天数'] == hold]
    if len(sub) < 10:
        continue
    
    avg = sub['收益%'].mean()
    med = sub['收益%'].median()
    win = (sub['收益%'] > 0).mean() * 100
    total = sub['收益%'].sum()
    n_days = sub['买入日'].nunique()
    
    # 月度统计
    sub_copy = sub.copy()
    sub_copy['月'] = sub_copy['买入日'] // 100
    monthly = sub_copy.groupby('月')['收益%'].mean()
    pos_months = (monthly > 0).sum()
    total_months = len(monthly)
    
    print(f"\n  持有{hold}天: {len(sub)}笔, {n_days}个交易日")
    print(f"    均值{avg:+.2f}%  中位数{med:+.2f}%  胜率{win:.0f}%  利润总和{total:+.1f}%")
    print(f"    月胜率: {pos_months}/{total_months}个月正收益")

# ── 最优持有天数下的详细分析 ──
# 先找最优
best_hold = 1
best_avg = -999
for hold in [1, 2, 3, 5]:
    sub = results_df[results_df['持有天数'] == hold]
    if len(sub) > 10:
        avg = sub['收益%'].mean()
        if avg > best_avg:
            best_avg = avg
            best_hold = hold

print(f"\n{'='*72}")
print(f"二、最优持有天数: {best_hold}天 详细分析")
print(f"{'='*72}")

best_df = results_df[results_df['持有天数'] == best_hold].copy()

# 月度明细
best_df['月'] = best_df['买入日'] // 100
monthly = best_df.groupby('月').agg(
    笔数=('收益%', 'count'),
    均值=('收益%', 'mean'),
    胜率=('收益%', lambda x: (x>0).mean()*100),
    利润和=('收益%', 'sum'),
).reset_index()

print(f"\n月度明细:")
print(f"{'月份':<10} {'笔数':>5} {'均值':>7} {'胜率':>5} {'利润和':>8}")
print('-' * 40)
for _, row in monthly.iterrows():
    marker = ' ★' if row['利润和'] > 10 else (' ▼' if row['利润和'] < -10 else '')
    print(f"  {int(row['月']):<8} {int(row['笔数']):>4}笔 {row['均值']:>+6.2f}% {row['胜率']:>4.0f}% {row['利润和']:>+7.1f}%{marker}")

# ── 按信号日涨幅分析 ──
print(f"\n{'='*72}")
print("三、信号日涨幅分组对比")
print(f"{'='*72}")

best_df['涨幅组'] = pd.cut(best_df['信号日涨幅'], 
                         bins=[7, 8, 9, 10, 15, 20, 50],
                         labels=['7~8%', '8~9%', '9~10%', '10~15%', '15~20%', '20%+'])

for group in ['7~8%', '8~9%', '9~10%', '10~15%', '15~20%', '20%+']:
    sub = best_df[best_df['涨幅组'] == group]
    if len(sub) >= 5:
        avg = sub['收益%'].mean()
        win = (sub['收益%'] > 0).mean() * 100
        print(f"  信号日涨{group:<8} {len(sub):>4}笔  均值{avg:>+6.2f}%  胜率{win:>4.0f}%")

# ── 涨停 vs 非涨停 ──
print(f"\n{'='*72}")
print("四、涨停信号 vs 非涨停大涨信号")
print(f"{'='*72}")

for is_limit in [True, False]:
    sub = best_df[best_df['涨停'] == is_limit]
    if len(sub) >= 5:
        label = '涨停' if is_limit else '非涨停大涨'
        avg = sub['收益%'].mean()
        win = (sub['收益%'] > 0).mean() * 100
        print(f"  {label:<12} {len(sub):>4}笔  均值{avg:>+6.2f}%  胜率{win:>4.0f}%")

# ── 按概念分析 ──
print(f"\n{'='*72}")
print("五、各热门概念的回测收益")
print(f"{'='*72}")

concept_stats = {}
for _, row in best_df.iterrows():
    concepts = row['热门概念'].split(',')
    for c in concepts:
        c = c.strip()
        if c:
            if c not in concept_stats:
                concept_stats[c] = []
            concept_stats[c].append(row['收益%'])

print(f"\n{'概念':<12} {'笔数':>5} {'均值':>7} {'胜率':>5} {'利润和':>8}")
print('-' * 45)

concept_summary = []
for c, rets in concept_stats.items():
    if len(rets) >= 10:
        concept_summary.append({
            '概念': c,
            '笔数': len(rets),
            '均值': np.mean(rets),
            '胜率': np.mean([1 if r > 0 else 0 for r in rets]) * 100,
            '利润和': np.sum(rets),
        })

concept_summary.sort(key=lambda x: x['利润和'], reverse=True)
for c in concept_summary[:15]:
    marker = ' ★' if c['均值'] > 1 else ''
    print(f"  {c['概念']:<12} {c['笔数']:>3}笔 {c['均值']:>+6.2f}% {c['胜率']:>4.0f}% {c['利润和']:>+7.1f}%{marker}")

# ── 与随机选股对比 ──
print(f"\n{'='*72}")
print("六、新闻选股 vs 全A随机涨停股对比")
print(f"{'='*72}")

# 随机基准：每天随机选3只涨停股，T+1买持有best_hold天
np.random.seed(42)
random_results = []
for date_int in trade_dates:
    if date_int < 20250210 or date_int > 20260110:
        continue
    if date_int not in daily_data:
        continue
    
    # 当天所有涨停股
    all_limit_up = [s for s in daily_data[date_int] 
                    if s['change_pct'] >= 9.5]
    
    if len(all_limit_up) < 3:
        continue
    
    # 随机选3只
    chosen = np.random.choice(len(all_limit_up), min(3, len(all_limit_up)), replace=False)
    
    buy_date = get_next_trade_date(date_int, 1)
    if buy_date is None:
        continue
    
    for idx in chosen:
        s = all_limit_up[idx]
        code = s['code']
        
        if code not in stock_daily or buy_date not in stock_daily[code]:
            continue
        
        buy_data = stock_daily[code][buy_date]
        buy_price = buy_data['open']
        if buy_price <= 0:
            continue
        
        is_20pct = code.startswith('3') or code.startswith('688')
        limit = 20 if is_20pct else 10
        if buy_data['open_pct'] >= limit * 0.98:
            continue
        
        sell_date = get_next_trade_date(buy_date, best_hold)
        if sell_date is None:
            continue
        
        if code in stock_daily and sell_date in stock_daily[code]:
            sell_data = stock_daily[code][sell_date]
            ret = (sell_data['close'] / buy_price - 1) * 100 - 0.15
            random_results.append(ret)

random_avg = np.mean(random_results) if random_results else 0
random_win = np.mean([1 if r > 0 else 0 for r in random_results]) * 100 if random_results else 0
news_avg = best_df['收益%'].mean()
news_win = (best_df['收益%'] > 0).mean() * 100

print(f"\n  新闻热点选股:   {len(best_df):>5}笔  均值{news_avg:>+6.2f}%  胜率{news_win:>4.0f}%")
print(f"  随机涨停股:    {len(random_results):>5}笔  均值{random_avg:>+6.2f}%  胜率{random_win:>4.0f}%")
print(f"  新闻alpha:                均值{news_avg - random_avg:>+6.2f}%  胜率{news_win - random_win:>+4.0f}%")

if news_avg > random_avg:
    print(f"\n  ✅ 新闻选股比随机好 {news_avg - random_avg:.2f}%/笔!")
else:
    print(f"\n  ❌ 新闻选股没有超过随机基准")

# ── 保存信号 ──
best_df.to_csv(f'{OUTPUT_DIR}新闻驱动选股_回测信号.csv', index=False, encoding='utf-8-sig')
print(f"\n信号已保存: {OUTPUT_DIR}新闻驱动选股_回测信号.csv")
print("=" * 72)
