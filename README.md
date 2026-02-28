# stocks_analysis

基于 `/Users/tq/Documents/quant_data` 的 A 股量化分析项目。

## 数据源

| 目录 | 内容 |
|------|------|
| `quant_data/data/` | 每日全A快照 CSV（TradingView 格式，含RSI/技术评级/价格等100+列） |
| `quant_data/basic/` | 基础信息 Excel（行业/概念/融券等） |
| `quant_data/miniqmt_data/1d/` | 日线K线（5478只股票） |
| `quant_data/miniqmt_data/5m/` | 5分钟K线 |

## 快速开始

```bash
cd /Users/tq/PycharmProjects/stocks_analysis

# 使用 stocks_v2 的虚拟环境
alias py=/Users/tq/PycharmProjects/stocks_v2/venv/bin/python

# 每日选股扫描（RSI 强势 + 涨幅 + 放量）
py analyze/daily_scan.py --date 2026-02-13 --top 20

# K线分析（000001 平安银行）
py analyze/kline_stats.py 000001

# 板块强弱排名
py analyze/sector.py --date 2026-02-13

# 查找特定概念
py analyze/sector.py --concept 新能源 --date 2026-02-13

# 涨停板分布统计
py analyze/sector.py --limit-up --date 2026-02-13

# 策略回测（base / daban / reversal / trend）
py analyze/strategy.py --date 2026-02-13 --preset base
py analyze/strategy.py --start 2026-01-05 --end 2026-02-13 --preset daban --save
```

## 模块说明

| 脚本 | 功能 |
|------|------|
| `analyze/daily_scan.py` | 每日选股：RSI + 技术评级 + 放量 + 价格过滤 |
| `analyze/kline_stats.py` | 技术指标计算：MA/RSI/MACD/布林带/ATR |
| `analyze/sector.py` | 板块分析：行业涨跌排名、概念搜索、涨停统计 |
| `analyze/strategy.py` | 策略回测：4种预设，输出胜率/收益统计 |
| `data_loader.py` | 数据加载工具（快照、K线、基础信息） |
| `config.py` | 路径配置 |

## 预设策略

| 策略 | 描述 |
|------|------|
| `base` | 高分强势股（RSI健康区间 + 上涨 + 技术评级买入） |
| `daban` | 打板（盘中涨停股） |
| `reversal` | 超卖反转（RSI<35 + 当日回升） |
| `trend` | 月线趋势（月涨10%+ + RSI 50~80） |

## 配置

编辑 `config.py` 修改数据路径；编辑各模块顶部的 `*_CONFIG` 字典调整筛选参数。
