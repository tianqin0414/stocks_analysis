"""
stocks_analysis — 配置文件
统一管理数据路径及分析参数
"""
import os
from datetime import datetime, timedelta
from typing import Optional

# ============================================================
#  根目录
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ============================================================
#  数据源路径
#  quant_data 目录下三个符号链接：
#    data       -> stocks_v2/data/          每日全A快照 CSV
#    basic      -> stocks_v2/basic/         基础信息 Excel
#    miniqmt_data -> ~/Documents/miniqmt_data/  K线数据
# ============================================================
QUANT_DATA_ROOT = '/Users/tq/Documents/quant_data'

# 每日全A股快照（china_YYYY-MM-DD.csv）
DAILY_SNAPSHOT_DIR = os.path.join(QUANT_DATA_ROOT, 'data')

# basic 目录（行业/概念/融券等 Excel）
BASIC_DIR = os.path.join(QUANT_DATA_ROOT, 'basic')

# K线数据根目录
KLINE_ROOT = os.path.join(QUANT_DATA_ROOT, 'miniqmt_data')

# 各频率K线目录
KLINE_1D_DIR  = os.path.join(KLINE_ROOT, '1d')
KLINE_5M_DIR  = os.path.join(KLINE_ROOT, '5m')
KLINE_15M_DIR = os.path.join(KLINE_ROOT, '15m')
KLINE_30M_DIR = os.path.join(KLINE_ROOT, '30m')
KLINE_60M_DIR = os.path.join(KLINE_ROOT, '60m')

# ============================================================
#  输出目录
# ============================================================
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
CACHE_DIR  = os.path.join(PROJECT_ROOT, 'cache')

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR,  exist_ok=True)

# ============================================================
#  basic 文件清单（加载时按需合并）
# ============================================================
BASIC_FILES = {
    'rongquan':   'rongquan.xlsx',                # 融券数据
    'stocks':     'A_Stocks1010.xlsx',             # 细分行业
    'concept':    '同花顺概念202508精简.xlsx',      # 省份/概念/公司性质
    'industry':   'Table202508.xlsx',              # 所属行业
    'blacklist':  '立案股票汇总_不重复.xlsx',       # 立案公司名单
}

# ============================================================
#  板块涨停阈值
# ============================================================
def get_limit_pct(code: str) -> float:
    """返回股票涨停幅度：创业板/科创板 20%，其他 10%。"""
    code = str(code).strip()
    if code.startswith('3') or code.startswith('68'):
        return 20.0
    return 10.0

# ============================================================
#  日期工具
# ============================================================
def last_trading_day(ref: Optional[datetime] = None) -> str:
    """返回最近一个工作日（跳过周六/周日），格式 YYYY-MM-DD。"""
    d = ref or datetime.now()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime('%Y-%m-%d')

def get_snapshot_path(date_str: str) -> str:
    """根据日期返回快照 CSV 路径（自动处理 2025 子目录）。"""
    if date_str.startswith('2025'):
        return os.path.join(DAILY_SNAPSHOT_DIR, '2025', f'china_{date_str}.csv')
    return os.path.join(DAILY_SNAPSHOT_DIR, f'china_{date_str}.csv')
