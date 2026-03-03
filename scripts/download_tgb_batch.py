#!/usr/bin/env python3
"""
批量下载淘股吧实盘比赛交割单数据
比赛: spmatchSeq=802
日期: 20260303
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
    {"id": "1120338", "name": "user_1120338"},
    {"id": "7386521", "name": "user_7386521"},
    {"id": "5452924", "name": "user_5452924"},
    {"id": "11310249", "name": "只核大学生"},
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
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception as e:
        print(f"  ❌ 请求失败: {url}")
        print(f"     错误: {e}")
        return None

def fetch_all_income(user_id):
    """获取所有页面的日度收益数据"""
    all_records = []
    page = 1
    total_pages = None
    
    while True:
        url = f"{BASE_URL}/spmatch/gains/listIncome?spmatchSeq={SPMATCH_SEQ}&endDateNum=&lookUserID={user_id}&pageNo={page}"
        data = fetch_json(url)
        
        if not data or not data.get("status"):
            break
        
        dto = data.get("dto", {})
        records = dto.get("list", [])
        
        if total_pages is None:
            total_pages = dto.get("pageNum", 1)
        
        if not records:
            break
        
        all_records.extend(records)
        
        if page >= total_pages:
            break
        
        page += 1
        time.sleep(0.3)
    
    return all_records

def fetch_trades_for_date(user_id, date_num):
    """获取指定日期的持仓/交易明细"""
    url = f"{BASE_URL}/spmatch/gains/listChiCangMatch?spmatchSeq={SPMATCH_SEQ}&lookeuserID={user_id}&type=ALL&date={date_num}&pageNo=1"
    data = fetch_json(url)
    
    if data and data.get("status"):
        dto = data.get("dto", {})
        return dto.get("list", [])
    return []

def download_user(user_id, user_label):
    """下载单个用户的全部数据"""
    print(f"\n{'='*60}")
    print(f"📥 下载用户: {user_label} (ID: {user_id})")
    print(f"{'='*60}")
    
    # 获取收益概况
    print("  📊 获取日度收益概况...")
    income_records = fetch_all_income(user_id)
    
    if not income_records:
        print(f"  ❌ 未获取到数据")
        return None
    
    # 获取用户名
    actual_name = income_records[0].get("userName", user_label) if income_records else user_label
    print(f"  ✅ 用户名: {actual_name}, 共 {len(income_records)} 条收益记录")
    
    # 获取每日持仓明细
    print("  📊 获取每日持仓明细...")
    all_trades = {}
    dates = list(dict.fromkeys([str(r["endDateNum"]) for r in income_records]))
    
    for i, date_str in enumerate(dates):
        trades = fetch_trades_for_date(user_id, date_str)
        if trades:
            all_trades[date_str] = trades
        
        if (i + 1) % 10 == 0:
            time.sleep(1)
        else:
            time.sleep(0.2)
        
        # 进度
        if (i + 1) % 20 == 0:
            print(f"    进度: {i+1}/{len(dates)}")
    
    print(f"  ✅ 持仓明细: {len(all_trades)} 天, 共 {sum(len(v) for v in all_trades.values())} 条记录")
    
    return {
        "user_id": user_id,
        "user_name": actual_name,
        "user_label": user_label,
        "income": income_records,
        "trades": all_trades,
    }

def save_to_excel_csv(all_data):
    """保存所有用户数据到CSV文件(Excel兼容)"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # === 汇总收益明细 ===
    csv_income = os.path.join(OUTPUT_DIR, f"tgb_{SPMATCH_SEQ}_收益汇总.csv")
    print(f"\n💾 保存收益汇总: {csv_income}")
    
    with open(csv_income, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "用户ID", "用户名", "日期", "初始资产(万)", "昨日资产(万)", "当日资产(万)",
            "初始资产(元)", "昨日资产(元)", "当日资产(元)",
            "存取金额", "仓位(%)", "昨日收益(%)", "当日收益(%)", "总收益(%)",
            "排名", "持股数", "持股代码"
        ])
        for user_data in all_data:
            for r in user_data["income"]:
                holdstocks = r.get("holdstocks") or ""
                if holdstocks:
                    codes = [stock_code_to_display(c) for c in holdstocks.split(",")]
                    holdstocks = ",".join(codes)
                
                writer.writerow([
                    user_data["user_id"],
                    user_data["user_name"],
                    r.get("endDateNum"),
                    r.get("firstMoneyStr"),
                    r.get("preMoneyStr"),
                    r.get("nowMoneyStr"),
                    r.get("firstMoney"),
                    r.get("preMoney"),
                    r.get("nowMoney"),
                    r.get("inoutMoneyStr", "0"),
                    r.get("position"),
                    r.get("preRateD"),
                    r.get("todayRateD"),
                    r.get("totalRateD"),
                    r.get("sortNum"),
                    r.get("holdStockNum"),
                    holdstocks
                ])
    
    # === 汇总持仓明细 ===
    csv_trades = os.path.join(OUTPUT_DIR, f"tgb_{SPMATCH_SEQ}_持仓汇总.csv")
    print(f"💾 保存持仓汇总: {csv_trades}")
    
    with open(csv_trades, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "用户ID", "用户名", "日期", "股票代码", "股票名称", "当日收益(%)", "金额", "数量"
        ])
        for user_data in all_data:
            for date_str in sorted(user_data["trades"].keys(), reverse=True):
                for t in user_data["trades"][date_str]:
                    code = stock_code_to_display(t.get("fullCode", ""))
                    writer.writerow([
                        user_data["user_id"],
                        user_data["user_name"],
                        date_str,
                        code,
                        t.get("stockName", ""),
                        t.get("todayRate", ""),
                        t.get("money", "--"),
                        t.get("num", "--")
                    ])
    
    # === 每个用户单独的文件 ===
    for user_data in all_data:
        safe_name = user_data["user_name"].replace("/", "_").replace(" ", "_")
        
        # 单用户收益
        csv_path = os.path.join(OUTPUT_DIR, f"tgb_{safe_name}_收益明细.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "日期", "初始资产(万)", "昨日资产(万)", "当日资产(万)",
                "仓位(%)", "昨日收益(%)", "当日收益(%)", "总收益(%)",
                "排名", "持股数", "持股代码"
            ])
            for r in user_data["income"]:
                holdstocks = r.get("holdstocks") or ""
                if holdstocks:
                    codes = [stock_code_to_display(c) for c in holdstocks.split(",")]
                    holdstocks = ",".join(codes)
                writer.writerow([
                    r.get("endDateNum"),
                    r.get("firstMoneyStr"),
                    r.get("preMoneyStr"),
                    r.get("nowMoneyStr"),
                    r.get("position"),
                    r.get("preRateD"),
                    r.get("todayRateD"),
                    r.get("totalRateD"),
                    r.get("sortNum"),
                    r.get("holdStockNum"),
                    holdstocks
                ])
        
        # 单用户持仓
        csv_path = os.path.join(OUTPUT_DIR, f"tgb_{safe_name}_持仓明细.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "日期", "股票代码", "股票名称", "当日收益(%)", "金额", "数量"
            ])
            for date_str in sorted(user_data["trades"].keys(), reverse=True):
                for t in user_data["trades"][date_str]:
                    code = stock_code_to_display(t.get("fullCode", ""))
                    writer.writerow([
                        date_str,
                        code,
                        t.get("stockName", ""),
                        t.get("todayRate", ""),
                        t.get("money", "--"),
                        t.get("num", "--")
                    ])
        
        print(f"  ✅ {user_data['user_name']}: 收益+持仓已保存")
    
    # === JSON 原始数据 ===
    json_path = os.path.join(OUTPUT_DIR, f"tgb_{SPMATCH_SEQ}_raw.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "spmatchSeq": SPMATCH_SEQ,
            "downloadTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "users": [{
                "user_id": d["user_id"],
                "user_name": d["user_name"],
                "income": d["income"],
                "trades": d["trades"],
            } for d in all_data]
        }, f, ensure_ascii=False, indent=2)
    print(f"💾 原始JSON: {json_path}")

def main():
    print("=" * 60)
    print(f"📥 批量下载淘股吧实盘比赛交割单")
    print(f"   比赛序号: {SPMATCH_SEQ}")
    print(f"   用户数: {len(USERS)}")
    print("=" * 60)
    
    all_data = []
    for user in USERS:
        data = download_user(user["id"], user["name"])
        if data:
            all_data.append(data)
        time.sleep(1)  # 用户间隔
    
    if all_data:
        save_to_excel_csv(all_data)
        
        print(f"\n{'='*60}")
        print("✅ 全部完成!")
        for d in all_data:
            total_rate = d["income"][0]["totalRateD"] if d["income"] else "N/A"
            print(f"   {d['user_name']} (ID:{d['user_id']}): {len(d['income'])}天记录, 总收益{total_rate}%")
        print(f"\n   📁 输出目录: {OUTPUT_DIR}")
        print("=" * 60)
    else:
        print("❌ 未获取到任何数据，请检查cookies是否过期")

if __name__ == "__main__":
    main()
