# -*- coding: utf-8 -*-
"""
投資組合資金平衡與「明日買進推薦」的規則邏輯（純 pandas，不依賴 Streamlit）。
所有門檻都是可調的經驗規則，不是最佳化結果，也不構成投資建議。
"""
import pandas as pd

# 常被視為「防禦型」的產業（營收較穩、景氣敏感度較低）；只是粗略分類
DEFENSIVE_INDUSTRIES = {"金融保險", "通信網路", "食品", "貿易百貨", "油電燃氣", "生技醫療", "水泥"}


def style_of(industry, tech=None):
    """把標的粗分成 防禦型／動能型／分散型(ETF)／其他。動能型＝技術分數 >= 30。"""
    if industry == "ETF":
        return "分散型"
    if industry in DEFENSIVE_INDUSTRIES:
        return "防禦型"
    if tech is not None and tech >= 30:
        return "動能型"
    return "其他"


def snapshot(rows, cash, total_capital, max_industry_pct=40.0, max_single_pct=40.0, target_cash_pct=15.0):
    """
    rows：投資組合頁算好的持股 list[dict]，用到 code, name, industry, market_value, is_short, score。
    只用多方部位計算權重（空方部位另計，不混進產業集中度）。
    回傳 (diag dict, issues list[(level, text)])。
    """
    longs = [r for r in rows if r.get("market_value") is not None and not r.get("is_short")]
    long_mv = sum(r["market_value"] for r in longs)
    base = total_capital if total_capital and total_capital > 0 else long_mv
    ind_mv, style_mv = {}, {}
    for r in longs:
        ind_mv[r["industry"]] = ind_mv.get(r["industry"], 0.0) + r["market_value"]
        s = style_of(r["industry"], r.get("score"))
        style_mv[s] = style_mv.get(s, 0.0) + r["market_value"]
    ind_pct = {k: v / base * 100 for k, v in ind_mv.items()} if base else {}
    style_pct = {k: v / base * 100 for k, v in style_mv.items()} if base else {}
    top_ind = max(ind_pct, key=ind_pct.get) if ind_pct else None
    single = max(longs, key=lambda r: r["market_value"]) if longs else None
    single_pct = single["market_value"] / base * 100 if (single and base) else 0.0
    cash_pct = cash / base * 100 if (base and cash) else 0.0

    issues = []
    for ind, p in sorted(ind_pct.items(), key=lambda kv: -kv[1]):
        if p > max_industry_pct:
            over_amt = (p - max_industry_pct) / 100 * base
            issues.append(("error", f"「{ind}」佔總資金 {p:.0f}%，超過你設的 {max_industry_pct:.0f}% 上限，約多 ${over_amt:,.0f}；推薦清單已排除這個產業，並建議不要再加碼。"))
    if single is not None and single_pct > max_single_pct:
        issues.append(("warning", f"單一持股「{single['name']}」佔 {single_pct:.0f}%，超過 {max_single_pct:.0f}%，個股風險偏集中。"))
    if cash and cash_pct < target_cash_pct:
        issues.append(("warning", f"現金只有 {cash_pct:.0f}%，低於目標水位 {target_cash_pct:.0f}%，系統不會建議新增部位。"))
    if style_pct.get("防禦型", 0) + style_pct.get("分散型", 0) < 15 and longs:
        issues.append(("info", "防禦型／分散型（金融、電信、民生、ETF 等）合計不到 15%，部位偏攻擊，景氣轉弱時可能一起回檔。"))
    if style_pct.get("動能型", 0) < 10 and longs:
        issues.append(("info", "目前技術面強勢（動能型）的持股不到 10%，若想加強進攻性，可看推薦清單中的動能型標的。"))

    diag = dict(base=base, cash_pct=cash_pct, ind_pct=ind_pct, style_pct=style_pct, top_ind=top_ind,
                single_name=single["name"] if single else None, single_pct=single_pct, long_mv=long_mv)
    return diag, issues


