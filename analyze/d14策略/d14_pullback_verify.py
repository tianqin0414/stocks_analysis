#!/usr/bin/env python3
"""
D14买点回落验证
验证：每天最先涨到14%的股票，有多少回落到13%？

用法: python3 d14_pullback_verify.py [月份]
例如: python3 d14_pullback_verify.py 202512
默认: 2025年12月
"""
import pandas as pd
import numpy as np
import os, sys, glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from data_loader import load_kline

BASE_1M = "/Users/tq/Documents/quant_data/miniqmt_data/1m"
KLINE_1D_DIR = "/Users/tq/Documents/quant_data/miniqmt_data/1d"


def get_20pct_codes():
    """获取所有20%板股票（创业板3xx/科创板68xx）"""
    codes = []
    for f in os.listdir(KLINE_1D_DIR):
        if f.endswith('.csv'):
            code = f.split('_')[0]
            if code.startswith('3') or code.startswith('68'):
                codes.append(f.replace('.csv', ''))
    return codes


def scan_d14_pullback(target_month="202512"):
    """
    扫描指定月份的D14信号回落情况
    条件: 20%板 + 开盘2~8% + 9:32~9:50首触14%
    """
    codes_20 = get_20pct_codes()
    print(f"20%板股票: {len(codes_20)}只")
    print(f"扫描月份: {target_month}")
    print(f"条件: 开盘2~8% + 9:32~9:50首触14%")
    print(f"{'='*70}")

    all_signals = []

    for ci, code_key in enumerate(codes_20):
        code6 = code_key.split('_')[0]
        exchange = code_key.split('_')[1]

        kl_1d = load_kline(code6, '1d')
        if kl_1d is None:
            continue

        # 筛选目标月份
        mask = kl_1d['date_str'].str.startswith(target_month)
        cands = kl_1d[mask]

        for _, day in cands.iterrows():
            preClose = float(day['preClose'])
            if preClose <= 0:
                continue
            open_pct = (float(day['open']) / preClose - 1) * 100
            high_pct = (float(day['high']) / preClose - 1) * 100

            # 开盘2~8%, 最高>=14%
            if open_pct < 2 or open_pct > 8:
                continue
            if high_pct < 14:
                continue

            date_str = day['date_str']
            yymm = date_str[2:6]
            month_dir = os.path.join(BASE_1M, yymm)
            if not os.path.isdir(month_dir):
                continue

            matches = glob.glob(os.path.join(month_dir, f"{code6}_{exchange}_*.csv"))
            if not matches:
                continue

            try:
                df_1m = pd.read_csv(matches[0])
            except:
                continue

            df_1m['date_only'] = df_1m['date'].astype(str).str[:8]
            day_1m = df_1m[df_1m['date_only'] == date_str].copy()
            if day_1m.empty:
                continue
            day_1m['hhmm'] = day_1m['date'].astype(str).str[8:12].astype(int)

            target_14 = preClose * 1.14
            target_13 = preClose * 1.13

            # 找9:32~9:50首触14%
            window = day_1m[(day_1m['hhmm'] >= 932) & (day_1m['hhmm'] <= 950)]
            first_idx = None
            for idx, r in window.iterrows():
                if float(r['high']) >= target_14:
                    first_idx = idx
                    break
            if first_idx is None:
                continue

            hit_bar = day_1m.loc[first_idx]
            hit_time = int(hit_bar['hhmm'])
            hit_price = float(hit_bar['high'])
            hit_pct = (hit_price / preClose - 1) * 100

            # 触14%后的最低价
            after = day_1m[day_1m.index >= first_idx]
            min_low = float(after['low'].min())
            min_pct = (min_low / preClose - 1) * 100
            pullback_13 = min_low <= target_13

            # 收盘
            close_p = float(day_1m.iloc[-1]['close'])
            close_pct = (close_p / preClose - 1) * 100

            # 次日收益
            day_idx = kl_1d.index[kl_1d['date_str'] == date_str].tolist()
            next_ret = None
            if day_idx:
                di = day_idx[0]
                if di + 1 < len(kl_1d):
                    nd = kl_1d.iloc[di + 1]
                    # 13%买入, 次日止盈3%/收盘卖
                    buy_p = target_13 if pullback_13 else target_14
                    tp = buy_p * 1.03
                    n_open = float(nd['open'])
                    n_high = float(nd['high'])
                    n_close = float(nd['close'])
                    if n_open >= tp:
                        sell_p = n_open
                    elif n_high >= tp:
                        sell_p = tp
                    else:
                        sell_p = n_close
                    next_ret = round((sell_p / buy_p - 1) * 100, 2)

            stock_name = ""
            try:
                stock_name = day.get('name', '') or ''
            except:
                pass

            all_signals.append({
                'date': date_str,
                'code': code6,
                'name': stock_name,
                'hit_time': hit_time,
                'open_pct': round(open_pct, 2),
                'hit_pct': round(hit_pct, 2),
                'min_after_pct': round(min_pct, 2),
                'close_pct': round(close_pct, 2),
                'pullback_13': pullback_13,
                'next_ret': next_ret,
            })

        if (ci + 1) % 500 == 0:
            print(f"  [{ci+1}/{len(codes_20)}] {len(all_signals)}个信号", flush=True)

    if not all_signals:
        print("没有找到D14信号")
        return

    df = pd.DataFrame(all_signals)
    df = df.sort_values(['date', 'hit_time'])

    # 每天第1个信号
    df['rank'] = df.groupby('date').cumcount() + 1
    first = df[df['rank'] == 1].copy()

    N = len(first)
    n_pb = first['pullback_13'].sum()
    n_no = N - n_pb

    print(f"\n{'='*70}")
    print(f"📊 {target_month} D14回落验证结果")
    print(f"{'='*70}")
    print(f"每天最先触14%的股票: {N}天有信号\n")
    print(f"🎯 回落到13%: {n_pb}/{N} = {n_pb/N*100:.1f}%")
    print(f"❌ 不回落:     {n_no}/{N} = {n_no/N*100:.1f}%\n")

    # 逐日明细
    print(f"{'日期':<12} {'代码':<8} {'触发时间':<8} {'开盘%':>6} {'最低%':>6} {'收盘%':>6} {'回落13%':>8} {'次日收益':>8}")
    print("-" * 70)

    for _, r in first.iterrows():
        d = r['date']
        date_fmt = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        pb = "✅ 是" if r['pullback_13'] else "❌ 否"
        nr = f"{r['next_ret']:+.2f}%" if r['next_ret'] is not None else "N/A"
        print(f"{date_fmt:<12} {r['code']:<8} {r['hit_time']:<8} "
              f"{r['open_pct']:>+5.1f}% {r['min_after_pct']:>+5.1f}% "
              f"{r['close_pct']:>+5.1f}% {pb:>8} {nr:>8}")

    # 不回落的详情
    no_pb = first[~first['pullback_13']]
    if not no_pb.empty:
        print(f"\n❌ 不回落到13%的{len(no_pb)}天详情:")
        for _, r in no_pb.iterrows():
            d = r['date']
            print(f"  {d[:4]}-{d[4:6]}-{d[6:8]} {r['code']} "
                  f"触发{r['hit_time']} 最低{r['min_after_pct']:+.1f}% "
                  f"收盘{r['close_pct']:+.1f}%")

    # 收益统计
    has_ret = first['next_ret'].notna()
    if has_ret.any():
        pb_ret = first[first['pullback_13'] & has_ret]['next_ret']
        print(f"\n📈 次日收益统计:")
        print(f"  回落到13%买入的: {len(pb_ret)}笔, "
              f"均值{pb_ret.mean():+.2f}%, 胜率{(pb_ret>0).mean()*100:.0f}%")
        if not no_pb.empty:
            no_ret = no_pb[no_pb['next_ret'].notna()]['next_ret']
            if not no_ret.empty:
                print(f"  不回落(放弃)的: {len(no_ret)}笔, "
                      f"如果14%追入均值{no_ret.mean():+.2f}%")


if __name__ == "__main__":
    month = sys.argv[1] if len(sys.argv) > 1 else "202512"
    scan_d14_pullback(month)
