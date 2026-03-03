# A股量化分析项目 · 总索引
> 路径: `/Users/tq/PycharmProjects/stocks_analysis/`
> Python: `/Users/tq/PycharmProjects/stocks_v2/venv/bin/python3`
> 数据: `/Users/tq/Documents/quant_data/`
> 更新: 2026-03-03

---

## 📊 核心策略

### 1. D14黄金稳健版 ⭐ 实战主力
- **操作手册**: [`D14_ACTION_MANUAL.md`](D14_ACTION_MANUAL.md)
- **策略代码**: [`analyze/d14_golden_stable.py`](analyze/d14_golden_stable.py)
- **规则**: 波动率>7 + RSI>60 + 开盘2~8% + 前日<5% + 创/科20%板 + 9:32~9:50首触14% → 13%买入 → 次日+3%止盈或收盘清仓
- **回测**: 57笔/8月, 单笔+3.15%, 胜率72%, 月月正收益, 全仓复利+396%

### 2. 首板策略 (涨停开板)
- **代码**: [`analyze/first_limitup_strategy.py`](analyze/first_limitup_strategy.py)
- **结果**: [`output/first_limitup_strategy_buy7.9pct_next.xlsx`](output/first_limitup_strategy_buy7.9pct_next.xlsx)

---

## 🏆 淘股吧高手研究

### 研究报告
- **总报告**: [`output/淘股吧高手策略深度研究.md`](output/淘股吧高手策略深度研究.md)
- **只核大学生专题**: [`output/只核大学生_策略分析报告.md`](output/只核大学生_策略分析报告.md)

### 交易明细 (标准格式Excel)
| 高手 | 总收益 | 笔数 | 风格 | 文件 |
|:----:|:-----:|:---:|------|------|
| 只核大学生 | +794% | 250 | 超短/追板 | [`tgb_只核大学生_交易价格明细_补齐.xlsx`](output/tgb_只核大学生_交易价格明细_补齐.xlsx) |
| 天牌 | +549% | 550 | 超短/低吸 | [`tgb_天牌_交易明细.xlsx`](output/tgb_天牌_交易明细.xlsx) |
| 低调内敛的朋 | +441% | 195 | 中短/逆势低吸 | [`tgb_低调内敛的朋_交易明细.xlsx`](output/tgb_低调内敛的朋_交易明细.xlsx) |
| 独行侠令狐冲 | +224% | 34 | 中线/精选 | [`tgb_独行侠令狐冲_交易明细.xlsx`](output/tgb_独行侠令狐冲_交易明细.xlsx) |
| 忘忧阁主 | +108% | 363 | 超短/低吸 | [`tgb_忘忧阁主_交易明细.xlsx`](output/tgb_忘忧阁主_交易明细.xlsx) |
| 龙年大叔 | +83% | 42 | 中短/重仓 | [`tgb_龙年大叔_交易明细.xlsx`](output/tgb_龙年大叔_交易明细.xlsx) |
| **全部汇总** | — | **1434** | — | [`tgb_全部高手_交易汇总.xlsx`](output/tgb_全部高手_交易汇总.xlsx) |

### 交易明细列定义
```
高手名, 买入日期, 卖出日期, 股票代码(6位), 股票名称, 持仓天数,
买入价(收盘), 卖出价(收盘), 单笔收益%, 买入日开盘涨幅%,
买入日最高涨幅%, 买入日收盘涨幅%, 前一日涨幅%, 板块(10%板/20%板)
```

### 原始数据
| 文件 | 说明 |
|------|------|
| `output/tgb_batch/` | 5位高手原始持仓明细+收益明细CSV |
| `output/tgb_zhihedaxuesheng_*.csv/json` | 只核大学生原始数据 |
| `output/tgb_交割单截图/` | 只核大学生每日截图(230+张) |
| `output/tgb_802/` | 比赛802当日快照 |

