#!/usr/bin/env python3
"""
遗传算法寻找最优交易策略参数
基于淘股吧高手的历史每日收益数据，优化仓位管理规则

思路:
- 每位高手的每日收益率是"已知信号"（我们不改变选股，只优化仓位管理）
- 遗传算法搜索最优的仓位管理参数组合
- 目标: 在保持收益的同时大幅降低回撤

染色体(策略参数):
  1. base_position     基础仓位 (0.3~1.0)
  2. monday_mult       周一仓位倍数 (0.8~2.0)
  3. friday_mult       周五仓位倍数 (0.3~1.2)
  4. dd_threshold      回撤开始减仓阈值 (0.03~0.20)
  5. dd_reduce_rate    回撤时仓位缩减比例 (0.2~0.8)
  6. big_loss_thresh   大亏阈值% (-3~-10)
  7. after_loss_mult   大亏次日仓位倍数 (0.3~1.5)
  8. consec_loss_max   连亏N天后减仓 (2~8)
  9. consec_loss_cut   连亏减仓比例 (0.2~0.7)
  10. win_streak_min   连赢N天后加仓 (2~6)
  11. win_streak_boost 连赢加仓比例 (0.0~0.5)
  12. recovery_speed   回撤恢复后加仓速度 (0.1~1.0)

适应度函数:
  Sharpe * sqrt(Calmar) * (1 + total_return)
  兼顾收益、波动、回撤三个维度
"""

import json
import math
import random
import os
from datetime import datetime
from copy import deepcopy

# ============================================================
# 配置
# ============================================================
POPULATION_SIZE = 200       # 种群大小
GENERATIONS = 150           # 进化代数
MUTATION_RATE = 0.15        # 变异概率
CROSSOVER_RATE = 0.7        # 交叉概率
ELITE_RATIO = 0.1           # 精英保留比例
TOURNAMENT_SIZE = 5         # 锦标赛选择大小
TRADING_DAYS_PER_YEAR = 243 # 年交易日
RISK_FREE_RATE = 0.02       # 无风险利率

# 基因定义: (名称, 最小值, 最大值, 精度)
GENE_DEFS = [
    ("base_position",    0.30, 1.00, 2),  # 基础仓位
    ("monday_mult",      0.80, 2.00, 2),  # 周一倍数
    ("friday_mult",      0.30, 1.20, 2),  # 周五倍数
    ("dd_threshold",     0.03, 0.20, 3),  # 回撤减仓阈值
    ("dd_reduce_rate",   0.20, 0.80, 2),  # 回撤减仓比例
    ("big_loss_thresh", -10.0, -3.0, 1),  # 大亏阈值
    ("after_loss_mult",  0.30, 1.50, 2),  # 大亏次日倍数
    ("consec_loss_max",  2.00, 8.00, 0),  # 连亏天数上限
    ("consec_loss_cut",  0.20, 0.70, 2),  # 连亏减仓比例
    ("win_streak_min",   2.00, 6.00, 0),  # 连赢加仓阈值
    ("win_streak_boost", 0.00, 0.50, 2),  # 连赢加仓比例
    ("recovery_speed",   0.10, 1.00, 2),  # 恢复速度
]

GENE_NAMES = [g[0] for g in GENE_DEFS]

