"""
data_loader.py — 统一数据加载工具

提供以下功能：
  - load_snapshot(date)       加载某日全A快照
  - load_kline(code, freq)    加载某股K线（支持 1d/5m/15m/30m/60m）
  - load_basic(name)          加载 basic 目录中的基础信息
  - load_all_klines(codes)    批量加载多只股票K线（带缓存）
"""
import os
import re
import glob
from collections import defaultdict
from functools import lru_cache
from typing import Optional, List, Dict

import pandas as pd

from config import (
    DAILY_SNAPSHOT_DIR, BASIC_DIR, BASIC_FILES,
    KLINE_ROOT, KLINE_1D_DIR,
    get_snapshot_path,
)


# ============================================================
#  股票代码工具
# ============================================================
def normalize_code(code) -> str:
    """统一股票代码格式为纯6位字符串，如 '300952.SZ' -> '300952'。"""
    s = str(code).strip()
    s = re.sub(r'\.(SZ|SH|BJ)$', '', s, flags=re.IGNORECASE)
    return s.zfill(6) if s.isdigit() else s


def code_to_exchange(code: str) -> str:
    """推断交易所后缀（SH / SZ / BJ）。"""
    code = str(code).strip()
    if code.startswith('6'):
        return 'SH'
    elif code.startswith(('4', '8')):
        return 'BJ'
    return 'SZ'


# ============================================================
#  快照数据（每日全A，china_YYYY-MM-DD.csv）
# ============================================================
def load_snapshot(date_str: str) -> Optional[pd.DataFrame]:
    """
    加载指定日期的全A快照 CSV。

    参数:
        date_str: 'YYYY-MM-DD' 格式

    返回:
        DataFrame（含100+列技术指标），文件不存在时返回 None。
    """
    path = get_snapshot_path(date_str)
    if not os.path.exists(path):
        print(f"  ⚠️  快照不存在: {date_str}")
        return None

    df = pd.read_csv(path, encoding='utf-8-sig', low_memory=False)

    # 原始快照列名规范化
    # TradingView 导出格式：第一列为 "商品代码"
    if '商品代码' in df.columns and '证券代码' not in df.columns:
        df = df.rename(columns={'商品代码': '证券代码'})

    # 价格列别名
    if '价格' not in df.columns and '收盘价' in df.columns:
        df['价格'] = df['收盘价']

    # 当日最高涨幅 = (最高价 1天 - 前收盘) / 前收盘 * 100
    # 原始数据中用 "价格变动 % 1天" 近似当日涨幅
    # "最高涨幅" 用 "最高价 1天" 与 "价格" 推算（近似）
    if '最高涨幅' not in df.columns:
        if '最高价 1天' in df.columns and '价格' in df.columns:
            price = pd.to_numeric(df['价格'], errors='coerce')
            high_1d = pd.to_numeric(df['最高价 1天'], errors='coerce')
            change_pct = pd.to_numeric(df.get('价格变动 % 1天', pd.Series(dtype=float)), errors='coerce')
            prev_close = price / (1 + change_pct / 100)
            df['最高涨幅'] = ((high_1d - prev_close) / prev_close * 100).round(3)

    if '证券代码' in df.columns:
        df['证券代码'] = df['证券代码'].apply(normalize_code)
    df['快照日期'] = date_str
    return df


def list_snapshot_dates(year: Optional[int] = None) -> List[str]:
    """列出所有可用的快照日期（YYYY-MM-DD 格式，从新到旧排序）。"""
    patterns = []
    if year:
        year_dir = os.path.join(DAILY_SNAPSHOT_DIR, str(year))
        if os.path.isdir(year_dir):
            patterns.append(os.path.join(year_dir, 'china_*.csv'))
        patterns.append(os.path.join(DAILY_SNAPSHOT_DIR, f'china_{year}-*.csv'))
    else:
        patterns.append(os.path.join(DAILY_SNAPSHOT_DIR, '**', 'china_*.csv'))

    dates: set = set()
    for pat in patterns:
        for f in glob.glob(pat, recursive=True):
            bn = os.path.basename(f)          # china_2026-01-05.csv
            date = bn[6:16]                   # 2026-01-05
            dates.add(date)

    return sorted(dates, reverse=True)


# ============================================================
#  K线数据（miniqmt_data/1d/、5m/ 等）
# ============================================================

# 文件索引缓存：{freq: {code_exchange: [filepath, ...]}}
_KLINE_INDEX: Dict[str, dict] = {}


def _build_kline_index(freq: str = '1d') -> dict:
    """构建指定频率的 K 线文件索引（懒加载）。"""
    if freq in _KLINE_INDEX:
        return _KLINE_INDEX[freq]

    kline_dir = os.path.join(KLINE_ROOT, freq)
    index = defaultdict(list)
    if not os.path.isdir(kline_dir):
        print(f"  ⚠️  K线目录不存在: {kline_dir}")
        _KLINE_INDEX[freq] = index
        return index

    for fname in os.listdir(kline_dir):
        if not fname.endswith('.csv'):
            continue
        parts = fname.split('_')  # 000001_SZ_20260101_20260205.csv
        if len(parts) >= 2:
            key = f'{parts[0]}_{parts[1]}'   # 000001_SZ
            index[key].append(os.path.join(kline_dir, fname))

    _KLINE_INDEX[freq] = index
    print(f"  ✅ K线索引[{freq}]: {len(index)} 只股票")
    return index


