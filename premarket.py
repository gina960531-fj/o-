# -*- coding: utf-8 -*-
"""
盤前必讀的規則邏輯（純 Python，不依賴 Streamlit）。
quotes：{代號: {"value", "chg_pct", "d5"(可選), "bp"(可選，殖利率變動 bp)}}，抓不到的代號請不要放進去或設為 None。
這是簡單的規則加總，不是預測模型。
"""

SYMBOLS = [
    ("^GSPC", "S&P 500"), ("^IXIC", "那斯達克"), ("^DJI", "道瓊"), ("^SOX", "費城半導體"),
    ("TSM", "台積電 ADR"), ("NQ=F", "那指期貨"), ("^VIX", "VIX 恐慌指數"), ("TWD=X", "美元／台幣"),
    ("^TNX", "美國10年期殖利率"), ("CL=F", "WTI 原油"), ("GC=F", "黃金"),
]
NAMES = dict(SYMBOLS)

MACRO_NEWS_KEYWORDS = ["Fed", "聯準會", "升息", "降息", "利率", "CPI", "通膨", "非農", "就業", "關稅", "美股", "費半", "輝達",
                       "台積電", "地緣", "油價", "匯率", "新台幣", "外資", "央行", "美元", "財報", "出口管制", "停火", "戰"]


def _get(quotes, sym):
    q = quotes.get(sym)
    return q if q and q.get("chg_pct") is not None else None


def build_summary(quotes):
    """
    回傳 dict(score, label, level, bullets, risks, used, missing)。
    level：success / warning / error / info，給畫面挑顏色。
    """
    score, bullets, used, missing = 0.0, [], 0, []

    def add(points, text):
        nonlocal score
        score += points
        bullets.append((points, text))

    def need(sym):
        q = _get(quotes, sym)
        if q is None:
            missing.append(NAMES.get(sym, sym))
        return q

    for sym, label in (("^SOX", "費半"), ("^IXIC", "那斯達克"), ("^GSPC", "S&P 500")):
        q = need(sym)
        if q is None:
            continue
        used += 1
        c = q["chg_pct"]
        if sym == "^SOX":
            if c <= -3:
                add(-2, f"{label}重挫 {c:+.2f}%，台股半導體族群容易跟著承壓")
            elif c <= -1:
                add(-1, f"{label}收跌 {c:+.2f}%")
            elif c >= 3:
                add(2, f"{label}大漲 {c:+.2f}%，對台股半導體偏正面")
            elif c >= 1:
                add(1, f"{label}收漲 {c:+.2f}%")
        else:
            if c <= -1.5:
                add(-1, f"{label}收跌 {c:+.2f}%")
            elif c >= 1.0:
                add(1, f"{label}收漲 {c:+.2f}%")

    q = need("TSM")
    if q:
        used += 1
        c = q["chg_pct"]
        if c >= 1:
            add(1, f"台積電 ADR 收漲 {c:+.2f}%")
        elif c <= -1:
            add(-1, f"台積電 ADR 收跌 {c:+.2f}%")

    q = need("NQ=F")
    if q:
        used += 1
        c = q["chg_pct"]
        if c >= 0.5:
            add(1, f"那指期貨 {c:+.2f}%（反映美股收盤後的走勢）")
        elif c <= -0.5:
            add(-1, f"那指期貨 {c:+.2f}%（反映美股收盤後的走勢）")

    q = need("^VIX")
    if q:
        used += 1
        v = q["value"]
        if v >= 25:
            add(-2, f"VIX {v:.1f}，市場恐慌情緒偏高")
        elif v >= 20:
            add(-1, f"VIX {v:.1f}，偏警戒")
        elif v < 15:
            add(1, f"VIX {v:.1f}，市場情緒平穩")

    q = need("TWD=X")
    if q:
        used += 1
        c = q["chg_pct"]
        if c >= 0.5:
            add(-1, f"台幣貶值 {c:.2f}%，外資可能偏向匯出")
        elif c <= -0.3:
            add(1, f"台幣升值 {abs(c):.2f}%")

    q = need("^TNX")
    if q and q.get("bp") is not None:
        used += 1
        bp = q["bp"]
        if bp >= 10:
            add(-1, f"美10年債殖利率單日上升 {bp:.0f} bp，利率壓力升高")
        elif bp <= -10:
            add(1, f"美10年債殖利率單日下降 {abs(bp):.0f} bp")

    if used == 0:
        label, level = "資料不足", "info"
    elif score >= 3:
        label, level = "🟢 偏多", "success"
    elif score <= -3:
        label, level = "🔴 偏空", "error"
    else:
        label, level = "🟡 中性／分歧", "warning"
    return dict(score=score, label=label, level=level, bullets=bullets, risks=risk_flags(quotes), used=used, missing=missing)


def risk_flags(quotes):
    """今天開盤前要特別留意的風險（規則式，觸發才列出）。"""
    out = []
    q = _get(quotes, "^VIX")
    if q and q["value"] >= 25:
        out.append(f"VIX 偏高（{q['value']:.1f}），盤中波動可能放大，注意停損與部位大小。")
    q = _get(quotes, "^SOX")
    if q and q["chg_pct"] <= -3:
        out.append(f"費半單日重挫 {q['chg_pct']:+.2f}%，台股電子權值股開盤容易跳空走弱。")
    q = _get(quotes, "TWD=X")
    if q and q["chg_pct"] >= 0.8:
        out.append(f"台幣單日急貶 {q['chg_pct']:.2f}%，留意外資賣壓。")
    q = _get(quotes, "^TNX")
    if q and q.get("bp") is not None and q["bp"] >= 10:
        out.append(f"美10年債殖利率單日上升 {q['bp']:.0f} bp，高估值成長股較敏感。")
    for sym in ("^GSPC", "^IXIC"):
        q = _get(quotes, sym)
        if q and q["chg_pct"] <= -2:
            out.append(f"{NAMES[sym]}單日下跌 {q['chg_pct']:+.2f}%，隔夜風險偏好轉弱。")
    q = _get(quotes, "CL=F")
    if q and abs(q["chg_pct"]) >= 4:
        out.append(f"原油單日波動 {q['chg_pct']:+.2f}%，航運、塑化與通膨預期可能受影響。")
    q = _get(quotes, "NQ=F")
    sp = _get(quotes, "^IXIC")
    if q and sp and q["chg_pct"] <= -1 and sp["chg_pct"] > -0.5:
        out.append("那指期貨在美股收盤後明顯走弱，開盤前請再確認最新消息。")
    return out


def pick_macro_news(items, limit=8):
    """從新聞標題挑出跟開盤前有關的（關鍵字比對，不是語意分析）。"""
    out = []
    for it in items or []:
        t = it.get("title", "")
        hits = [k for k in MACRO_NEWS_KEYWORDS if k.lower() in t.lower()]
        if hits:
            out.append(dict(it, hits=hits[:3]))
    return out[:limit]
