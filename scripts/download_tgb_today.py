#!/usr/bin/env python3
"""
下载淘股吧指定日期的交割单数据
比赛: spmatchSeq=802, 日期: 20260303
"""
import json
import time
import urllib.request
import csv
import os
from datetime import datetime

# === 配置 ===
SPMATCH_SEQ = "802"
TARGET_DATE = "20260303"
OUTPUT_DIR = "/Users/tq/PycharmProjects/stocks_analysis/output/tgb_802"

USERS = [
    {"id": "1120338"},
    {"id": "7386521"},
    {"id": "5452924"},
    {"id": "11310249"},  # 只核大学生
    {"id": "9157318"},
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
        print(f"  ❌ 请求失败: {e}")
        return None

def fetch_income_for_date(user_id, date_num):
    """获取指定日期的收益概况（从第1页开始找）"""
    url = f"{BASE_URL}/spmatch/gains/listIncome?spmatchSeq={SPMATCH_SEQ}&endDateNum={date_num}&lookUserID={user_id}&pageNo=1"
    data = fetch_json(url)
    if data and data.get("status"):
        records = data.get("dto", {}).get("list", [])
        # 找到目标日期的记录
        for r in records:
            if str(r.get("endDateNum")) == str(date_num):
                return r
        # 如果没精确匹配，返回第一条（最近日期）
        if records:
            return records[0]
    return None

def fetch_trades_for_date(user_id, date_num):
    """获取指定日期的持仓/交易明细"""
    url = f"{BASE_URL}/spmatch/gains/listChiCangMatch?spmatchSeq={SPMATCH_SEQ}&lookeuserID={user_id}&type=ALL&date={date_num}&pageNo=1"
    data = fetch_json(url)
    if data and data.get("status"):
        return data.get("dto", {}).get("list", [])
    return []

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("=" * 60)
    print(f"📥 下载淘股吧交割单 - 比赛{SPMATCH_SEQ} 日期{TARGET_DATE}")
    print(f"   用户数: {len(USERS)}")
    print("=" * 60)
    
    all_data = []
    
    for user in USERS:
        uid = user["id"]
        print(f"\n--- 用户 {uid} ---")
        
        # 获取收益概况
        income = fetch_income_for_date(uid, TARGET_DATE)
        if income:
            name = income.get("userName", uid)
            print(f"  用户名: {name}")
            print(f"  日期: {income.get('endDateNum')}")
            print(f"  当日收益: {income.get('todayRateD')}%")
            print(f"  总收益: {income.get('totalRateD')}%")
            print(f"  排名: {income.get('sortNum')}")
            print(f"  当日资产: {income.get('nowMoneyStr')}万")
        else:
            name = uid
            print(f"  ⚠️ 未找到收益数据")
        
        time.sleep(0.3)
        
        # 获取持仓明细
        trades = fetch_trades_for_date(uid, TARGET_DATE)
        print(f"  持仓: {len(trades)} 只股票")
        for t in trades:
            code = stock_code_to_display(t.get("fullCode", ""))
            rate = t.get("todayRate", "")
            rate_str = f"{float(rate)/100:.2f}%" if rate and rate != "" else "N/A"
            print(f"    {code} {t.get('stockName','')} 收益:{rate_str} 金额:{t.get('money','--')} 数量:{t.get('num','--')}")
        
        all_data.append({
            "user_id": uid,
            "user_name": name,
            "income": income,
            "trades": trades,
        })
        
        time.sleep(0.3)
    
    # === 保存 Excel CSV ===
    csv_path = os.path.join(OUTPUT_DIR, f"tgb_{SPMATCH_SEQ}_{TARGET_DATE}_交割单.csv")
    print(f"\n💾 保存: {csv_path}")
    
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "用户ID", "用户名", "日期", "股票代码", "股票名称", 
            "当日收益(%)", "金额(元)", "数量(股)",
            "当日总收益(%)", "总收益(%)", "当日资产(万)", "排名", "仓位(%)"
        ])
        for d in all_data:
            inc = d["income"] or {}
            if d["trades"]:
                for t in d["trades"]:
                    code = stock_code_to_display(t.get("fullCode", ""))
                    rate = t.get("todayRate", "")
                    rate_pct = f"{float(rate)/100:.2f}" if rate and str(rate).strip() else ""
                    writer.writerow([
                        d["user_id"],
                        d["user_name"],
                        inc.get("endDateNum", TARGET_DATE),
                        code,
                        t.get("stockName", ""),
                        rate_pct,
                        t.get("money", ""),
                        t.get("num", ""),
                        inc.get("todayRateD", ""),
                        inc.get("totalRateD", ""),
                        inc.get("nowMoneyStr", ""),
                        inc.get("sortNum", ""),
                        inc.get("position", ""),
                    ])
            else:
                # 无持仓记录，只写收益行
                writer.writerow([
                    d["user_id"],
                    d["user_name"],
                    inc.get("endDateNum", TARGET_DATE),
                    "", "", "", "", "",
                    inc.get("todayRateD", ""),
                    inc.get("totalRateD", ""),
                    inc.get("nowMoneyStr", ""),
                    inc.get("sortNum", ""),
                    inc.get("position", ""),
                ])
    
    # === JSON ===
    json_path = os.path.join(OUTPUT_DIR, f"tgb_{SPMATCH_SEQ}_{TARGET_DATE}_raw.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "spmatchSeq": SPMATCH_SEQ,
            "date": TARGET_DATE,
            "downloadTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "users": all_data,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"💾 原始JSON: {json_path}")
    
    # === 汇总 ===
    print(f"\n{'='*60}")
    print("✅ 完成! 汇总:")
    print(f"{'用户名':>12} {'当日收益':>10} {'总收益':>10} {'排名':>6} {'持股数':>6}")
    print("-" * 50)
    for d in all_data:
        inc = d["income"] or {}
        print(f"{d['user_name']:>12} {str(inc.get('todayRateD',''))+'%':>10} {str(inc.get('totalRateD',''))+'%':>10} {str(inc.get('sortNum','')):>6} {len(d['trades']):>6}")
    print("=" * 60)

if __name__ == "__main__":
    main()