# ============================================================
# 数据加载
# ============================================================
def load_data():
    """加载所有高手的每日收益数据"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    with open(os.path.join(base_dir, "output/tgb_batch/tgb_all_raw.json"), "r") as f:
        data = json.load(f)
    with open(os.path.join(base_dir, "output/2_淘股吧高手/原始数据/只核大学生/tgb_zhihedaxuesheng_data.json"), "r") as f:
        zhihe = json.load(f)
    
    all_traders = {}
    for u in data["users"]:
        income = sorted(u["income"], key=lambda x: x["dateNum"])
        all_traders[u["user_name"]] = income
    
    all_traders[zhihe["user"]] = sorted(zhihe["income"], key=lambda x: x["dateNum"])
    
    return all_traders


def get_weekday(datenum):
    """日期数字转星期几 (0=周一)"""
    s = str(datenum)
    dt = datetime(int(s[:4]), int(s[4:6]), int(s[6:]))
    return dt.weekday()


# ============================================================
# 策略模拟
# ============================================================
def simulate_strategy(params, daily_returns):
    """
    用给定参数模拟仓位管理策略
    
    params: dict, 策略参数
    daily_returns: list of dict, 每日交易数据
    
    返回: 每日调整后收益率列表, 净值曲线
    """
    base_pos = params["base_position"]
    mon_mult = params["monday_mult"]
    fri_mult = params["friday_mult"]
    dd_thresh = params["dd_threshold"]
    dd_reduce = params["dd_reduce_rate"]
    big_loss = params["big_loss_thresh"]
    loss_mult = params["after_loss_mult"]
    consec_max = int(params["consec_loss_max"])
    consec_cut = params["consec_loss_cut"]
    win_min = int(params["win_streak_min"])
    win_boost = params["win_streak_boost"]
    rec_speed = params["recovery_speed"]
    
    nav = 1.0          # 净值
    peak_nav = 1.0     # 历史最高
    adjusted_returns = []
    nav_curve = [1.0]
    
    consecutive_loss = 0
    consecutive_win = 0
    prev_big_loss = False
    dd_recovery_factor = 1.0  # 回撤恢复因子
    
    for rec in daily_returns:
        raw_return = rec["todayRateD"] / 100  # 原始日收益率
        weekday = get_weekday(rec["dateNum"])
        
        # ---- 计算当前仓位 ----
        position = base_pos
        
        # 1. 周内调整
        if weekday == 0:      # 周一
            position *= mon_mult
        elif weekday == 4:     # 周五
            position *= fri_mult
        
        # 2. 回撤调整
        current_dd = (peak_nav - nav) / peak_nav if peak_nav > 0 else 0
        if current_dd > dd_thresh:
            # 回撤越深，仓位越低
            dd_severity = min((current_dd - dd_thresh) / dd_thresh, 2.0)
            position *= (1 - dd_reduce * dd_severity)
            dd_recovery_factor = 1 - dd_reduce * dd_severity
        else:
            # 逐步恢复仓位
            dd_recovery_factor = min(1.0, dd_recovery_factor + rec_speed * 0.1)
            position *= dd_recovery_factor
        
        # 3. 大亏后调整
        if prev_big_loss:
            position *= loss_mult
            prev_big_loss = False
        
        # 4. 连续亏损调整
        if consecutive_loss >= consec_max:
            position *= (1 - consec_cut)
        
        # 5. 连续盈利加仓
        if consecutive_win >= win_min:
            position *= (1 + win_boost)
        
        # 限制仓位范围
        position = max(0.05, min(position, 1.5))
        
        # ---- 计算调整后收益 ----
        adjusted_return = raw_return * position
        nav *= (1 + adjusted_return)
        
        if nav > peak_nav:
            peak_nav = nav
        
        adjusted_returns.append(adjusted_return)
        nav_curve.append(nav)
        
        # ---- 更新状态 ----
        if raw_return < big_loss / 100:
            prev_big_loss = True
        
        if raw_return < 0:
            consecutive_loss += 1
            consecutive_win = 0
        elif raw_return > 0:
            consecutive_win += 1
            consecutive_loss = 0
        else:
            consecutive_loss = 0
            consecutive_win = 0
    
    return adjusted_returns, nav_curve


def evaluate_fitness(params, all_traders):
    """
    评估策略的适应度
    在所有高手的数据上运行，取综合表现
    """
    scores = []
    
    for name, income in all_traders.items():
        adj_rets, nav_curve = simulate_strategy(params, income)
        
        n = len(adj_rets)
        if n < 30:
            continue
        
        # 总收益
        total_return = nav_curve[-1] - 1
        
        # 年化收益
        ann_return = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / n) - 1
        
        # 日均收益和波动率
        avg_ret = sum(adj_rets) / n
        variance = sum((r - avg_ret) ** 2 for r in adj_rets) / n
        daily_vol = math.sqrt(variance) if variance > 0 else 0.0001
        ann_vol = daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)
        
        # Sharpe
        rf_daily = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        sharpe = (avg_ret - rf_daily) / daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR) if daily_vol > 0 else 0
        
        # 最大回撤
        peak = nav_curve[0]
        max_dd = 0
        for v in nav_curve[1:]:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        max_dd = max(max_dd, 0.001)
        
        # Calmar
        calmar = ann_return / max_dd
        
        # Sortino
        downside = [r for r in adj_rets if r < 0]
        down_var = sum(r ** 2 for r in downside) / n if downside else 0.0001
        down_vol = math.sqrt(down_var) * math.sqrt(TRADING_DAYS_PER_YEAR)
        sortino = (ann_return - RISK_FREE_RATE) / down_vol if down_vol > 0 else 0
        
        # 综合得分: Sharpe * sqrt(Calmar) * log(1 + total_return)
        # 惩罚过大回撤
        dd_penalty = 1.0 if max_dd < 0.20 else (0.8 if max_dd < 0.30 else (0.5 if max_dd < 0.50 else 0.3))
        
        score = sharpe * math.sqrt(max(calmar, 0)) * math.log(1 + max(total_return, 0) + 1) * dd_penalty
        
        scores.append({
            "name": name,
            "score": score,
            "total_return": total_return,
            "ann_return": ann_return,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "max_dd": max_dd,
        })
    
    if not scores:
        return 0, []
    
    # 综合适应度 = 各高手得分的加权平均（给回撤小的高手更高权重）
    total_score = sum(s["score"] for s in scores) / len(scores)
    
    return total_score, scores


# ============================================================
# 遗传算法
# ============================================================
def random_gene(gene_def):
    """随机生成一个基因值"""
    name, lo, hi, prec = gene_def
    val = random.uniform(lo, hi)
    return round(val, prec) if prec > 0 else round(val)


def random_individual():
    """随机生成一个个体"""
    return {g[0]: random_gene(g) for g in GENE_DEFS}


def crossover(parent1, parent2):
    """均匀交叉"""
    child = {}
    for gene_def in GENE_DEFS:
        name = gene_def[0]
        if random.random() < 0.5:
            child[name] = parent1[name]
        else:
            child[name] = parent2[name]
    return child


def mutate(individual):
    """变异: 随机改变一个或多个基因"""
    mutated = individual.copy()
    for gene_def in GENE_DEFS:
        if random.random() < MUTATION_RATE:
            name, lo, hi, prec = gene_def
            # 高斯变异
            range_size = hi - lo
            delta = random.gauss(0, range_size * 0.2)
            new_val = mutated[name] + delta
            new_val = max(lo, min(hi, new_val))
            mutated[name] = round(new_val, prec) if prec > 0 else round(new_val)
    return mutated


def tournament_select(population, fitness_scores):
    """锦标赛选择"""
    candidates = random.sample(list(zip(population, fitness_scores)), min(TOURNAMENT_SIZE, len(population)))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return deepcopy(candidates[0][0])


def run_ga(all_traders):
    """运行遗传算法"""
    print("🧬 初始化种群...")
    population = [random_individual() for _ in range(POPULATION_SIZE)]
    
    # 注入一些基于已有研究的种子个体
    seed_individuals = [
        # 忘忧阁主风格: 中等仓位, 分散
        {"base_position": 0.75, "monday_mult": 1.3, "friday_mult": 0.7,
         "dd_threshold": 0.10, "dd_reduce_rate": 0.4, "big_loss_thresh": -5.0,
         "after_loss_mult": 1.0, "consec_loss_max": 3, "consec_loss_cut": 0.3,
         "win_streak_min": 3, "win_streak_boost": 0.1, "recovery_speed": 0.5},
        # 激进风格
        {"base_position": 0.95, "monday_mult": 1.5, "friday_mult": 0.9,
         "dd_threshold": 0.15, "dd_reduce_rate": 0.3, "big_loss_thresh": -7.0,
         "after_loss_mult": 1.2, "consec_loss_max": 5, "consec_loss_cut": 0.2,
         "win_streak_min": 2, "win_streak_boost": 0.3, "recovery_speed": 0.8},
        # 保守风格
        {"base_position": 0.50, "monday_mult": 1.2, "friday_mult": 0.5,
         "dd_threshold": 0.05, "dd_reduce_rate": 0.6, "big_loss_thresh": -3.0,
         "after_loss_mult": 0.5, "consec_loss_max": 2, "consec_loss_cut": 0.5,
         "win_streak_min": 4, "win_streak_boost": 0.05, "recovery_speed": 0.3},
    ]
    for i, seed in enumerate(seed_individuals):
        population[i] = seed
    
    best_ever_fitness = -float("inf")
    best_ever_individual = None
    best_ever_details = None
    no_improve_count = 0
    
    history = []
    
    print(f"🚀 开始进化! 种群={POPULATION_SIZE}, 代数={GENERATIONS}")
    print(f"   基因数={len(GENE_DEFS)}, 变异率={MUTATION_RATE}, 交叉率={CROSSOVER_RATE}")
    print("=" * 100)
    
    for gen in range(GENERATIONS):
        # 评估适应度
        fitness_scores = []
        all_details = []
        for ind in population:
            score, details = evaluate_fitness(ind, all_traders)
            fitness_scores.append(score)
            all_details.append(details)
        
        # 找本代最优
        best_idx = max(range(len(fitness_scores)), key=lambda i: fitness_scores[i])
        gen_best_fitness = fitness_scores[best_idx]
        gen_best_individual = population[best_idx]
        gen_best_details = all_details[best_idx]
        
        avg_fitness = sum(fitness_scores) / len(fitness_scores)
        
        # 更新全局最优
        if gen_best_fitness > best_ever_fitness:
            best_ever_fitness = gen_best_fitness
            best_ever_individual = deepcopy(gen_best_individual)
            best_ever_details = gen_best_details
            no_improve_count = 0
            marker = "⭐ NEW BEST"
        else:
            no_improve_count += 1
            marker = ""
        
        history.append({
            "gen": gen, "best": gen_best_fitness, "avg": avg_fitness,
            "best_ever": best_ever_fitness,
        })
        
        if gen % 10 == 0 or marker:
            # 简要输出本代最优的效果
            if gen_best_details:
                avg_ret = sum(d["total_return"] for d in gen_best_details) / len(gen_best_details) * 100
                avg_dd = sum(d["max_dd"] for d in gen_best_details) / len(gen_best_details) * 100
                avg_sharpe = sum(d["sharpe"] for d in gen_best_details) / len(gen_best_details)
                print(f"  Gen {gen:>3} | 适应度: {gen_best_fitness:>8.2f} (avg:{avg_fitness:>7.2f}) | "
                      f"均收益:{avg_ret:>7.1f}% 均回撤:{avg_dd:>5.1f}% Sharpe:{avg_sharpe:>5.2f} {marker}")
        
        # 动态调整变异率
        if no_improve_count > 20:
            current_mutation = min(0.4, MUTATION_RATE * 2)
        elif no_improve_count > 10:
            current_mutation = min(0.3, MUTATION_RATE * 1.5)
        else:
            current_mutation = MUTATION_RATE
        
        # 早停
        if no_improve_count > 40:
            print(f"\n  ⏹  连续{no_improve_count}代无改进，提前停止")
            break
        
        # 生成下一代
        elite_count = max(2, int(POPULATION_SIZE * ELITE_RATIO))
        sorted_indices = sorted(range(len(fitness_scores)), key=lambda i: fitness_scores[i], reverse=True)
        
        new_population = []
        
        # 保留精英
        for i in sorted_indices[:elite_count]:
            new_population.append(deepcopy(population[i]))
        
        # 生成剩余个体
        while len(new_population) < POPULATION_SIZE:
            if random.random() < CROSSOVER_RATE:
                p1 = tournament_select(population, fitness_scores)
                p2 = tournament_select(population, fitness_scores)
                child = crossover(p1, p2)
            else:
                child = tournament_select(population, fitness_scores)
            
            # 变异
            child = mutate(child)
            new_population.append(child)
        
        population = new_population
    
    return best_ever_individual, best_ever_fitness, best_ever_details, history


# ============================================================
# 输出结果
# ============================================================
def print_results(best_params, best_fitness, details, history, all_traders):
    """打印最优策略结果"""
    print("\n" + "=" * 100)
    print("🏆 遗传算法搜索完成! 最优策略参数:")
    print("=" * 100)
    
    print("\n📋 最优参数:")
    param_descriptions = {
        "base_position": "基础仓位",
        "monday_mult": "周一仓位倍数",
        "friday_mult": "周五仓位倍数",
        "dd_threshold": "回撤开始减仓阈值",
        "dd_reduce_rate": "回撤减仓比例",
        "big_loss_thresh": "大亏阈值(%)",
        "after_loss_mult": "大亏次日仓位倍数",
        "consec_loss_max": "连亏N天后减仓",
        "consec_loss_cut": "连亏减仓比例",
        "win_streak_min": "连赢N天后加仓",
        "win_streak_boost": "连赢加仓比例",
        "recovery_speed": "回撤恢复加仓速度",
    }
    
    for name, val in best_params.items():
        desc = param_descriptions.get(name, name)
        if name == "big_loss_thresh":
            print(f"  {desc:<20}: {val:>8.1f}%")
        elif name in ("consec_loss_max", "win_streak_min"):
            print(f"  {desc:<20}: {int(val):>8}天")
        elif name in ("dd_threshold",):
            print(f"  {desc:<20}: {val:>8.1%}")
        elif name in ("base_position", "dd_reduce_rate", "consec_loss_cut", "win_streak_boost", "recovery_speed"):
            print(f"  {desc:<20}: {val:>8.0%}")
        else:
            print(f"  {desc:<20}: {val:>8.2f}x")
    
    # 各高手的表现对比
    print(f"\n📊 各高手应用最优策略前后对比:")
    print(f"{'高手':<14} {'原始收益':>10} {'优化收益':>10} {'收益变化':>10} | "
          f"{'原始回撤':>10} {'优化回撤':>10} {'回撤变化':>10} | "
          f"{'原始Sharpe':>10} {'优化Sharpe':>10}")
    print("-" * 110)
    
    for d in details:
        name = d["name"]
        income = all_traders[name]
        
        # 原始表现
        orig_rets = [r["todayRateD"] / 100 for r in income]
        n = len(orig_rets)
        orig_total = income[-1]["totalRateD"] / 100
        
        orig_nav = [1.0]
        for r in orig_rets:
            orig_nav.append(orig_nav[-1] * (1 + r))
        orig_peak = orig_nav[0]
        orig_max_dd = 0
        for v in orig_nav[1:]:
            if v > orig_peak: orig_peak = v
            dd = (orig_peak - v) / orig_peak
            if dd > orig_max_dd: orig_max_dd = dd
        
        orig_avg = sum(orig_rets) / n
        orig_var = sum((r - orig_avg) ** 2 for r in orig_rets) / n
        orig_vol = math.sqrt(orig_var) if orig_var > 0 else 0.0001
        rf_d = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        orig_sharpe = (orig_avg - rf_d) / orig_vol * math.sqrt(TRADING_DAYS_PER_YEAR)
        
        # 优化后
        opt_total = d["total_return"]
        opt_dd = d["max_dd"]
        opt_sharpe = d["sharpe"]
        
        ret_change = (opt_total - orig_total) * 100
        dd_change = (opt_dd - orig_max_dd) * 100
        
        print(f"{name:<14} {orig_total:>9.1%} {opt_total:>9.1%} {ret_change:>+9.1f}pp | "
              f"{orig_max_dd:>9.1%} {opt_dd:>9.1%} {dd_change:>+9.1f}pp | "
              f"{orig_sharpe:>10.2f} {opt_sharpe:>10.2f}")
    
    # 策略解读
    print("\n" + "=" * 100)
    print("💡 最优策略解读:")
    print("=" * 100)
    
    bp = best_params
    print(f"""
  🎯 基础仓位规则:
    • 默认使用 {bp['base_position']:.0%} 仓位运作
    • 周一加仓至 {bp['base_position'] * bp['monday_mult']:.0%} (倍数 {bp['monday_mult']:.2f}x)
    • 周五减仓至 {bp['base_position'] * bp['friday_mult']:.0%} (倍数 {bp['friday_mult']:.2f}x)
    
  🛡️ 风控规则:
    • 回撤超过 {bp['dd_threshold']:.1%} 时开始减仓，减仓比例 {bp['dd_reduce_rate']:.0%}
    • 单日亏损超过 {bp['big_loss_thresh']:.1f}% 后，次日仓位调整为 {bp['after_loss_mult']:.2f}x
    • 连续亏损 {int(bp['consec_loss_max'])} 天后，仓位削减 {bp['consec_loss_cut']:.0%}
    
  📈 进攻规则:
    • 连续盈利 {int(bp['win_streak_min'])} 天后，仓位增加 {bp['win_streak_boost']:.0%}
    • 回撤恢复速度: {bp['recovery_speed']:.0%} (每天恢复仓位的速度)
