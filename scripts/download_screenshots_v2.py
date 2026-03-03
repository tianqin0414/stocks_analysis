#!/usr/bin/env python3
"""批量下载淘股吧5位高手交割单截图 (修正版: 直接用原始URL)"""
import urllib.request, json, os, time, sys

OUTPUT_BASE = "/Users/tq/PycharmProjects/stocks_analysis/output/2_淘股吧高手/原始数据/截图"

TASKS = [
    ("802", "1120338",  "天牌"),
    ("802", "7386521",  "忘忧阁主"),
    ("802", "5452924",  "低调内敛的朋"),
    ("802", "9157318",  "独行侠令狐冲"),
    ("858", "10580905", "龙年大叔"),
]

COOKIES = "tgbuser=12810600; tgbpwd=8daecd30e53af3098373334ba74c00c865a577cb782a854686a2e0d46979905dfpfqtq2qbqmq9v0; loginStatus=phone"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Cookie": COOKIES,
}

def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except:
        return None

def get_dates(seq, uid):
    dates = []
    page = 1
    while True:
        url = f"https://www.tgb.cn/spmatch/gains/listIncome?spmatchSeq={seq}&endDateNum=&lookUserID={uid}&pageNo={page}"
        data = fetch_json(url)
        if not data or not data.get("status"): break
        dto = data.get("dto",{})
        for r in dto.get("list",[]):
            dates.append(str(r["endDateNum"]))
        if page >= dto.get("pageNum",1): break
        page += 1
        time.sleep(0.3)
    return sorted(set(dates))

log_file = os.path.join(OUTPUT_BASE, "download_log.txt")
def log(msg):
    print(msg, flush=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

log(f"{'='*50}")
log(f"开始下载 {time.strftime('%Y-%m-%d %H:%M:%S')}")

total_all = 0
for seq, uid, name in TASKS:
    out_dir = os.path.join(OUTPUT_BASE, f"{name}_交割单截图")
    os.makedirs(out_dir, exist_ok=True)
    
    log(f"\n📥 {name} (比赛{seq})")
    dates = get_dates(seq, uid)
    log(f"  {len(dates)}个交易日")
    
    dl = 0; skip = 0; fail = 0; noimg = 0
    urls_map = {}
    
    for i, dt in enumerate(dates):
        HEADERS["Referer"] = f"https://www.tgb.cn/spmatch/gains/readInfo?lookeUserID={uid}&spmatchSeq={seq}"
        url = f"https://www.tgb.cn/spmatch/gains/listUrl?spmatchSeq={seq}&lookUserID={uid}&dateNum={dt}"
        result = fetch_json(url)
        
        if not result or not result.get("status"):
            fail += 1; continue
        
        dto_list = result.get("dto") or []
        if not dto_list:
            noimg += 1; continue
        
        for dto in dto_list:
            img_urls = dto.get("imgUrls") or []
            if not img_urls:
                noimg += 1; continue
            urls_map[dt] = img_urls
            
            for j, img_url in enumerate(img_urls):
                suffix = f"_{j+1}" if len(img_urls)>1 else ""
                filepath = os.path.join(out_dir, f"{dt}{suffix}.png")
                if os.path.exists(filepath):
                    skip += 1; continue
                try:
                    req = urllib.request.Request(img_url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.tgb.cn/"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with open(filepath,"wb") as f:
                            f.write(resp.read())
                    dl += 1
                except:
                    fail += 1
                time.sleep(0.15)
        
        if (i+1) % 50 == 0:
            log(f"  [{i+1}/{len(dates)}] 下载{dl} 跳过{skip} 无图{noimg} 失败{fail}")
            time.sleep(0.5)
        else:
            time.sleep(0.2)
    
    with open(os.path.join(out_dir,"截图URL.json"),"w",encoding="utf-8") as f:
        json.dump(urls_map, f, ensure_ascii=False, indent=2)
    
    log(f"  ✅ {name}: 下载{dl} 跳过{skip} 无图{noimg} 失败{fail}")
    total_all += dl + skip

log(f"\n🎉 全部完成! 总截图: {total_all}张")
