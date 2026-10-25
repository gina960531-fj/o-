# -*- coding: utf-8 -*-
"""
到價通知的資料與判斷邏輯（不依賴 Streamlit）。
注意：網頁程式沒有背景執行，只有「頁面開著」時才會檢查；要在頁面關閉時也收到通知，需要另外設定排程。
"""
import json
import os
import time
import uuid

try:
    import requests
except ImportError:
    requests = None

OPS = {">=": "漲到", "<=": "跌到"}


def _path(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "price_alerts.json")


def load_alerts(data_dir):
    p = _path(data_dir)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_alerts(data_dir, alerts):
    tmp = _path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(data_dir))


def add_alert(data_dir, ticker, code, name, op, price, note=""):
    if op not in OPS:
        raise ValueError("條件必須是 >= 或 <=")
    if not (price and price > 0):
        raise ValueError("目標價必須大於 0")
    alerts = load_alerts(data_dir)
    alerts.append(dict(id=uuid.uuid4().hex[:8], ticker=ticker, code=str(code), name=name, op=op, price=float(price), note=note,
                       created=time.strftime("%Y-%m-%d %H:%M"), active=True, triggered_at=None, triggered_price=None))
    save_alerts(data_dir, alerts)
    return alerts


def remove_alerts(data_dir, ids):
    alerts = [a for a in load_alerts(data_dir) if a["id"] not in set(ids)]
    save_alerts(data_dir, alerts)
    return alerts


def rearm(data_dir, ids):
    alerts = load_alerts(data_dir)
    for a in alerts:
        if a["id"] in set(ids):
            a.update(active=True, triggered_at=None, triggered_price=None)
    save_alerts(data_dir, alerts)
    return alerts


def evaluate(alerts, prices):
    """回傳 [(alert, price)]：啟用中、且現價已達條件的通知。缺價格的不判斷。"""
    hit = []
    for a in alerts:
        if not a.get("active", True):
            continue
        px = prices.get(a["ticker"])
        if px is None or px != px:                 # None 或 NaN
            continue
        if (a["op"] == ">=" and px >= a["price"]) or (a["op"] == "<=" and px <= a["price"]):
            hit.append((a, float(px)))
    return hit


def mark_triggered(data_dir, hits, now_str=None):
    now_str = now_str or time.strftime("%Y-%m-%d %H:%M")
    ids = {a["id"]: px for a, px in hits}
    alerts = load_alerts(data_dir)
    for a in alerts:
        if a["id"] in ids:
            a.update(active=False, triggered_at=now_str, triggered_price=ids[a["id"]])
    save_alerts(data_dir, alerts)
    return alerts


def format_message(alert, price):
    msg = f"🔔 {alert['name']}（{alert['code']}）{OPS[alert['op']]} {alert['price']:g}：現價 {price:.2f}"
    return msg + (f"\n備註：{alert['note']}" if alert.get("note") else "")


def send_telegram(token, chat_id, text, timeout=10):
    """回傳 (成功與否, 說明)。沒設定 token／chat_id 時不會丟例外。"""
    if not token or not chat_id:
        return False, "沒有設定 Telegram"
    if requests is None:
        return False, "沒有安裝 requests"
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": text}, timeout=timeout)
        return (r.status_code == 200 and bool(r.json().get("ok"))), f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"