def load_kline(code: str, freq: str = '1d') -> Optional[pd.DataFrame]:
    """
    加载单只股票 K 线数据。

    参数:
        code:  6位股票代码（纯数字）
        freq:  '1d' | '5m' | '15m' | '30m' | '60m'

    返回:
        按日期排序的 DataFrame（date_str/open/high/low/close/volume/amount），
        找不到时返回 None。
    """
    code = normalize_code(code)
    exchange = code_to_exchange(code)
    key = f'{code}_{exchange}'

    index = _build_kline_index(freq)
    files = index.get(key, [])
    if not files:
        return None

    dfs = []
    for f in sorted(files):  # 按文件名（时间段）排序
        try:
            df = pd.read_csv(f, encoding='utf-8-sig')
            req_cols = {'date', 'open', 'high', 'low', 'close', 'volume'}
            if req_cols.issubset(df.columns):
                df['date_str'] = df['date'].astype(str).str[:8]
                cols = ['date_str', 'open', 'high', 'low', 'close', 'volume']
                if 'amount' in df.columns:
                    cols.append('amount')
                if 'preClose' in df.columns:
                    cols.append('preClose')
                dfs.append(df[cols].copy())
        except Exception as e:
            print(f"  ⚠️  读取失败 {os.path.basename(f)}: {e}")

    if not dfs:
        return None

    result = pd.concat(dfs, ignore_index=True)
    result = (result
              .drop_duplicates(subset='date_str')
              .sort_values('date_str')
              .reset_index(drop=True))
    return result


def load_klines_batch(codes: List[str], freq: str = '1d',
                      show_progress: bool = True) -> Dict[str, pd.DataFrame]:
    """
    批量加载多只股票 K 线。

    返回:
        {code: DataFrame}，找不到的股票不会出现在字典中。
    """
    _build_kline_index(freq)  # 预先建索引
    result = {}
    total = len(codes)
    for i, code in enumerate(codes):
        if show_progress and (i + 1) % 200 == 0:
            print(f"  进度: {i+1}/{total}")
        df = load_kline(code, freq)
        if df is not None:
            result[code] = df
    if show_progress:
        print(f"  ✅ 批量加载 [{freq}]: {len(result)}/{total} 只股票")
    return result


# ============================================================
#  Basic 基础数据
# ============================================================
@lru_cache(maxsize=16)
def load_basic(name: str) -> Optional[pd.DataFrame]:
    """
    加载 basic 目录中的基础信息文件（带 LRU 缓存）。

    参数:
        name: 'stocks' | 'concept' | 'industry' | 'rongquan' | 'blacklist'
              或完整文件名如 'A_Stocks1010.xlsx'

    返回:
        DataFrame，找不到时返回 None。
    """
    filename = BASIC_FILES.get(name, name)
    path = os.path.join(BASIC_DIR, filename)
    if not os.path.exists(path):
        print(f"  ⚠️  basic 文件不存在: {filename}")
        return None

    if filename.endswith('.csv'):
        df = pd.read_csv(path, encoding='utf-8-sig')
    else:
        df = pd.read_excel(path)

    print(f"  ✅ 加载 basic[{name}]: {len(df)} 行")
    return df


# ============================================================
#  辅助：计算前向收益
# ============================================================
def calc_forward_returns(kline: pd.DataFrame, buy_date: str,
                         days: int = 5, buy_price: Optional[float] = None,
                         stop_loss_pct: float = 5.0) -> Optional[dict]:
    """
    计算从 buy_date 收盘后持有 days 个交易日的收益指标。

    返回:
        {max_high_pct, close_pct, stop_pct}
        - max_high_pct: 持有期内最高涨幅（%）
        - close_pct:    第 days 日收盘涨幅（%）
        - stop_pct:     动态回撤 stop_loss_pct% 止损后收益（%）
    """
    date_fmt = buy_date.replace('-', '')
    idx_arr = kline.index[kline['date_str'] == date_fmt].tolist()
    if not idx_arr:
        return None

    buy_idx = idx_arr[0]
    if buy_idx >= len(kline) - 1:
        return None

    price = buy_price if buy_price else kline.at[buy_idx, 'close']
    if not price or price <= 0:
        return None

    end_idx = min(buy_idx + days + 1, len(kline))
    future = kline.iloc[buy_idx + 1:end_idx]
    if len(future) == 0:
        return None

    max_high = future['high'].max()
    close_price = future.iloc[-1]['close']

    # 动态回撤止损
    peak = price
    sell = None
    for _, row in future.iterrows():
        if row['high'] > peak:
            peak = row['high']
        stop = peak * (1 - stop_loss_pct / 100)
        if row['low'] <= stop:
            sell = stop
            break

    return {
        'max_high_pct': round((max_high - price) / price * 100, 2),
        'close_pct':    round((close_price - price) / price * 100, 2),
        'stop_pct':     round((sell - price) / price * 100, 2) if sell else round((close_price - price) / price * 100, 2),
    }
