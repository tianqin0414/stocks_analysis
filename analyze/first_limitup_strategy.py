"""
analyze/first_limitup_strategy.py — 首板策略回测

策略规则：
  1. 主板股票（0xx / 6xx，排除 688 科创板 / 北交所）
  2. "首板"：当日收盘涨停 & 前一交易日未涨停
  3. 当日 9:50 前封板（1m K线 close == 涨停价）
  4. 连续封板 ≥ 30 分钟（1m K线连续 30 根以上 close ≈ 涨停价）
  5. 开板后价格回落至 +7.9%（即 preClose × 1.079）→ 记为"买入价"
  6. 出场：次日收盘卖出（同时记录次日最高/最低供参考）

输出指标：
  股票代码, 日期, 封板时间, 开板时间, 买入价, preClose,
  前日涨跌幅(%), 开盘涨幅(%), 首次封板涨幅,
  封板持续(分钟), 当日收盘涨幅(%),
  次日开盘涨幅(%), 次日最高涨幅(%), 次日收盘涨幅(%),
  盈亏(%)

运行方式:
    cd /Users/tq/PycharmProjects/stocks_analysis
    /Users/tq/Desktop/stocks_data/stock-downloader/venv/bin/python3 \\
        analyze/first_limitup_strategy.py
    # 可选参数:
    #   --drawback  5.5    (开板后回落幅度，默认7.9，即+7.9%买入)
    #   --exit      next   (出场方式: next=次日收盘, same=当日收盘)
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

# ============================================================
# 常量
# ============================================================
DEC_START    = '20251201'
DEC_END      = '20251231'
KLINE_1D_DIR = os.path.join(KLINE_ROOT, '1d')
KLINE_1M_DIR = os.path.join(KLINE_ROOT, '1m')

LIMIT_PCT         = 0.10   # 主板涨停幅度
LIMIT_UP_THRESH   = 0.099  # 判定"处于涨停"的最低涨幅（容错 0.1%）
SEAL_BEFORE_TIME  = '09:50'
MIN_SEAL_MINUTES  = 30     # 最短连续封板分钟数
BUY_GAIN_PCT      = 7.9    # 开板后买入点（相对 preClose 的涨幅%）


# ============================================================
# 工具：判断主板（0xx / 6xx，排除 688）
# ============================================================
def is_main_board(code: str) -> bool:
    c = str(code).strip()
    if c.startswith('688'):
        return False  # 科创板
    return c.startswith('0') or c.startswith('6')


# ============================================================
# 工具：找 1m 文件（20251201_20251231）
# ============================================================
_1m_cache: Dict[str, Optional[pd.DataFrame]] = {}


def load_1m_dec(code: str) -> Optional[pd.DataFrame]:
    if code in _1m_cache:
        return _1m_cache[code]

    # 推断交易所后缀
    c = str(code)
    if c.startswith('6'):
        exch = 'SH'
    else:
        exch = 'SZ'

    pattern = os.path.join(KLINE_1M_DIR,
                           '{}_{}_{}_{}*.csv'.format(code, exch, '20251201', '20251231'))
    files = glob.glob(pattern)
    if not files:
        _1m_cache[code] = None
        return None

    try:
        df = pd.read_csv(files[0], encoding='utf-8-sig')
    except Exception:
        _1m_cache[code] = None
        return None

    req = {'date', 'open', 'high', 'low', 'close'}
    if not req.issubset(df.columns):
        _1m_cache[code] = None
        return None

    df['date_str'] = df['date'].astype(str).str[:8]

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
    if 'preClose' in df.columns:
        df['preClose'] = pd.to_numeric(df['preClose'], errors='coerce')

    _1m_cache[code] = df.reset_index(drop=True)
    return _1m_cache[code]


# ============================================================
# 核心：单只股票单日策略分析
# ============================================================
def analyze_day(code: str,
                date_str: str,
                df_1d: pd.DataFrame,
                buy_gain_pct: float = BUY_GAIN_PCT,
                exit_mode: str = 'next',
                seal_before: str = SEAL_BEFORE_TIME,
                min_seal: int = MIN_SEAL_MINUTES) -> Optional[dict]:
    """
    返回 dict 或 None（不满足条件）。
    exit_mode: 'next' = 次日收盘卖出，'same' = 当日收盘卖出
    """
    # ---------- 1. 基础日线数据 ----------
    idx_list = df_1d.index[df_1d['date_str'] == date_str].tolist()
    if not idx_list:
        return None
    idx_1d = idx_list[0]
    day = df_1d.iloc[idx_1d]

    pre_close = pd.to_numeric(day.get('preClose', None), errors='coerce')
    if pd.isna(pre_close) or pre_close <= 0:
        if idx_1d == 0:
            return None
        pre_close = df_1d.iloc[idx_1d - 1]['close']
    if pd.isna(pre_close) or pre_close <= 0:
        return None

    close_p = pd.to_numeric(day['close'], errors='coerce')
    open_p  = pd.to_numeric(day['open'],  errors='coerce')
    if pd.isna(close_p) or pd.isna(open_p):
        return None

    limit_price = round(pre_close * (1 + LIMIT_PCT), 2)

    # 当日需涨停（收盘 ≈ 涨停价）
    if (close_p - limit_price) / limit_price < -0.005:
        return None  # 当日未以涨停收盘

    # ---------- 2. 首板：前一日未涨停 ----------
    if idx_1d == 0:
        return None  # 没有前日数据
    prev      = df_1d.iloc[idx_1d - 1]
    prev_c    = pd.to_numeric(prev['close'],    errors='coerce')
    prev_pc   = pd.to_numeric(prev.get('preClose', None), errors='coerce')
    if pd.isna(prev_pc) or prev_pc <= 0:
        if idx_1d >= 2:
            prev_pc = df_1d.iloc[idx_1d - 2]['close']
    if pd.isna(prev_pc) or prev_pc <= 0:
        return None

    prev_limit = round(prev_pc * (1 + LIMIT_PCT), 2)
    prev_was_limit = (not pd.isna(prev_c)) and (abs(prev_c - prev_limit) / prev_limit <= 0.005)
    if prev_was_limit:
        return None  # 昨日也涨停 → 非首板

    # ---------- 3. 前一日涨跌幅 ----------
    prev_close_pct = (prev_c - prev_pc) / prev_pc * 100 if not pd.isna(prev_c) else None

    # ---------- 4. 加载当日 1m K线 ----------
    df_1m_all = load_1m_dec(code)
    if df_1m_all is None:
        return None

    day_1m = df_1m_all[df_1m_all['date_str'] == date_str].copy().reset_index(drop=True)
    if len(day_1m) == 0:
        return None

    # ---------- 5. 判断 9:50 前是否封板 ----------
    # "封板" = 1m bar 的 close >= limit_price × 0.999
    limit_thresh = limit_price * (1 - 0.001)
    sealed = day_1m['close'] >= limit_thresh

    # 找首次封板时间
    first_seal_idx = sealed.idxmax() if sealed.any() else None
    if first_seal_idx is None:
        return None
    first_seal_time = day_1m.at[first_seal_idx, 'time_str']

    if first_seal_time > seal_before:
        return None  # 晚于 seal_before 才封板

    # ---------- 6. 连续封板 ≥ 30 分钟 ----------
    # 从首次封板那一根 K 线开始，向后数有多少根连续封板
    # 遇到第一根非封板即停（只看初始那段，防止开板后下午再封板被计入）
    seal_start_idx = first_seal_idx
    seal_end_idx   = first_seal_idx
    for i in range(first_seal_idx, len(day_1m)):
        if sealed[i]:
            seal_end_idx = i
        else:
            break  # 首次开板，停止计数

    seal_duration = seal_end_idx - seal_start_idx + 1

    if seal_duration < min_seal:
        return None  # 初始连续封板 < min_seal 分钟

    seal_start_time = day_1m.at[seal_start_idx, 'time_str']

    # ---------- 7. 开板检测：seal_end_idx 后首次开板 ----------
    open_start = seal_end_idx + 1 if seal_end_idx is not None else None
    if open_start is None or open_start >= len(day_1m):
        # 全天封板未开板 → 策略不触发（无买点）
        return None

    # 检查 seal_end_idx 是否是真实"开板"（收盘价低于涨停价）
    # 即在 seal_start_idx~seal_end_idx 之后，价格脱离涨停
    open_idx = None
    open_time = None
    for i in range(open_start, len(day_1m)):
        if not sealed[i]:
            open_idx  = i
            open_time = day_1m.at[i, 'time_str']
            break

    if open_idx is None:
        return None  # 一直封板到收盘

    # ---------- 8. 开板后是否回落到 buy_gain_pct ----------
    buy_price = round(pre_close * (1 + buy_gain_pct / 100), 3)
    buy_idx   = None
    buy_time  = None

    for i in range(open_idx, len(day_1m)):
        row = day_1m.iloc[i]
        # 当根 K 线的 low 触及买入价
        if row['low'] <= buy_price:
            buy_idx  = i
            buy_time = row['time_str']
            break

    if buy_idx is None:
        return None  # 开板后未回落到 buy_gain_pct → 不触发

    # ---------- 9. 出场：次日收盘 ----------
    close_gain  = (close_p - pre_close) / pre_close * 100
    open_gain   = (open_p  - pre_close) / pre_close * 100
    profit_pct  = None
    next_open_g = None
    next_high_g = None
    next_close_g = None

    if exit_mode == 'same':
        # 当日收盘出场
        profit_pct = (close_p - buy_price) / buy_price * 100
    else:
        # 次日出场
        next_idx = idx_1d + 1
        if next_idx < len(df_1d):
            nxt     = df_1d.iloc[next_idx]
            nxt_c   = pd.to_numeric(nxt['close'], errors='coerce')
            nxt_o   = pd.to_numeric(nxt['open'],  errors='coerce')
            nxt_h   = pd.to_numeric(nxt['high'],  errors='coerce')
            nxt_pc  = pd.to_numeric(nxt.get('preClose', None), errors='coerce')
            if pd.isna(nxt_pc) or nxt_pc <= 0:
                nxt_pc = close_p
            if not pd.isna(nxt_c) and not pd.isna(nxt_pc):
                next_close_g = (nxt_c - nxt_pc) / nxt_pc * 100
                profit_pct   = (nxt_c - buy_price) / buy_price * 100
            if not pd.isna(nxt_o):
                next_open_g  = (nxt_o - nxt_pc) / nxt_pc * 100
            if not pd.isna(nxt_h):
                next_high_g  = (nxt_h - nxt_pc) / nxt_pc * 100

    return {
        '股票代码':          code,
        '日期':              date_str,
        '前日涨跌幅(%)':     round(prev_close_pct, 2) if prev_close_pct is not None else None,
        '开盘涨幅(%)':       round(open_gain, 2),
        '封板时间':          seal_start_time,
        '封板持续(分钟)':    seal_duration,
        '开板时间':          open_time,
        '买入时间':          buy_time,
        'preClose':          round(pre_close, 3),
        '买入价(+{}%)'.format(buy_gain_pct): buy_price,
        '当日收盘涨幅(%)':   round(close_gain, 2),
        '次日开盘涨幅(%)':   round(next_open_g,  2) if next_open_g  is not None else None,
        '次日最高涨幅(%)':   round(next_high_g,  2) if next_high_g  is not None else None,
        '次日收盘涨幅(%)':   round(next_close_g, 2) if next_close_g is not None else None,
        '盈亏(%)':           round(profit_pct, 2)    if profit_pct   is not None else None,
    }


def run_backtest(buy_gain_pct: float = BUY_GAIN_PCT,
                 exit_mode: str = 'next',
                 seal_before: str = SEAL_BEFORE_TIME,
                 min_seal: int = MIN_SEAL_MINUTES,
                 verbose: bool = True) -> pd.DataFrame:
    """完整回测，返回结果 DataFrame。供优化器批量调用。"""
    all_1d = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    code_files: Dict[str, List[str]] = {}
    for f in all_1d:
        bn    = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) < 4:
            continue
        code_   = parts[0]
        exch    = parts[1]
        start_d = parts[2]
        end_d   = parts[3].replace('.csv', '')
        if exch == 'BJ':
            continue
        if not is_main_board(code_):
            continue
        if start_d <= DEC_END and end_d >= DEC_START:
            key = '{}_{}'.format(code_, exch)
            code_files.setdefault(key, []).append(f)

    results = []
    for key, files in sorted(code_files.items()):
        code_ = key.split('_')[0]
        dfs = []
        for f in sorted(files):
            try:
                df = pd.read_csv(f, encoding='utf-8-sig')
                if not {'date','open','high','low','close'}.issubset(df.columns):
                    continue
                df['date_str'] = df['date'].astype(str).str[:8]
                cols = ['date_str','open','high','low','close']
                if 'preClose' in df.columns:
                    cols.append('preClose')
                for col in ['open','high','low','close']:
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
        df_dec = df_1d[(df_1d['date_str'] >= DEC_START) & (df_1d['date_str'] <= DEC_END)]
        for abs_idx, drow in df_dec.iterrows():
            pc = drow.get('preClose', None)
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                pc = float('nan')
            if pd.isna(pc) or pc <= 0:
                pos = df_1d.index.get_loc(abs_idx)
                if pos > 0:
                    pc = float(df_1d.iloc[pos - 1]['close'])
            if pd.isna(pc) or pc <= 0:
                continue
            lp = round(pc * 1.10, 2)
            c  = drow['close']
            if pd.isna(c) or abs(c - lp) / lp > 0.005:
                continue
            rec = analyze_day(code_, drow['date_str'], df_1d,
                              buy_gain_pct, exit_mode, seal_before, min_seal)
            if rec:
                results.append(rec)

    if not results:
        return pd.DataFrame()
    df_res = pd.DataFrame(results)
    df_res = df_res.sort_values(['日期', '封板时间']).reset_index(drop=True)
    return df_res
# ============================================================
# 主流程（命令行入口）
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='首板策略回测')
    parser.add_argument('--drawback',   type=float, default=BUY_GAIN_PCT,
                        help='开板后买入点（涨幅%，默认 7.9）')
    parser.add_argument('--exit',       default='next', choices=['next', 'same'],
                        help='出场方式：next=次日收盘（默认），same=当日收盘')
    parser.add_argument('--seal-before', default=SEAL_BEFORE_TIME,
                        help='封板截止时间（默认 09:50）')
    parser.add_argument('--min-seal',   type=int, default=MIN_SEAL_MINUTES,
                        help='最短连续封板分钟数（默认 30）')
    args = parser.parse_args()

    buy_gain_pct = args.drawback
    exit_mode    = args.exit
    seal_before  = args.seal_before
    min_seal     = args.min_seal

    print("🎯 首板策略回测（主板）")
    print("   条件：{}前封板 & 连续封板≥{}分钟 & 开板回落至+{}%".format(
          seal_before, min_seal, buy_gain_pct))
    print("   出场：{}日收盘".format('次' if exit_mode == 'next' else '当'))
    print("=" * 65)

    # --- 找主板 + 覆盖12月 的日线文件 ---
    all_1d = glob.glob(os.path.join(KLINE_1D_DIR, '*.csv'))
    code_files: Dict[str, List[str]] = {}
    for f in all_1d:
        bn    = os.path.basename(f)
        parts = bn.split('_')
        if len(parts) < 4:
            continue
        code    = parts[0]
        exch    = parts[1]
        start_d = parts[2]
        end_d   = parts[3].replace('.csv', '')
        if exch == 'BJ':
            continue
        if not is_main_board(code):
            continue
        if start_d <= DEC_END and end_d >= DEC_START:
            key = '{}_{}'.format(code, exch)
            code_files.setdefault(key, []).append(f)

    total = len(code_files)
    print("  主板股票数（含12月数据）: {}".format(total))

    results = []

    for i, (key, files) in enumerate(sorted(code_files.items())):
        code = key.split('_')[0]

        if (i + 1) % 1000 == 0:
            print("  进度 {}/{}  命中: {}".format(i + 1, total, len(results)))

        # 合并日线
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

        # 快速预筛选：12月哪些天日线收盘涨停？
        df_dec = df_1d[(df_1d['date_str'] >= DEC_START) & (df_1d['date_str'] <= DEC_END)]
        for abs_idx, drow in df_dec.iterrows():
            pc = drow.get('preClose', None)
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                pc = float('nan')
            if pd.isna(pc) or pc <= 0:
                pos = df_1d.index.get_loc(abs_idx)
                if pos > 0:
                    pc = float(df_1d.iloc[pos - 1]['close'])
            if pd.isna(pc) or pc <= 0:
                continue
            lp = round(pc * 1.10, 2)
            c  = drow['close']
            if pd.isna(c):
                continue
            # 仅当日收盘 ≈ 涨停价才进入详细分析
            if abs(c - lp) / lp > 0.005:
                continue

            rec = analyze_day(code, drow['date_str'], df_1d, buy_gain_pct, exit_mode)
            if rec:
                results.append(rec)

    print("\n✅ 扫描完成  触发买点: {} 笔".format(len(results)))

    if not results:
        print("  ⚠️  无满足条件的交易")
        return

    df_res = pd.DataFrame(results)
    df_res = df_res.sort_values(['日期', '封板时间']).reset_index(drop=True)

    # --- 输出统计 ---
    pnl = df_res['盈亏(%)'].dropna()
    print("\n" + "=" * 65)
    print("📊 策略回测统计  （2025年12月，主板首板）")
    print("=" * 65)
    print("  总触发笔数:   {}".format(len(df_res)))
    print("  有效P&L数:    {}".format(len(pnl)))
    if len(pnl) > 0:
        win  = (pnl > 0).sum()
        loss = (pnl <= 0).sum()
        print("  胜率:         {:.1f}%  ({} 盈 / {} 亏)".format(
              (pnl > 0).mean() * 100, win, loss))
        print("  平均盈亏:     {:+.2f}%".format(pnl.mean()))
        print("  中位盈亏:     {:+.2f}%".format(pnl.median()))
        print("  最大盈利:     {:+.2f}%".format(pnl.max()))
        print("  最大亏损:     {:+.2f}%".format(pnl.min()))
        print("  总收益（等权）: {:+.2f}%".format(pnl.sum()))

    # 按日期分布
    print("\n  按日期笔数：")
    date_cnt = df_res.groupby('日期')['股票代码'].count()
    for d, cnt in date_cnt.items():
        pnl_d = df_res[df_res['日期'] == d]['盈亏(%)'].dropna()
        avg_d = pnl_d.mean() if len(pnl_d) > 0 else float('nan')
        print("    {}  {}笔  平均{:+.2f}%".format(d, cnt, avg_d))

    # 全量数据预览
    print("\n📋 全部交易明细：")
    pd.set_option('display.width', 260)
    pd.set_option('display.max_columns', 20)
    print(df_res.to_string(index=False))

    # 保存
    col_buy = '买入价(+{}%)'.format(buy_gain_pct)
    out_path = os.path.join(OUTPUT_DIR,
        'first_limitup_strategy_buy{}pct_{}.xlsx'.format(
            buy_gain_pct, exit_mode))
    df_res.to_excel(out_path, index=False)
    print("\n💾 已保存: {}".format(out_path))


if __name__ == '__main__':
    main()
