"""
analyze/dec_surge_14pct.py — 2025年12月 峰值涨幅超14% 股票分析

输出列：
  股票代码, 日期, 首次达标时间, 首次达标价格,
  preClose, 上一日收跌幅(%), 开盘涨幅(%),
  峰值涨幅(%), 回撤18%时涨幅(%), 收盘涨幅(%),
  次日涨跌幅(%), 能否买到

数据来源（均从 miniqmt_data/ 读取）:
  - 日线: 1d/  (文件名覆盖12月)
  - 分钟线: 1m/CODE_EXCH_20251201_20251231.csv

用法:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 analyze/dec_surge_14pct.py
"""
from __future__ import annotations

import os
import sys
import glob
import argparse
from typing import Optional, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config import KLINE_ROOT, OUTPUT_DIR
from data_loader import code_to_exchange

# ============================================================
# 参数
# ============================================================
THRESHOLD_PCT = 14.0
DRAWDOWN_PCT  = 18.0
DEC_START     = '20251201'
DEC_END       = '20251231'

KLINE_1D_DIR = os.path.join(KLINE_ROOT, '1d')
KLINE_1M_DIR = os.path.join(KLINE_ROOT, '1m')


# ============================================================
# 辅助：加载 1m K线（覆盖12月）
# ============================================================
_1m_cache: Dict[str, Optional[pd.DataFrame]] = {}


def load_1m_dec(code: str) -> Optional[pd.DataFrame]:
    """加载某只股票的1分钟K线（仅12月），带内存缓存。"""
    if code in _1m_cache:
        return _1m_cache[code]

    exchange = code_to_exchange(code)
    fname_pattern = '{}_{}_{}_{}*.csv'.format(code, exchange, DEC_START, DEC_END)
    # 先在根目录找，再在子目录找（如 1m/2512/）
    pattern = os.path.join(KLINE_1M_DIR, fname_pattern)
    files = glob.glob(pattern)
    if not files:
        pattern = os.path.join(KLINE_1M_DIR, '**', fname_pattern)
        files = glob.glob(pattern, recursive=True)
    if not files:
        _1m_cache[code] = None
        return None

    try:
        df = pd.read_csv(files[0], encoding='utf-8-sig')
    except Exception as e:
        print("  ⚠️  1m读取失败 {}: {}".format(code, e))
        _1m_cache[code] = None
        return None

    req = {'date', 'open', 'high', 'low', 'close'}
    if not req.issubset(df.columns):
        _1m_cache[code] = None
        return None

    df['date_str'] = df['date'].astype(str).str[:8]

    # time 列是 UTC 毫秒时间戳 → 转北京时间
    if 'time' in df.columns:
        df['time_str'] = (
            pd.to_datetime(df['time'], unit='ms', utc=True)
            .dt.tz_convert('Asia/Shanghai')
            .dt.strftime('%H:%M')
        )
    else:
        df['time_str'] = '09:30'

    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    _1m_cache[code] = df.reset_index(drop=True)
    return _1m_cache[code]