""")
    
    return best_params


def save_results(best_params, best_fitness, details, history):
    """保存结果"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output/2_淘股吧高手")
    
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    result = {
        "分析时间": time_str,
        "算法参数": {
            "种群大小": POPULATION_SIZE,
            "进化代数": GENERATIONS,
            "变异率": MUTATION_RATE,
            "交叉率": CROSSOVER_RATE,
        },
        "最优适应度": best_fitness,
        "最优策略参数": best_params,
        "各高手表现": details,
        "进化历史": history[-10:],  # 只保存最后10代
    }
    
    # 保存 JSON（供程序使用）
    path = os.path.join(output_dir, "GA最优策略参数.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ JSON 已保存到: {path}")
    
    # 保存人类可读的 Markdown 说明
    save_readable_report(best_params, best_fitness, details, history, time_str, output_dir)


def save_readable_report(bp, best_fitness, details, history, time_str, output_dir):
    """生成人类可读的策略说明 Markdown"""
    
    # 找到收敛的代数
    converge_gen = history[-1]["gen"] if history else 0
    for i in range(1, len(history)):
        if history[i]["best_ever"] == history[-1]["best_ever"] and history[i-1]["best_ever"] != history[i]["best_ever"]:
            converge_gen = history[i]["gen"]
            break
    
    md = f"""# 🏆 遗传算法找到的"最强策略"

> 分析时间: {time_str}
> 算法配置: 种群{POPULATION_SIZE}个 × 进化{GENERATIONS}代，第{converge_gen}代收敛
> 最优适应度: {best_fitness:.2f}

---

## 6条核心规则

| 规则 | 具体操作 | 逻辑 |
|:---|:---|:---|
| 🟢 周一全力进攻 | 仓位 × {bp['monday_mult']:.1f} | 周末利好消化后周一最赚钱 |
| 🔴 周五大幅防守 | 仓位 × {bp['friday_mult']:.1f} | 避免周末不确定性，周五最亏 |
| 💣 大亏后缩手 | 亏>{abs(bp['big_loss_thresh']):.1f}%→次日只用{bp['after_loss_mult']:.0%}仓位 | 避免情绪化连续踩坑 |
| 📈 连赢{int(bp['win_streak_min'])}天加仓 | 仓位 +{bp['win_streak_boost']:.0%} | 手感好时放大收益 |
| ⏸ 连亏{int(bp['consec_loss_max'])}天减仓 | 仓位 -{bp['consec_loss_cut']:.0%} | 市场不配合时收手 |
| 📉 回撤{bp['dd_threshold']:.0%}减仓 | 减{bp['dd_reduce_rate']:.0%}，恢复后快速加回 | 控制最大亏损 |

---

## 基础设定

- **基础仓位**: {bp['base_position']:.0%}
- 所有规则基于基础仓位进行调整

---

## 策略运作示例

### 场景1：周一开盘
> 基础仓位 {bp['base_position']:.0%} × 周一倍数 {bp['monday_mult']:.1f} = **{bp['base_position'] * bp['monday_mult']:.0%} 仓位**

### 场景2：周五收盘前
> 基础仓位 {bp['base_position']:.0%} × 周五倍数 {bp['friday_mult']:.1f} = **{bp['base_position'] * bp['friday_mult']:.0%} 仓位**

### 场景3：某天亏了{abs(bp['big_loss_thresh']):.1f}%以上
> 次日仓位 = 基础仓位 × {bp['after_loss_mult']:.1f} = **{bp['base_position'] * bp['after_loss_mult']:.0%}**（先缩手观望一天）

### 场景4：连赢{int(bp['win_streak_min'])}天
> 仓位增加{bp['win_streak_boost']:.0%} → 如果当前60%仓位，加到 **{0.6 * (1 + bp['win_streak_boost']):.0%}**

### 场景5：连亏{int(bp['consec_loss_max'])}天
> 仓位削减{bp['consec_loss_cut']:.0%} → 如果当前80%仓位，减到 **{0.8 * (1 - bp['consec_loss_cut']):.0%}**

### 场景6：从高点回撤超过{bp['dd_threshold']:.0%}
> 仓位减少{bp['dd_reduce_rate']:.0%}，当净值恢复后以速度{bp['recovery_speed']:.0%}加回仓位

---

## 各高手应用此策略后的表现

| 高手 | 优化后总收益 | 优化后最大回撤 | 优化后Sharpe |
|:---|:---:|:---:|:---:|
"""
    
    for d in sorted(details, key=lambda x: x["total_return"], reverse=True):
        md += f"| {d['name']} | {d['total_return']:.1%} | {d['max_dd']:.1%} | {d['sharpe']:.2f} |\n"
    
    md += f"""
---

## 原始参数（供程序使用）

```json
{json.dumps(bp, ensure_ascii=False, indent=2)}
```
"""
    
    md_path = os.path.join(output_dir, "GA最优策略说明.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✅ 策略说明已保存到: {md_path}")


# ============================================================
# 主程序
# ============================================================
def main():
    print("=" * 100)
    print("🧬 遗传算法 - 淘股吧高手最优仓位管理策略搜索")
    print("=" * 100)
    
    # 加载数据
    print("\n📥 加载交易数据...")
    all_traders = load_data()
    print(f"   已加载 {len(all_traders)} 位高手的数据:")
    for name, income in all_traders.items():
        print(f"   - {name}: {len(income)} 个交易日")
    
    # 运行GA
    random.seed(42)  # 可复现
    best_params, best_fitness, details, history = run_ga(all_traders)
    
    # 输出结果
    print_results(best_params, best_fitness, details, history, all_traders)
    
    # 保存
    save_results(best_params, best_fitness, details, history)


if __name__ == "__main__":
    main()
