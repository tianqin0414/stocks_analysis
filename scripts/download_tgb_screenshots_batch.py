#!/usr/bin/env python3
"""
批量下载淘股吧5位高手的交割单截图
然后用 macOS Vision OCR 提取持仓价格数据
"""
import json
import time
import urllib.request
import os
import sys
from datetime import datetime

# === 配置 ===
OUTPUT_BASE = "/Users/tq/PycharmProjects/stocks_analysis/output/2_淘股吧高手/原始数据/截图"

TASKS = [
    ("802", "1120338",  "天牌"),
    ("802", "7386521",  "忘忧阁主"),
    ("802", "5452924",  "低调内敛的朋"),
    ("802", "9157318",  "独行侠令狐冲"),
    ("858", "10580905", "龙年大叔"),
]

COOKIES = (
    "tgbuser=12810600; "
    "tgbpwd=8daecd30e53af3098373334ba74c00c865a577cb782a854686a2e0d46979905dfpfqtq2qbqmq9v0; "
    "loginStatus=phone"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Cookie": COOKIES,
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None

def get_trade_dates(spmatch_seq, user_id):
    """获取所有交易日期"""
    dates = []
    page = 1
    while True:
        url = f"https://www.tgb.cn/spmatch/gains/listIncome?spmatchSeq={spmatch_seq}&endDateNum=&lookUserID={user_id}&pageNo={page}"
        data = fetch_json(url)
        if not data or not data.get("status"): break
        dto = data.get("dto", {})
        records = dto.get("list", [])
        if not records: break
        for r in records:
            dates.append(str(r["endDateNum"]))
        total_pages = dto.get("pageNum", 1)
        if page >= total_pages: break
        page += 1
        time.sleep(0.3)
    return sorted(set(dates))

def download_screenshots(spmatch_seq, user_id, name, output_dir):
    """下载某位高手的所有截图"""
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取交易日期
    print(f"  获取交易日期...")
    dates = get_trade_dates(spmatch_seq, user_id)
    print(f"  共 {len(dates)} 个交易日")
    
    downloaded = 0
    skipped = 0
    failed = 0
    no_image = 0
    urls_map = {}
    
    for i, date_str in enumerate(dates):
        url = f"https://www.tgb.cn/spmatch/gains/listUrl?spmatchSeq={spmatch_seq}&lookUserID={user_id}&dateNum={date_str}"
        HEADERS["Referer"] = f"https://www.tgb.cn/spmatch/gains/readInfo?lookeUserID={user_id}&spmatchSeq={spmatch_seq}"
        
        result = fetch_json(url)
        if not result or not result.get("status"):
            failed += 1
            continue
        
        dto_list = result.get("dto", [])
        if not dto_list:
            no_image += 1
            continue
        
        for dto in dto_list:
            img_urls = dto.get("imgUrls", [])
            if not img_urls:
                no_image += 1
                continue
            
            urls_map[date_str] = img_urls
            
            for j, img_url in enumerate(img_urls):
                suffix = f"_{j+1}" if len(img_urls) > 1 else ""
                filename = f"{date_str}{suffix}.png"
                filepath = os.path.join(output_dir, filename)
                
                if os.path.exists(filepath):
                    skipped += 1
                    continue
                
                try:
                    original_url = img_url.replace("_sp760w.png", ".jpg").replace("_sp760w", "")
                    req = urllib.request.Request(original_url, headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://www.tgb.cn/"
                    })
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with open(filepath, "wb") as f:
                            f.write(resp.read())
                    downloaded += 1
                except Exception as e:
                    failed += 1
                
                time.sleep(0.2)
        
        if (i+1) % 50 == 0:
            print(f"    进度: {i+1}/{len(dates)}, 下载{downloaded}, 跳过{skipped}")
            time.sleep(1)
        else:
            time.sleep(0.3)
    
    # 保存URL映射
    urls_file = os.path.join(output_dir, f"截图URL.json")
    with open(urls_file, "w", encoding="utf-8") as f:
        json.dump(urls_map, f, ensure_ascii=False, indent=2)
    
    print(f"  ✅ 完成: 下载{downloaded}, 已有{skipped}, 无图{no_image}, 失败{failed}")
    return downloaded + skipped

def main():
    print("=" * 60)
    print("📸 批量下载淘股吧高手交割单截图")
    print("=" * 60)
    
    for spmatch_seq, user_id, name in TASKS:
        print(f"\n{'='*40}")
        print(f"📥 {name} (比赛{spmatch_seq}, ID={user_id})")
        print(f"{'='*40}")
        
        output_dir = os.path.join(OUTPUT_BASE, f"{name}_交割单截图")
        total = download_screenshots(spmatch_seq, user_id, name, output_dir)
        print(f"  📁 保存到: {output_dir}")
    
    print(f"\n{'='*60}")
    print("🎉 全部下载完成!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
