# -*- coding: utf-8 -*-
"""
證交所／櫃買中心「每日收盤行情」開放資料（全部上市、上櫃個股一次抓完）。
用途：熱力圖的報價與成交值、全市場流動性排行。不依賴 Streamlit，也不依賴 Yahoo。
單獨執行 `python official_quotes.py` 可以自我檢查：會印出抓到幾檔、成交值前十名與漲跌。
"""
import re
import sys

try:
    import requests
except ImportError:                      # 沒裝 requests 時 fetch 會回傳空結果
    requests = None

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
           "Referer": "https://www.twse.com.tw/", "Accept-Language": "zh-TW,zh;q=0.9"}
CODE_RE = re.compile(r"^[0-9]{4,6}[A-Z]?$")


def _num(x):
    try:
        s = str(x).replace(",", "").replace("+", "").strip()
        return float(s) if s not in ("", "--", "---", "----", "X") else None
    except Exception:
        return None


def _asof(s):
    """民國日期 '1151022' → '10/22'。"""
    s = str(s).strip()
    return f"{s[-4:-2]}/{s[-2:]}" if len(s) >= 6 and s.isdigit() else ""


def _row(code, name, close, change, value, volume, date, suffix):
    if close is None or change is None or value is None:
        return None
    prev = close - change
    if close <= 0 or prev <= 0 or value <= 0 or not CODE_RE.match(code):
        return None
    return dict(ticker=code + suffix, code=code, name=name, close=close, prev=prev, chg=(close / prev - 1) * 100,
                value=value, volume=volume or 0.0, asof=_asof(date))


def parse_twse(data):
    out = {}
    for rec in data if isinstance(data, list) else []:
        if not isinstance(rec, dict):
            continue
        code = str(rec.get("Code", "")).strip()
        close, change = _num(rec.get("ClosingPrice")), _num(rec.get("Change"))
        value, volume = _num(rec.get("TradeValue")), _num(rec.get("TradeVolume"))
        r = _row(code, str(rec.get("Name", "")).strip(), close, change, value, volume, rec.get("Date", ""), ".TW")
        if r:
            out[r["ticker"]] = r
    return out


def parse_tpex(data):
    out = {}
    for rec in data if isinstance(data, list) else []:
        if not isinstance(rec, dict):
            continue
        code = str(rec.get("SecuritiesCompanyCode", "")).strip()
        close, change = _num(rec.get("Close")), _num(rec.get("Change"))
        volume = _num(rec.get("TradingShares"))
        value = _num(rec.get("TransactionAmount"))
        if value is None and close is not None and volume is not None:
            value = close * volume                    # 沒有成交金額欄位時，用收盤價×股數近似
        r = _row(code, str(rec.get("CompanyName", "")).strip(), close, change, value, volume, rec.get("Date", ""), ".TWO")
        if r:
            out[r["ticker"]] = r
    return out


def fetch_source(name, timeout=(10, 40), retries=1):
    """抓單一來源（'twse' 上市／'tpex' 上櫃）。失敗會丟例外，方便呼叫端用快取機制『失敗不快取』。"""
    if requests is None:
        raise RuntimeError("沒有安裝 requests")
    url, parser = {"twse": (TWSE_URL, parse_twse), "tpex": (TPEX_URL, parse_tpex)}[name]
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            rows = parser(r.json())
            if rows:
                return rows
            last = RuntimeError("解析不到任何資料")
        except Exception as e:
            last = e
    raise last


def fetch_official(timeout=(10, 40), retries=1):
    """回傳 (rows: {ticker: row}, messages: list[str])。任何一邊抓失敗都只會少一邊，不會丟例外。"""
    rows, msgs = {}, []
    for name, label in (("twse", "上市"), ("tpex", "上櫃")):
        try:
            part = fetch_source(name, timeout, retries)
            msgs.append(f"{label}：解析出 {len(part)} 檔")
            rows.update(part)
        except Exception as e:
            msgs.append(f"{label}：失敗（{type(e).__name__}: {str(e)[:80]}）")
    return rows, msgs


def liquidity(rows):
    """{股票代號（不含 .TW/.TWO）: 成交值}，給流動性排行用。"""
    return {r["code"]: r["value"] for r in rows.values()}


if __name__ == "__main__":
    rows, msgs = fetch_official()
    for m in msgs:
        print(m)
    print(f"合計 {len(rows)} 檔")
    top = sorted(rows.values(), key=lambda r: -r["value"])[:10]
    print("成交值前 10 名：")
    for r in top:
        print(f"  {r['code']:>6} {r['name']:<8} 收 {r['close']:>8.2f}  漲跌 {r['chg']:+6.2f}%  成交值 {r['value'] / 1e8:8.1f} 億  ({r['asof']})")
    sys.exit(0 if len(rows) > 300 else 1)
