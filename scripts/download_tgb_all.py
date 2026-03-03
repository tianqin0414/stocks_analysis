#!/usr/bin/env python3
"""
批量下载淘股吧实盘比赛交割单 - 全历史数据
支持多比赛、多用户
"""
import json
import time
import urllib.request
import csv
import os
import sys
from datetime import datetime

# === 配置 ===
OUTPUT_DIR = "/Users/tq/PycharmProjects/stocks_analysis/output/tgb_batch"

TASKS = [
    # (比赛序号, 用户ID)
    ("858", "10580905"),   # 龙年大叔
    ("802", "1120338"),    # 天牌
    ("802", "7386521"),    # 忘忧阁主
    ("802", "5452924"),    # 低调内敛的朋
    ("802", "9157318"),    # 独行侠令狐冲
]

COOKIES = (
    "tgbuser=12810600; "
    "tgbpwd=8daecd30e53af3098373334ba74c00c865a577cb782a854686a2e0d46979905dfpfqtq2qbqmq9v0; "
    "loginStatus=phone"
)

BASE_URL = "https://www.tgb.cn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Cookie": COOKIES,
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

def stock_code_to_display(full_code):
    if full_code and len(full_code) > 2:
        return full_code[2:]
    return full_code

def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ❌ 请求失败: {e}", flush=True)
        return None

def fetch_all_income(spmatch_seq, user_id):
    """获取所有页面的日度收益数据"""
    all_records = []
    page = 1
    while True:
        url = f"{BASE_URL}/spmatch/gains/listIncome?spmatchSeq={spmatch_seq}&endDateNum=&lookUserID={user_id}&pageNo={page}"
        data = fetch_json(url)
        if not data or not data.get("status"):
            break
        dto = data.get("dto", {})
        records = dto.get("list", [])
        total_pages = dto.get("pageNum", 1)
        if not records:
            break
        all_records.extend(records)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.2)
    return all_records

def fetch_trades_for_date(spmatch_seq, user_id, date_num):
    """获取指定日期的持仓/交易明细"""
    url = f"{BASE_URL}/spmatch/gains/listChiCangMatch?spmatchSeq={spmatch_seq}&lookeuserID={user_id}&type=ALL&date={date_num}&pageNo=1"
    data = fetch_json(url)
    if data and data.get("status"):
        return data.get("dto", {}).get("list", [])
    return []

def download_user(spmatch_seq, user_id):
    """下载单个用户的全部数据"""
    print(f"\n{'='*50}", flush=True)
    print(f"📥 比赛{spmatch_seq} 用户{user_id}", flush=True)
    
    # 1. 收益概况
    income_records = fetch_all_income(spmatch_seq, user_id)
    if not income_records:
        print(f"  ❌ 无数据", flush=True)
        return None
    
    name = income_records[0].get("userName", user_id)
    total_rate = income_records[0].get("totalRateD", "N/A")
    print(f"  ✅ {name} | {len(income_records)}天 | 总收益{total_rate}%", flush=True)
    
    # 2. 每日持仓明细
    all_trades = {}
    dates = list(dict.fromkeys([str(r["endDateNum"]) for r in income_records]))
    
    for i, date_str in enumerate(dates):
        trades = fetch_trades_for_date(spmatch_seq, user_id, date_str)
        if trades:
            all_trades[date_str] = trades
        time.sleep(0.15)
        if (i + 1) % 50 == 0:
            print(f"    进度: {i+1}/{len(dates)} 天", flush=True)
            time.sleep(0.5)
    
    total_trades = sum(len(v) for v in all_trades.values())
    print(f"  ✅ 持仓: {len(all_trades)}天 {total_trades}条记录", flush=True)
    
    return {
        "spmatch_seq": spmatch_seq,
        "user_id": user_id,
        "user_name": name,
        "income": income_records,
        "trades": all_trades,
    }