def trim_suggestions(rows, total_capital, max_industry_pct):
    """超過產業上限的產業：建議減碼多少金額，並列出該產業中市值最大的持股。"""
    longs = [r for r in rows if r.get("market_value") is not None and not r.get("is_short")]
    base = total_capital if total_capital and total_capital > 0 else sum(r["market_value"] for r in longs)
    out = []
    if not base:
        return out
    by_ind = {}
    for r in longs:
        by_ind.setdefault(r["industry"], []).append(r)
    for ind, rs in by_ind.items():
        mv = sum(r["market_value"] for r in rs)
        if mv / base * 100 > max_industry_pct:
            biggest = max(rs, key=lambda r: r["market_value"])
            out.append(dict(industry=ind, pct=mv / base * 100, trim_amt=mv - max_industry_pct / 100 * base,
                            biggest=f"{biggest['name']}（{biggest['code']}）"))
    return out


def target_cash_pct(base_pct, macro_flags):
    """目標現金水位：基準 + 每個總經風險旗標 5 個百分點（最多加 10）。"""
    return base_pct + min(10, 5 * len(macro_flags or []))


def recommend(rows, candidates, directory, deployable_cash, total_capital, *, max_industry_pct=40.0,
              max_single_pct=15.0, risk_pct=1.0, n=5, style_pref="平衡", min_rr=1.0, lot=1000):
    """
    從每日候選股挑「明日可買進」清單：排除已持有、排除會讓產業超過上限的標的，
    依「候選綜合分數＋分散化加分＋風格偏好加分」排序，
    股數 = 單筆風險金額 ÷（買價−停損），再受「單檔上限」「產業剩餘額度」「可動用現金」三重封頂。
    回傳 (DataFrame, 剩餘現金)。
    """
    held = {str(r["code"]) for r in rows}
    ind_mv = {}
    for r in rows:
        if r.get("market_value") is not None and not r.get("is_short"):
            ind_mv[r["industry"]] = ind_mv.get(r["industry"], 0.0) + r["market_value"]
    base = total_capital if total_capital and total_capital > 0 else 0.0
    if base <= 0 or deployable_cash <= 0:
        return pd.DataFrame(), deployable_cash

    scored = []
    for c in candidates:
        code = str(c["code"])
        if code in held:
            continue
        if min_rr and (c.get("rr") is None or c["rr"] < min_rr):
            continue
        ind = directory.get(code, {}).get("ind", "其他")
        cls = style_of(ind, c.get("tech"))
        cur_w = ind_mv.get(ind, 0.0) / base * 100
        bonus, why = 0.0, []
        if cur_w == 0:
            bonus += 8
            why.append("補上目前沒持有的產業")
        elif cur_w < 15:
            bonus += 4
            why.append("該產業目前佔比偏低")
        if style_pref == "偏防禦" and cls in ("防禦型", "分散型"):
            bonus += 10
            why.append("符合偏防禦的配置方向")
        if style_pref == "偏動能" and cls == "動能型":
            bonus += 10
            why.append("符合偏動能的配置方向")
        scored.append((c["composite"] + bonus, c, ind, cls, why))
    scored.sort(key=lambda x: -x[0])

    recs, cash_left = [], float(deployable_cash)
    for sc, c, ind, cls, why in scored:
        if len(recs) >= n:
            break
        buy, stop = float(c["buy_price"]), float(c["stop"])
        if buy <= 0 or buy <= stop:
            continue
        shares = base * risk_pct / 100.0 / (buy - stop)
        ind_room = max(0.0, max_industry_pct / 100.0 * base - ind_mv.get(ind, 0.0))
        max_amt = min(max_single_pct / 100.0 * base, cash_left, ind_room)
        shares = min(shares, max_amt / buy)
        shares = int(shares // lot * lot) if shares >= lot else int(shares)
        if shares <= 0:
            continue
        amt = shares * buy
        cash_left -= amt
        ind_mv[ind] = ind_mv.get(ind, 0.0) + amt
        recs.append(dict(code=c["code"], name=c["name"], industry=ind, style=cls, composite=c["composite"],
                         buy_price=buy, stop=stop, target1=c.get("target1"), rr=c.get("rr"),
                         shares=shares, amount=amt, risk_amt=shares * (buy - stop),
                         post_ind_pct=ind_mv[ind] / base * 100, why="；".join(why) or "綜合分數靠前"))
    return pd.DataFrame(recs), cash_left