### 高手共同发现
1. **T+1不赚钱**，持3天开始赚(+3.6%)，5天+(+11.9%)
2. **两种赚钱模式**: 逆势低吸(前日小跌) 或 追强势(前日大涨5~10%)
3. **前日涨3~5%最差**
4. **主板>创业板**

---

## 🔬 D14策略研究过程

### 回测数据
| 文件 | 说明 |
|------|------|
| [`output/d14_full_backtest.xlsx`](output/d14_full_backtest.xlsx) | 7549笔全量回测(13月) |
| [`output/d14_monthly_stats.xlsx`](output/d14_monthly_stats.xlsx) | 月度统计 |
| [`output/d14_with_indicators.xlsx`](output/d14_with_indicators.xlsx) | 1269笔D14+技术指标 |
| [`output/d14_optimization_report.md`](output/d14_optimization_report.md) | 639种组合优化报告 |
| [`output/best_strategy_result.xlsx`](output/best_strategy_result.xlsx) | 最优策略交易明细 |

### 分析代码
| 文件 | 功能 |
|------|------|
| `analyze/d14_full_backtest.py` | D14全量回测(7549笔) |
| `analyze/d14_best_strategy.py` | 639种参数组合搜索 |
| `analyze/d14_golden_stable.py` | ⭐ D14黄金稳健版 |
| `analyze/param_optimizer.py` | 参数网格优化器 |
| `analyze/sell_strategy_backtest.py` | 多种卖出策略对比 |
| `analyze/buy_point_comparison.py` | 买入点位分析 |

---

## 🛠 工具脚本

### 淘股吧数据采集
| 文件 | 功能 |
|------|------|
| `scripts/download_tgb_delivery.py` | 下载只核大学生交割单(API) |
| `scripts/download_tgb_batch.py` | 批量下载比赛802高手 |
| `scripts/download_tgb_all.py` | 批量多比赛多用户下载 |
| `scripts/download_tgb_today.py` | 下载指定日期交割单 |
| `scripts/ocr_tgb_screenshots.py` | OCR提取截图持仓(macOS Vision) |
| `scripts/convert_tgb_to_excel.py` | JSON/CSV → 格式化Excel |
| `scripts/fetch_missing_prices.py` | 用K线补齐缺失价格 |
| `scripts/analyze_tgb_trades.py` | 交易模式分析 |

### 基础设施
| 文件 | 功能 |
|------|------|
| `config.py` | 路径配置(KLINE_ROOT等) |
| `data_loader.py` | K线数据加载器(load_kline) |
| `main.py` | 主入口 |

---

## 📁 数据目录
```
/Users/tq/Documents/quant_data/
├── data/                          # TradingView每日全A快照
│   ├── 2025/china_YYYY-MM-DD.csv  # 2025年(147个)
│   └── china_YYYY-MM-DD.csv       # 2026年
├── basic/                         # 基础信息Excel
└── miniqmt_data/                  # K线数据
    ├── 1d/                        # 日线(5478只)
    ├── 1m/                        # 1分钟线(按YYMM子目录)
    ├── 5m/                        # 5分钟线
    └── ...

/Users/tq/Documents/quant_data/交割单/
└── tgb_只核大学生_交易价格明细_2025.xlsx
```

---

## ⚡ 快速上手

```bash
# 进入项目
cd /Users/tq/PycharmProjects/stocks_analysis/

# 使用Python环境
/Users/tq/PycharmProjects/stocks_v2/venv/bin/python3

# 加载K线
from data_loader import load_kline
kl = load_kline('300450', '1d')  # 日线
kl = load_kline('300450', '1m')  # 分钟线

# 加载高手交易数据
import pandas as pd
all_trades = pd.read_excel('output/tgb_全部高手_交易汇总.xlsx')  # 1434笔
d14_signals = pd.read_excel('output/d14_with_indicators.xlsx')   # 1269笔
```