def save_user_csv(d, output_dir):
    """保存单个用户的CSV"""
    safe_name = d["user_name"].replace("/", "_").replace(" ", "_")
    seq = d["spmatch_seq"]
    
    # 收益明细
    csv_income = os.path.join(output_dir, f"{safe_name}_比赛{seq}_收益明细.csv")
    with open(csv_income, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "日期", "初始资产(万)", "昨日资产(万)", "当日资产(万)",
            "初始资产(元)", "昨日资产(元)", "当日资产(元)",
            "存取金额", "仓位(%)", "昨日收益(%)", "当日收益(%)", "总收益(%)",
            "排名", "持股数", "持股代码"
        ])
        for r in d["income"]:
            holdstocks = r.get("holdstocks") or ""
            if holdstocks:
                codes = [stock_code_to_display(c) for c in holdstocks.split(",")]
                holdstocks = ",".join(codes)
            writer.writerow([
                r.get("endDateNum"), r.get("firstMoneyStr"), r.get("preMoneyStr"),
                r.get("nowMoneyStr"), r.get("firstMoney"), r.get("preMoney"),
                r.get("nowMoney"), r.get("inoutMoneyStr", "0"), r.get("position"),
                r.get("preRateD"), r.get("todayRateD"), r.get("totalRateD"),
                r.get("sortNum"), r.get("holdStockNum"), holdstocks
            ])
    
    # 持仓明细
    csv_trades = os.path.join(output_dir, f"{safe_name}_比赛{seq}_持仓明细.csv")
    with open(csv_trades, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "日期", "股票代码", "股票名称", "当日收益(%)", "金额(元)", "数量(股)"
        ])
        for date_str in sorted(d["trades"].keys()):
            for t in d["trades"][date_str]:
                code = stock_code_to_display(t.get("fullCode", ""))
                rate = t.get("todayRate", "")
                rate_pct = f"{float(rate)/100:.2f}" if rate and str(rate).strip() else ""
                writer.writerow([
                    date_str, code, t.get("stockName", ""),
                    rate_pct, t.get("money", ""), t.get("num", "")
                ])
    
    return csv_income, csv_trades

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("=" * 60, flush=True)
    print(f"📥 批量下载淘股吧交割单", flush=True)
    print(f"   任务数: {len(TASKS)}", flush=True)
    print("=" * 60, flush=True)
    
    all_data = []
    for seq, uid in TASKS:
        data = download_user(seq, uid)
        if data:
            all_data.append(data)
            csv_i, csv_t = save_user_csv(data, OUTPUT_DIR)
            print(f"  💾 已保存CSV", flush=True)
        time.sleep(0.5)
    
    # JSON 原始数据
    json_path = os.path.join(OUTPUT_DIR, "tgb_all_raw.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "downloadTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "users": [{
                "spmatch_seq": d["spmatch_seq"],
                "user_id": d["user_id"],
                "user_name": d["user_name"],
                "income": d["income"],
                "trades": d["trades"],
            } for d in all_data]
        }, f, ensure_ascii=False, indent=2)
    
    # 汇总
    print(f"\n{'='*60}", flush=True)
    print("✅ 全部完成!", flush=True)
    print(f"{'比赛':>6} {'用户名':>12} {'总收益':>10} {'排名':>6} {'交易天数':>8}", flush=True)
    print("-" * 50, flush=True)
    for d in all_data:
        total_rate = d["income"][0]["totalRateD"] if d["income"] else "N/A"
        rank = d["income"][0].get("sortNum", "") if d["income"] else ""
        print(f'{d["spmatch_seq"]:>6} {d["user_name"]:>12} {str(total_rate)+"%":>10} {str(rank):>6} {len(d["trades"]):>8}', flush=True)
    print(f"\n📁 输出目录: {OUTPUT_DIR}", flush=True)
    print(f"📁 文件列表:", flush=True)
    for fname in sorted(os.listdir(OUTPUT_DIR)):
        fpath = os.path.join(OUTPUT_DIR, fname)
        fsize = os.path.getsize(fpath)
        print(f"   {fname} ({fsize//1024}KB)", flush=True)
    print("=" * 60, flush=True)

if __name__ == "__main__":
    main()