# ============================================================
# 核心分析：单只股票某一日
# ============================================================
def analyze_one_day(code: str, date_str: str,
                    df_1d: pd.DataFrame,
                    threshold: float,
                    drawdown: float) -> Optional[dict]:
    idx_list = df_1d.index[df_1d['date_str'] == date_str].tolist()
    if not idx_list:
        return None
    idx_1d = idx_list[0]
    day = df_1d.iloc[idx_1d]

    # --- preClose ---
    pre_close = pd.to_numeric(day.get('preClose', None), errors='coerce')
    if pd.isna(pre_close) or pre_close <= 0:
        if idx_1d == 0:
            return None
        pre_close = df_1d.iloc[idx_1d - 1]['close']
    if pd.isna(pre_close) or pre_close <= 0:
        return None

    open_p  = pd.to_numeric(day['open'],  errors='coerce')
    high_p  = pd.to_numeric(day['high'],  errors='coerce')
    close_p = pd.to_numeric(day['close'], errors='coerce')
    if pd.isna(high_p) or pd.isna(close_p) or pd.isna(open_p):
        return None

    peak_pct  = (high_p - pre_close) / pre_close * 100
    if peak_pct < threshold:
        return None

    open_pct  = (open_p  - pre_close) / pre_close * 100
    close_pct = (close_p - pre_close) / pre_close * 100

    # --- 上一日收(跌)幅 ---
    prev_close_pct = None
    if idx_1d > 0:
        prev    = df_1d.iloc[idx_1d - 1]
        prev_c  = pd.to_numeric(prev['close'], errors='coerce')
        prev_pc = pd.to_numeric(prev.get('preClose', None), errors='coerce')
        if (pd.isna(prev_pc) or prev_pc <= 0) and idx_1d >= 2:
            prev_pc = df_1d.iloc[idx_1d - 2]['close']
        if not pd.isna(prev_c) and not pd.isna(prev_pc) and prev_pc > 0:
            prev_close_pct = (prev_c - prev_pc) / prev_pc * 100

    # --- 次日涨跌幅 ---
    next_day_pct = None
    if idx_1d < len(df_1d) - 1:
        nxt    = df_1d.iloc[idx_1d + 1]
        nxt_c  = pd.to_numeric(nxt['close'], errors='coerce')
        nxt_pc = pd.to_numeric(nxt.get('preClose', None), errors='coerce')
        if pd.isna(nxt_pc) or nxt_pc <= 0:
            nxt_pc = close_p
        if not pd.isna(nxt_c) and not pd.isna(nxt_pc) and nxt_pc > 0:
            next_day_pct = (nxt_c - nxt_pc) / nxt_pc * 100

    # --- 回撤 drawdown% 后涨幅（相对 preClose）---
    drawback_price = high_p * (1 - drawdown / 100)
    drawback_pct   = (drawback_price - pre_close) / pre_close * 100

    # --- 1m线：首次达标 & 能否买到 ---
    first_time  = None
    first_price = None
    can_buy     = '无1m数据'

    df_1m_all = load_1m_dec(code)
    if df_1m_all is not None:
        day_1m = df_1m_all[df_1m_all['date_str'] == date_str].copy().reset_index(drop=True)
        if len(day_1m) > 0:
            is_star_or_cyb = str(code).startswith('3') or str(code).startswith('68')
            limit_pct  = 0.20 if is_star_or_cyb else 0.10
            limit_price = pre_close * (1 + limit_pct)

            target_price = pre_close * (1 + threshold / 100)
            hit_rows = day_1m[day_1m['high'] >= target_price]

            if len(hit_rows) > 0:
                first_row   = hit_rows.iloc[0]
                first_time  = first_row['time_str']
                first_price = round(target_price, 3)
                hit_idx     = hit_rows.index[0]

                last_1m = day_1m.iloc[-1]
                is_limit_up = (
                    abs(last_1m['close'] - limit_price) <= limit_price * 0.005
                    and abs(last_1m['close'] - last_1m['high']) < 0.002
                )
                remaining = len(day_1m) - 1 - hit_idx
                hit_time  = first_row['time_str']

                if is_limit_up and hit_idx <= 5:
                    can_buy = '难以买到（开盘即涨停）'
                elif is_limit_up:
                    can_buy = '难以买到（涨停封死，{}封板）'.format(hit_time)
                elif remaining >= 15:
                    can_buy = '可以买到（{}达标，剩{}分钟）'.format(hit_time, remaining)
                elif remaining > 0:
                    can_buy = '较难买到（{}达标，剩{}分钟）'.format(hit_time, remaining)
                else:
                    can_buy = '难以买到（收盘最后1分钟达标）'
            else:
                can_buy = '未在1m中找到达标点'

    return {
        '股票代码':         code,
        '日期':             date_str,
        '首次达标时间':     first_time,
        '首次达标价格':     first_price,
        'preClose':         round(pre_close, 3),
        '上一日收跌幅(%)':  round(prev_close_pct, 2) if prev_close_pct is not None else None,
        '开盘涨幅(%)':      round(open_pct,   2),
        '峰值涨幅(%)':      round(peak_pct,   2),
        '回撤18%时涨幅(%)': round(drawback_pct, 2),
        '收盘涨幅(%)':      round(close_pct,  2),
        '次日涨跌幅(%)':    round(next_day_pct, 2) if next_day_pct is not None else None,
        '能否买到':         can_buy,
    }


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='2025年12月 峰值涨幅超14% 股票分析')
    parser.add_argument('--threshold', type=float, default=THRESHOLD_PCT)
    parser.add_argument('--drawdown',  type=float, default=DRAWDOWN_PCT)
    args = parser.parse_args()
    threshold = args.threshold
    drawdown  = args.drawdown

    print("🔍 扫描 2025年12月 峰值涨幅 ≥ {}%".format(threshold))
    print("   回撤定义: 从峰值回撤 {}%".format(drawdown))
    print("=" * 65)

    # Step1: 找所有含12月日线文件
    all_1d_files = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    code_files: Dict[str, List[str]] = {}
    for f in all_1d_files:
        bn    = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) < 4:
            continue
        key     = '{}_{}'.format(parts[0], parts[1])
        start_d = parts[2]
        end_d   = parts[3].replace('.csv', '')
        if start_d <= DEC_END and end_d >= DEC_START:
            code_files.setdefault(key, []).append(f)

    total_codes = len(code_files)
    print("  日线文件覆盖12月: {} 只股票".format(total_codes))

    results = []

    for i, (key, files) in enumerate(sorted(code_files.items())):
        # 跳过北交所
        if key.endswith('_BJ'):
            continue
        code = key.split('_')[0]

        if (i + 1) % 1000 == 0:
            print("  进度: {}/{}  命中: {}".format(i + 1, total_codes, len(results)))

        dfs = []
        for f in sorted(files):
            try:
                df = pd.read_csv(f, encoding='utf-8-sig')
                if not {'date', 'open', 'high', 'low', 'close'}.issubset(df.columns):
                    continue
                df['date_str'] = df['date'].astype(str).str[:8]
                cols = ['date_str', 'open', 'high', 'low', 'close']
                if 'preClose' in df.columns:
                    cols.append('preClose')
                for col in ['open', 'high', 'low', 'close']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                if 'preClose' in df.columns:
                    df['preClose'] = pd.to_numeric(df['preClose'], errors='coerce')
                dfs.append(df[cols])
            except Exception:
                continue

        if not dfs:
            continue

        df_1d = (pd.concat(dfs)
                 .drop_duplicates('date_str')
                 .sort_values('date_str')
                 .reset_index(drop=True))

        # 快速过滤：12月是否有峰值涨幅 >= threshold
        df_dec = df_1d[(df_1d['date_str'] >= DEC_START) & (df_1d['date_str'] <= DEC_END)]
        if len(df_dec) == 0:
            continue

        candidate_dates = []
        for loc_in_1d, (abs_idx, drow) in enumerate(df_dec.iterrows()):
            pc = drow.get('preClose', None)
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                pc = float('nan')
            if pd.isna(pc) or pc <= 0:
                # fallback: 取 df_1d 中该行之前一行 close
                pos = df_1d.index.get_loc(abs_idx)
                if pos > 0:
                    pc = df_1d.iloc[pos - 1]['close']
            if pd.isna(pc) or pc <= 0:
                continue
            high_p = drow['high']
            if pd.isna(high_p):
                continue
            if (high_p - pc) / pc * 100 >= threshold:
                candidate_dates.append(drow['date_str'])

        if not candidate_dates:
            continue

        for date_str in candidate_dates:
            rec = analyze_one_day(code, date_str, df_1d, threshold, drawdown)
            if rec:
                results.append(rec)

    print("\n✅ 扫描完成  命中 {} 条".format(len(results)))

    if not results:
        print("  ⚠️  未找到满足条件的股票，请检查数据路径")
        return

    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values(['日期', '峰值涨幅(%)'], ascending=[True, False]).reset_index(drop=True)

    # 控制台预览
    print("\n📊 结果预览（前50条）：")
    pd.set_option('display.max_columns', 20)
    pd.set_option('display.width', 220)
    preview_cols = ['股票代码', '日期', '首次达标时间', 'preClose',
                    '上一日收跌幅(%)', '开盘涨幅(%)', '峰值涨幅(%)',
                    '回撤18%时涨幅(%)', '收盘涨幅(%)', '次日涨跌幅(%)', '能否买到']
    print(result_df[preview_cols].head(50).to_string(index=False))

    # 汇总统计
    print("\n📈 汇总统计（共 {} 条）：".format(len(result_df)))
    print("  峰值涨幅  均值={:.2f}%  最大={:.2f}%".format(
        result_df['峰值涨幅(%)'].mean(), result_df['峰值涨幅(%)'].max()))
    print("  收盘涨幅  均值={:.2f}%".format(result_df['收盘涨幅(%)'].mean()))
    nd = result_df['次日涨跌幅(%)'].dropna()
    if len(nd) > 0:
        print("  次日涨跌  均值={:.2f}%  正收益比={:.1f}%".format(
            nd.mean(), (nd > 0).mean() * 100))
    buy_dist = result_df['能否买到'].value_counts()
    print("\n  能否买到分布：\n{}".format(buy_dist.to_string()))

    out_path = os.path.join(OUTPUT_DIR, 'dec2025_surge_{}pct.xlsx'.format(int(threshold)))
    result_df.to_excel(out_path, index=False)
    print("\n💾 已保存: {}".format(out_path))


if __name__ == '__main__':
    main()
