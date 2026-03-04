#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
高手交易 vs 重大会议/政策事件 交叉分析
目标: 验证高手是否在重大会议前后集中交易特定板块
"""

import pandas as pd
import numpy as np

# ── 2025年重大政策事件时间线 ──
events = [
    # (日期, 事件名称, 可能受益板块关键词)
    ('20250217', '习近平民营企业座谈会(马云马化腾雷军任正非等)', '人工智能,科技,互联网,新能源,消费电子'),
    ('20250305', '两会开幕(政府工作报告)', '新质生产力,数字经济,消费,新能源,半导体'),
    ('20250311', '两会闭幕', '两会概念'),
    ('20250401', '东部战区台海演训', '军工,航天,国防'),
    ('20250402', '特朗普对华加征34%关税', '自主可控,国产替代,半导体,芯片'),
    ('20250409', '中国对美加征关税至84%', '贸易战反制,稀土,农业'),
    ('20250411', '中国对美关税提至125%', '国产替代,内需消费'),
    ('20250507', '歼10实战击落(印巴空战)', '军工,航空,中航系'),
    ('20250512', '中美日内瓦经贸会谈(关税降至10%)', '出口,贸易,科技'),
    ('20250719', '雅鲁藏布江水电工程动工', '水电,基建,电力'),
    # 常规重要会议（估计时间）
    ('20250430', '4月政治局会议(一季度经济分析)', '经济刺激,消费,基建'),
    ('20250730', '7月政治局会议(半年经济分析)', '经济刺激,科技,房地产'),
    ('20251030', '10月五中全会/政治局会议', '十五五规划,科技,新能源'),
    ('20251210', '12月中央经济工作会议', '明年经济政策,消费,科技'),
]

events_df = pd.DataFrame(events, columns=['date', 'event', 'keywords'])
events_df['date'] = events_df['date'].astype(int)

# ── 加载高手交易数据 ──
xlsx_files = {
    '天牌': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_天牌_交易明细.xlsx',
    '独行侠令狐冲': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_独行侠令狐冲_交易明细.xlsx',
    '忘忧阁主': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_忘忧阁主_交易明细.xlsx',
    '低调内敛的朋': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_低调内敛的朋_交易明细.xlsx',
    '龙年大叔': '/Users/tq/PycharmProjects/stocks_analysis/output/tgb_龙年大叔_交易明细.xlsx',
}

all_trades = []
for name, f in xlsx_files.items():
    df = pd.read_excel(f)
    for col in ['持仓天数','单笔收益%','买入日开盘涨幅%','买入日最高涨幅%','买入日收盘涨幅%','前一日涨幅%']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['买入日期'] = pd.to_numeric(df['买入日期'], errors='coerce').astype('Int64')
    df['卖出日期'] = pd.to_numeric(df['卖出日期'], errors='coerce').astype('Int64')
    all_trades.append(df)

all_df = pd.concat(all_trades, ignore_index=True)
all_df = all_df.dropna(subset=['单笔收益%','买入日期'])
all_df = all_df[all_df['单笔收益%'].between(-50, 100)]  # 清洗异常值

# 加载概念数据
concepts_df = pd.read_excel('/Users/tq/Documents/quant_data/basic/A_Stocks1010.xlsx')
concepts_df['商品代码'] = concepts_df['商品代码'].astype(str).str.zfill(6)
# 建立代码→概念映射
code_to_concepts = dict(zip(concepts_df['商品代码'], concepts_df['同花顺概念old'].fillna('')))
code_to_name = dict(zip(concepts_df['商品代码'], concepts_df['名称'].fillna('')))

# 给交易添加概念
all_df['股票代码str'] = all_df['股票代码'].astype(str).str.zfill(6)
all_df['概念'] = all_df['股票代码str'].map(code_to_concepts).fillna('')

print("=" * 72)
print("高手交易 vs 重大会议/政策事件 交叉分析")
print(f"数据: {len(all_df)}笔交易, {len(events)}个重大事件")
print("=" * 72)

# ═══════════════════════════════════════════
# 1. 每个事件前后的交易密度和收益
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("一、重大事件前后交易分析")
print("═" * 72)

for _, ev in events_df.iterrows():
    ev_date = ev['date']
    ev_name = ev['event']
    ev_kw = ev['keywords'].split(',')
    
    # 事件前5天买入的交易
    before = all_df[(all_df['买入日期'] >= ev_date - 7) & (all_df['买入日期'] < ev_date)]
    # 事件后5天买入的交易
    after = all_df[(all_df['买入日期'] >= ev_date) & (all_df['买入日期'] <= ev_date + 7)]
    # 正常期（事件前后各1个月但排除前后7天）
    normal = all_df[
        ((all_df['买入日期'] >= ev_date - 30) & (all_df['买入日期'] < ev_date - 7)) |
        ((all_df['买入日期'] > ev_date + 7) & (all_df['买入日期'] <= ev_date + 30))
    ]
    
    if len(before) + len(after) < 3:
        continue
    
    print(f"\n{'─'*60}")
    print(f"📅 {ev_date} {ev_name}")
    print(f"{'─'*60}")
    
    for label, sub in [('事件前7天', before), ('事件后7天', after), ('正常期(1月)', normal)]:
        if len(sub) > 0:
            avg = sub['单笔收益%'].mean()
            win = (sub['单笔收益%']>0).mean()*100
            
            # 检查是否买了相关概念的票
            related = 0
            for _, trade in sub.iterrows():
                for kw in ev_kw:
                    if kw in str(trade['概念']):
                        related += 1
                        break
            
            print(f"  {label:<12} {len(sub):>3}笔  均值{avg:>+6.2f}%  胜率{win:>4.0f}%  相关概念{related}笔({related/len(sub)*100:.0f}%)")

# ═══════════════════════════════════════════
# 2. 高手买入股票的概念词频统计（按月）
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("二、高手买入股票概念词频（按月TOP5）")
print("═" * 72)

all_df['买入月'] = (all_df['买入日期'] // 100).astype(int)

# 主要概念关键词
hot_concepts = ['人工智能','机器人','芯片','半导体','军工','新能源','消费电子',
                '光伏','储能','汽车','锂电','AI','算力','数据','国产替代',
                '华为','卫星','航天','低空经济','自动驾驶','CPO','液冷','核电']

months = sorted(all_df['买入月'].unique())
for m in months:
    msub = all_df[all_df['买入月'] == m]
    if len(msub) < 5:
        continue
    
    # 统计每个概念出现次数
    concept_counts = {}
    for _, trade in msub.iterrows():
        concepts = str(trade['概念'])
        for kw in hot_concepts:
            if kw in concepts:
                concept_counts[kw] = concept_counts.get(kw, 0) + 1
    
    if concept_counts:
        top5 = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top5_str = ', '.join([f"{k}({v})" for k,v in top5])
        avg_ret = msub['单笔收益%'].mean()
        print(f"  {m}({len(msub)}笔,均{avg_ret:+.1f}%): {top5_str}")

# ═══════════════════════════════════════════
# 3. 各高手的概念偏好
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("三、各高手概念偏好 TOP10")
print("═" * 72)

for name in ['天牌', '忘忧阁主', '低调内敛的朋', '独行侠令狐冲', '龙年大叔']:
    sub = all_df[all_df['高手名'] == name]
    if len(sub) < 10:
        continue
    
    concept_counts = {}
    concept_returns = {}
    for _, trade in sub.iterrows():
        concepts = str(trade['概念'])
        for kw in hot_concepts:
            if kw in concepts:
                concept_counts[kw] = concept_counts.get(kw, 0) + 1
                if kw not in concept_returns:
                    concept_returns[kw] = []
                concept_returns[kw].append(trade['单笔收益%'])
    
    if concept_counts:
        top10 = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"\n【{name}】{len(sub)}笔")
        for kw, count in top10:
            pct = count / len(sub) * 100
            avg_ret = np.mean(concept_returns[kw])
            win = np.mean([1 if r > 0 else 0 for r in concept_returns[kw]]) * 100
            print(f"  {kw:<8} {count:>3}笔({pct:>4.0f}%)  均值{avg_ret:>+6.2f}%  胜率{win:>4.0f}%")

# ═══════════════════════════════════════════
# 4. 关键发现：哪些概念最赚钱
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("四、全部高手 - 最赚钱的概念板块")
print("═" * 72)

all_concept_stats = {}
for _, trade in all_df.iterrows():
    concepts = str(trade['概念'])
    for kw in hot_concepts:
        if kw in concepts:
            if kw not in all_concept_stats:
                all_concept_stats[kw] = []
            all_concept_stats[kw].append(trade['单笔收益%'])

print(f"\n{'概念':<10} {'笔数':>5} {'均值':>7} {'胜率':>5} {'利润和':>8}")
print(f"{'─'*45}")

concept_summary = []
for kw, rets in all_concept_stats.items():
    if len(rets) >= 10:
        concept_summary.append({
            '概念': kw,
            '笔数': len(rets),
            '均值': np.mean(rets),
            '胜率': np.mean([1 if r > 0 else 0 for r in rets]) * 100,
            '利润和': np.sum(rets),
        })

concept_summary.sort(key=lambda x: x['利润和'], reverse=True)
for c in concept_summary:
    marker = ' ★' if c['均值'] > 2 else ''
    print(f"  {c['概念']:<10} {c['笔数']:>4}笔 {c['均值']:>+6.2f}% {c['胜率']:>4.0f}% {c['利润和']:>+7.1f}%{marker}")

# ═══════════════════════════════════════════
# 5. 特朗普关税事件深度分析
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("五、特朗普关税战期间(4月)高手操作详情")
print("═" * 72)

april = all_df[(all_df['买入日期'] >= 20250401) & (all_df['买入日期'] <= 20250430)]
print(f"4月交易: {len(april)}笔  均值{april['单笔收益%'].mean():+.2f}%  胜率{(april['单笔收益%']>0).mean()*100:.0f}%")

# 关税前后
pre_tariff = all_df[(all_df['买入日期'] >= 20250325) & (all_df['买入日期'] <= 20250401)]
tariff_week = all_df[(all_df['买入日期'] >= 20250402) & (all_df['买入日期'] <= 20250411)]
post_tariff = all_df[(all_df['买入日期'] >= 20250414) & (all_df['买入日期'] <= 20250430)]

for label, sub in [('关税前(3.25-4.1)', pre_tariff), ('关税加征期(4.2-4.11)', tariff_week), ('关税稳定后(4.14-4.30)', post_tariff)]:
    if len(sub) > 0:
        avg = sub['单笔收益%'].mean()
        win = (sub['单笔收益%']>0).mean()*100
        # 概念分布
        concept_counts = {}
        for _, t in sub.iterrows():
            for kw in hot_concepts:
                if kw in str(t['概念']):
                    concept_counts[kw] = concept_counts.get(kw, 0) + 1
        top3_kw = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        kw_str = ', '.join([f"{k}({v})" for k,v in top3_kw]) if top3_kw else ''
        print(f"  {label:<20} {len(sub):>3}笔 均值{avg:>+6.2f}% 胜率{win:>4.0f}%  热门: {kw_str}")

# ═══════════════════════════════════════════
# 6. 中美谈判后(5月12日)
# ═══════════════════════════════════════════
print("\n" + "═" * 72)
print("六、中美日内瓦谈判后(5.12)高手操作")
print("═" * 72)

pre_deal = all_df[(all_df['买入日期'] >= 20250505) & (all_df['买入日期'] <= 20250512)]
post_deal = all_df[(all_df['买入日期'] >= 20250513) & (all_df['买入日期'] <= 20250523)]

for label, sub in [('谈判前(5.5-5.12)', pre_deal), ('谈判后(5.13-5.23)', post_deal)]:
    if len(sub) > 0:
        avg = sub['单笔收益%'].mean()
        win = (sub['单笔收益%']>0).mean()*100
        concept_counts = {}
        for _, t in sub.iterrows():
            for kw in hot_concepts:
                if kw in str(t['概念']):
                    concept_counts[kw] = concept_counts.get(kw, 0) + 1
        top3_kw = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        kw_str = ', '.join([f"{k}({v})" for k,v in top3_kw]) if top3_kw else ''
        print(f"  {label:<20} {len(sub):>3}笔 均值{avg:>+6.2f}% 胜率{win:>4.0f}%  热门: {kw_str}")

print("\n" + "=" * 72)
