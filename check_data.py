# -*- coding: utf-8 -*-
"""
檢查各個外部資料來源現在抓不抓得到（只讀取、不修改任何檔案）。
用法：python check_data.py
Codespaces 與 Streamlit Cloud 都在海外機房，結果可以拿來推測雲端上的狀況。
"""
import sys
import time

print("Python", sys.version.split()[0])
results = []


def report(name, ok, detail=""):
    results.append((name, ok))
    print(("✅ " if ok else "❌ ") + name + (f"　{detail}" if detail else ""))


try:
    import yfinance as yf
    print("yfinance", yf.__version__)
except Exception as e:
    print("❌ 沒有安裝 yfinance：", e)
    sys.exit(1)

print("\n--- Yahoo Finance（個股、指數）---")
for sym in ("2330.TW", "0050.TW", "^TWII", "^GSPC", "^SOX"):
    try:
        h = yf.Ticker(sym).history(period="5d")
        report(f"history {sym}", h is not None and len(h) > 0, f"{0 if h is None else len(h)} 列")
    except Exception as e:
        report(f"history {sym}", False, f"{type(e).__name__}: {str(e)[:100]}")
    time.sleep(0.3)

print("\n--- Yahoo 批次下載（熱力圖用的方式）---")
try:
    tk = ["2330.TW", "2317.TW", "2454.TW", "2412.TW", "2881.TW", "2603.TW"]
    raw = yf.download(tk, period="5d", group_by="ticker", progress=False, threads=True, auto_adjust=False)
    got = 0 if raw is None or raw.empty else len(set(raw.columns.get_level_values(0))) if hasattr(raw.columns, "levels") else 0
    report("yf.download 6 檔批次", got >= 4, f"取得 {got}/6 檔")
except Exception as e:
    report("yf.download 6 檔批次", False, f"{type(e).__name__}: {str(e)[:100]}")

print("\n--- 證交所／櫃買／集保／期交所／新聞 ---")
try:
    import requests
except Exception as e:
    print("❌ 沒有安裝 requests：", e)
    sys.exit(1)

H = {"User-Agent": "Mozilla/5.0"}
tests = [
    ("證交所 公司基本資料（股票名單）", "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"),
    ("櫃買 公司基本資料", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"),
    ("證交所 每日成交量（熱力圖流動性排序）", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"),
    ("證交所 三大法人買賣超", "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={d}&selectType=ALLBUT0999"),
    ("集保 股權分散表", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"),
    ("期交所 三大法人期貨", "https://www.taifex.com.tw/cht/3/futContractsDate"),
    ("新聞 自由時報財經 RSS", "https://news.ltn.com.tw/rss/business.xml"),
    ("新聞 中央社財經 RSS", "https://www.cna.com.tw/rss/finance.xml"),
]
import pandas as pd
d = (pd.Timestamp.now() - pd.Timedelta(days=1))
while d.weekday() >= 5:
    d -= pd.Timedelta(days=1)
ds = d.strftime("%Y%m%d")
for name, url in tests:
    url = url.replace("{d}", ds)
    try:
        r = requests.get(url, headers=H, timeout=15)
        note = f"HTTP {r.status_code}，{len(r.content) // 1024} KB"
        ok = r.status_code == 200 and len(r.content) > 500
        if ok and "json" in url.lower() and "openapi" not in url:
            try:
                js = r.json()
                stat = js.get("stat") if isinstance(js, dict) else None
                note += f"，stat={stat}"
                ok = stat in (None, "OK")
            except Exception:
                ok = False
                note += "，不是 JSON（可能被擋或網站改版）"
        report(name, ok, note)
    except Exception as e:
        report(name, False, f"{type(e).__name__}: {str(e)[:100]}")

print("\n" + "=" * 50)
bad = [n for n, ok in results if not ok]
print(f"通過 {len(results) - len(bad)}/{len(results)} 項")
if bad:
    print("失敗的項目：")
    for n in bad:
        print("  -", n)
    print("\n把整段輸出貼給我。若 Yahoo 的 history 失敗而證交所正常，多半是 Yahoo 擋了雲端 IP（Rate limit）；")
    print("若證交所失敗，常見原因是證交所限制海外 IP。兩者的處理方式不同。")
