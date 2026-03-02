#!/usr/bin/env python3
"""
从淘股吧(tgb.cn)下载"只核大学生"的实盘比赛交割单数据
2025梦想杯 - 百万组第1名
"""
import json
import time
import urllib.request
import urllib.parse
import csv
import os
from datetime import datetime

# === 配置 ===
USER_ID = "11310249"
SPMATCH_SEQ = "813"
OUTPUT_DIR = "/Users/tq/PycharmProjects/stocks_analysis/output"
JSON_OUTPUT = os.path.join(OUTPUT_DIR, "tgb_zhihedaxuesheng_data.json")
CSV_INCOME = os.path.join(OUTPUT_DIR, "tgb_zhihedaxuesheng_收益明细.csv")
CSV_TRADES = os.path.join(OUTPUT_DIR, "tgb_zhihedaxuesheng_持仓明细.csv")

# 从浏览器获取的 Cookies
COOKIES = (
    "tgbuser=12810600; "
    "tgbpwd=8daecd30e53af3098373334ba74c00c865a577cb782a854686a2e0d46979905dfpfqtq2qbqmq9v0; "
    "loginStatus=phone; "
    "JSESSIONID=NTY4ZmU0ZTEtZDNhZC00YWFjLWEzYmQtZmZhZTVhODQ4ZDNk; "
    "acw_tc=7929ee2c17723648343801290ee26e79d8a7e27c90e4189f49d27b800ea160"
)

BASE_URL = "https://www.tgb.cn"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"https://www.tgb.cn/spmatch/gains/readInfo?lookeUserID={USER_ID}&spmatchSeq={SPMATCH_SEQ}",
    "Cookie": COOKIES,
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# 股票代码映射（去掉前缀）
def stock_code_to_display(full_code):
    """将 sh600343 -> 600343, sz002361 -> 002361, bj832885 -> 832885"""
    if full_code and len(full_code) > 2:
        return full_code[2:]
    return full_code

def fetch_json(url):
    """发起 GET 请求并返回 JSON 数据"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except Exception as e:
        print(f"  ❌ 请求失败: {url}")
        print(f"     错误: {e}")
        return None


def fetch_all_income():
    """获取所有页面的日度收益数据"""
    all_records = []
    page = 1
    total_pages = None
    
    while True:
        url = f"{BASE_URL}/spmatch/gains/listIncome?spmatchSeq={SPMATCH_SEQ}&endDateNum=&lookUserID={USER_ID}&pageNo={page}"
        print(f"  正在获取收益概况第 {page} 页...")
        data = fetch_json(url)
        
        if not data or not data.get("status"):
            print(f"  ⚠️ 第 {page} 页数据获取失败")
            break
        
        dto = data.get("dto", {})
        records = dto.get("list", [])
        
        if total_pages is None:
            total_pages = dto.get("pageNum", 1)
            print(f"  📊 共 {total_pages} 页数据")
        
        if not records:
            break
        
        all_records.extend(records)
        print(f"    ✅ 获取到 {len(records)} 条记录 (累计 {len(all_records)})")
        
        if page >= total_pages:
            break
        
        page += 1
        time.sleep(0.5)  # 避免请求过快
    
    return all_records


def fetch_trades_for_date(date_num):
    """获取指定日期的持仓/交易明细"""
    url = f"{BASE_URL}/spmatch/gains/listChiCangMatch?spmatchSeq={SPMATCH_SEQ}&lookeuserID={USER_ID}&type=ALL&date={date_num}&pageNo=1"
    data = fetch_json(url)
    
    if data and data.get("status"):
        dto = data.get("dto", {})
        return dto.get("list", [])
    return []


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("=" * 60)
    print("📥 开始下载淘股吧实盘比赛数据")
    print("   选手: 只核大学生")
    print("   比赛: 2025梦想杯 (spmatchSeq=813)")
    print("=" * 60)
    
    # ========== 1. 获取日度收益概况 ==========
    print("\n📊 第一步: 获取日度收益概况...")
    income_records = fetch_all_income()
    print(f"\n✅ 共获取 {len(income_records)} 条日度收益记录")
    
    if not income_records:
        print("❌ 未获取到任何数据，请检查 cookies 是否过期")
        return
    
    # ========== 2. 获取每日持仓明细 ==========
    print("\n📊 第二步: 获取每日持仓明细...")
    all_trades = {}
    dates = [str(r["endDateNum"]) for r in income_records]
    # 去重
    unique_dates = list(dict.fromkeys(dates))
    
    for i, date_str in enumerate(unique_dates):
        print(f"  [{i+1}/{len(unique_dates)}] 获取 {date_str} 持仓明细...")
        trades = fetch_trades_for_date(date_str)
        if trades:
            all_trades[date_str] = trades
            print(f"    ✅ {len(trades)} 只股票")
        else:
            print(f"    ⚠️ 无数据")
        
        if (i + 1) % 10 == 0:
            time.sleep(1)  # 每10个请求休息一下
        else:
            time.sleep(0.3)
    
    # ========== 3. 保存原始 JSON ==========
    print(f"\n💾 保存原始 JSON 数据到: {JSON_OUTPUT}")
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "user": "只核大学生",
            "userID": USER_ID,
            "spmatchSeq": SPMATCH_SEQ,
            "downloadTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "income": income_records,
            "trades": all_trades
        }, f, ensure_ascii=False, indent=2)
    
    # ========== 4. 保存收益明细 CSV ==========
    print(f"\n💾 保存收益明细 CSV: {CSV_INCOME}")
    with open(CSV_INCOME, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "日期", "初始资产(万)", "昨日资产(万)", "当日资产(万)", 
            "初始资产(元)", "昨日资产(元)", "当日资产(元)",
            "存取金额", "仓位(%)", "昨日收益(%)", "当日收益(%)", "总收益(%)", 
            "排名", "持股数", "持股代码"
        ])
        for r in income_records:
            holdstocks = r.get("holdstocks") or ""
            if holdstocks:
                # 转换股票代码格式
                codes = [stock_code_to_display(c) for c in holdstocks.split(",")]
                holdstocks = ",".join(codes)
            
            writer.writerow([
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
    
    # ========== 5. 保存持仓明细 CSV ==========
    print(f"💾 保存持仓明细 CSV: {CSV_TRADES}")
    with open(CSV_TRADES, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "日期", "股票代码", "股票名称", "当日收益(%)", "金额", "数量"
        ])
        for date_str in sorted(all_trades.keys(), reverse=True):
            trades_list = all_trades[date_str]
            for t in trades_list:
                code = stock_code_to_display(t.get("fullCode", ""))
                writer.writerow([
                    date_str,
                    code,
                    t.get("stockName", ""),
                    t.get("todayRate", ""),
                    t.get("money", "--"),
                    t.get("num", "--")
                ])
    
    # ========== 6. 统计输出 ==========
    print("\n" + "=" * 60)
    print("✅ 数据下载完成!")
    print(f"   📊 日度收益记录: {len(income_records)} 条")
    print(f"   📊 持仓明细交易日: {len(all_trades)} 天")
    total_trade_records = sum(len(v) for v in all_trades.values())
    print(f"   📊 持仓明细总记录: {total_trade_records} 条")
    print(f"\n   📁 JSON: {JSON_OUTPUT}")
    print(f"   📁 收益CSV: {CSV_INCOME}")
    print(f"   📁 持仓CSV: {CSV_TRADES}")
    print("=" * 60)
    
    return income_records, all_trades


if __name__ == "__main__":
    main()
