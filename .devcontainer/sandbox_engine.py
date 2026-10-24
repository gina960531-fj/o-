# -*- coding: utf-8 -*-
"""
模擬自動交易引擎（多策略沙盒）。全部是模擬：不連券商、不碰真錢。
介面對應 app.py 的「🤖 模擬自動交易」頁；狀態存在 ~/.quant_radar_data/sandbox/。

成本假設：買賣手續費各 0.1425%、賣出證交稅 0.3%。
簡化：不處理台股最小跳動單位、漲跌停、滑價與成交量限制；成交價就是「觸發當下抓到的價格」。
"""
import json
import os

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.expanduser("~"), ".quant_radar_data", "sandbox")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
LOG_FILE = os.path.join(DATA_DIR, "log.csv")
REPORT_DIR = os.path.join(DATA_DIR, "reports")
LOG_COLUMNS = ["時間", "策略", "動作", "代號", "名稱", "價格", "股數", "損益", "原因", "來源"]

FEE = 0.001425
TAX = 0.003


def _ensure():
    os.makedirs(REPORT_DIR, exist_ok=True)


# ------------------------------------------------------------------ 預設策略
def _params(entry, rr, risk, maxp, pct, mode="即時進場", win=0, be=0.0, tech=None):
    return {"entry_threshold": entry, "min_rr": rr, "risk_pct": risk, "max_positions": maxp, "max_pos_pct": float(pct),
            "buy_mode": mode, "min_win_rate": win, "breakeven_pct": float(be), "tech_filter": list(tech or [])}


BUILTIN = {
    "builtin_balanced": ("🛡️ 均衡穩健", "分數達標、風報比合理、站上月線才進場；獲利 6% 後把停損上移到成本。",
                         _params(40, 1.5, 1.5, 5, 20, be=6, tech=["站上月線"])),
    "builtin_momentum": ("🚀 動能順勢", "只追技術分數很強的標的，單筆風險較大、持股檔數較多。",
                         _params(60, 1.5, 2.0, 6, 20, be=8, tech=["站上月線"])),
    "builtin_pullback": ("🎯 拉回承接", "不追高：先掛單，等價格跌回參考買價附近才建倉，要求風報比至少 2。",
                         _params(20, 2.0, 1.5, 5, 20, mode="拉回觸價", tech=["站上月線"])),
    "builtin_quality": ("🏆 嚴選高勝率", "只買歷史同分數區間隔日上漲機率 ≥ 55% 的標的，檔數少、單筆風險小。",
                        _params(40, 2.0, 1.0, 4, 25, win=55, be=5)),
}


def new_account(name, desc, params, capital, builtin=False):
    return {"name": name, "desc": desc, "params": dict(params), "initial_capital": float(capital), "cash": float(capital),
            "builtin": bool(builtin), "active": True, "positions": {}, "orders": {}, "trades": [], "equity_hist": []}


def ensure_builtin(state, capital):
    """補上缺少的系統預設策略；有新增就回傳 True。"""
    added = False
    for sid, (name, desc, params) in BUILTIN.items():
        if sid not in state["strategies"]:
            state["strategies"][sid] = new_account(name, desc, params, capital, builtin=True)
            added = True
    return added


# ------------------------------------------------------------------ 儲存
def load_state():
    _ensure()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("strategies"), dict):
                return data
        except Exception:
            pass
    return {"strategies": {}}


def save_state(state):
    _ensure()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def append_log(rows):
    if not rows:
        return
    _ensure()
    new = pd.DataFrame(rows).reindex(columns=LOG_COLUMNS)
    if os.path.exists(LOG_FILE):
        try:
            old = pd.read_csv(LOG_FILE, dtype={"代號": str})
            new = pd.concat([old, new], ignore_index=True)
        except Exception:
            pass
    new.to_csv(LOG_FILE, index=False, encoding="utf-8-sig")


def load_log():
    if os.path.exists(LOG_FILE):
        try:
            return pd.read_csv(LOG_FILE, dtype={"代號": str}).reindex(columns=LOG_COLUMNS)
        except Exception:
            pass
    return pd.DataFrame(columns=LOG_COLUMNS)


def reset_all():
    for p in (STATE_FILE, LOG_FILE):
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(REPORT_DIR):
        for f in os.listdir(REPORT_DIR):
            os.remove(os.path.join(REPORT_DIR, f))


def watched_tickers(state):
    out = set()
    for a in state["strategies"].values():
        if a.get("active", True):
            out |= set(a["positions"]) | set(a["orders"])
    return out


# ------------------------------------------------------------------ 交易動作
def _stamp(now):
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _row(now, a, action, tk, name, price, shares, pnl, reason, source):
    return {"時間": _stamp(now), "策略": a["name"], "動作": action, "代號": tk, "名稱": name, "價格": round(float(price), 2),
            "股數": int(shares), "損益": None if pnl is None else round(float(pnl), 0), "原因": reason, "來源": source}


def _round_shares(raw):
    raw = int(raw)
    return raw // 1000 * 1000 if raw >= 1000 else raw


def _buy(a, tk, name, price, shares, stop, t1, t2, now, log, reason, source):
    cost = shares * price * (1 + FEE)
    if shares <= 0 or cost > a["cash"]:
        return False
    a["cash"] -= cost
    a["positions"][tk] = {"name": name, "shares": int(shares), "cost": float(price), "stop": float(stop), "t1": float(t1), "t2": float(t2),
                          "entry_time": _stamp(now), "half_sold": False}
    log.append(_row(now, a, "買進", tk, name, price, shares, None, reason, source))
    return True


def _sell(a, tk, price, shares, now, log, reason, source):
    pos = a["positions"][tk]
    shares = min(int(shares), pos["shares"])
    proceeds = shares * price * (1 - FEE - TAX)
    basis = shares * pos["cost"] * (1 + FEE)
    pnl = proceeds - basis
    a["cash"] += proceeds
    pos["shares"] -= shares
    a["trades"].append({"代號": tk, "名稱": pos["name"], "股數": shares, "買價": pos["cost"], "賣價": float(price), "損益": float(pnl),
                        "時間": _stamp(now), "原因": reason})
    log.append(_row(now, a, "賣出", tk, pos["name"], price, shares, pnl, reason, source))
    if pos["shares"] <= 0:
        del a["positions"][tk]


def process_exits(a, prices, scores, now, log, source):
    """持股出場檢查：停損、獲利保本、第一停利（賣一半）、第二停利、技術轉弱。"""
    p = a["params"]
    for tk in list(a["positions"]):
        price = prices.get(tk)
        if price is None or not np.isfinite(price):
            continue
        pos = a["positions"][tk]
        be = p.get("breakeven_pct") or 0
        if be and price >= pos["cost"] * (1 + be / 100.0):
            pos["stop"] = max(pos["stop"], pos["cost"])
        if price <= pos["stop"]:
            _sell(a, tk, price, pos["shares"], now, log, f"跌破停損 {pos['stop']:.2f}", source)
        elif price >= pos["t2"]:
            _sell(a, tk, price, pos["shares"], now, log, f"達第二停利 {pos['t2']:.2f}", source)
        elif price >= pos["t1"] and not pos.get("half_sold") and pos["shares"] >= 2:
            _sell(a, tk, price, pos["shares"] // 2, now, log, f"達第一停利 {pos['t1']:.2f}（先賣一半）", source)
            if tk in a["positions"]:
                a["positions"][tk]["half_sold"] = True
                a["positions"][tk]["stop"] = max(a["positions"][tk]["stop"], pos["cost"])
        else:
            sc = (scores or {}).get(tk)
            if sc is not None and sc <= p.get("exit_score", 0):
                _sell(a, tk, price, pos["shares"], now, log, f"技術轉弱（分數 {sc}）", source)


def process_orders(a, prices, now, log, source):
    """拉回觸價單：價格跌到觸發價以下才以當時價格成交。"""
    for tk in list(a["orders"]):
        o = a["orders"][tk]
        price = prices.get(tk)
        if price is None or not np.isfinite(price) or price > o["trigger"]:
            continue
        if price <= o["stop"]:
            del a["orders"][tk]                        # 已經跌破停損，這張單作廢
            continue
        if _buy(a, tk, o["name"], price, o["shares"], o["stop"], o["t1"], o["t2"], now, log, f"觸及掛單價 {o['trigger']:.2f}", source):
            del a["orders"][tk]


def equity_of(a, prices):
    mv = 0.0
    for tk, pos in a["positions"].items():
        px = prices.get(tk)
        px = pos["cost"] if (px is None or not np.isfinite(px)) else px
        mv += pos["shares"] * px * (1 - FEE - TAX)
    return a["cash"] + mv


def place_entries(a, cands, prices, now, log, source):
    """依策略條件對候選股建倉（即時進場）或掛單（拉回觸價）。"""
    p = a["params"]
    equity = equity_of(a, prices)
    for c in sorted(cands, key=lambda x: -x["composite"]):
        if len(a["positions"]) + len(a["orders"]) >= p["max_positions"]:
            break
        tk = c["ticker"]
        if tk in a["positions"] or tk in a["orders"]:
            continue
        if c["composite"] < p["entry_threshold"]:
            continue
        if c.get("rr") is None or c["rr"] < p["min_rr"]:
            continue
        if p.get("min_win_rate"):
            wr, n = c.get("wr"), c.get("n")
            if wr is None or n is None or n < 10 or wr < p["min_win_rate"]:
                continue
        price = prices.get(tk, c["price"])
        buy_ref, stop = float(c["buy_price"]), float(c["stop"])
        entry_px = price if p["buy_mode"] == "即時進場" else buy_ref
        if entry_px <= stop:
            continue
        risk_amt = a["initial_capital"] * p["risk_pct"] / 100.0
        shares = risk_amt / (entry_px - stop)
        cap_amt = min(p["max_pos_pct"] / 100.0 * equity, a["cash"] / (1 + FEE))
        shares = _round_shares(min(shares, cap_amt / entry_px))
        if shares <= 0:
            continue
        reason = f"綜合分數 {c['composite']}，風報比 1:{c['rr']:.1f}"
        if p["buy_mode"] == "即時進場" or price <= buy_ref:
            _buy(a, tk, c["name"], price, shares, stop, c["target1"], c["target2"], now, log, reason, source)
        else:
            a["orders"][tk] = {"name": c["name"], "trigger": buy_ref, "stop": stop, "t1": float(c["target1"]), "t2": float(c["target2"]),
                               "shares": int(shares), "created": _stamp(now)}
            log.append(_row(now, a, "掛單", tk, c["name"], buy_ref, shares, None, f"等跌到 {buy_ref:.2f} 才買；" + reason, source))


def record_equity(a, prices, date_str):
    eq = round(equity_of(a, prices), 0)
    if a["equity_hist"] and a["equity_hist"][-1]["date"] == date_str:
        a["equity_hist"][-1]["equity"] = eq
    else:
        a["equity_hist"].append({"date": date_str, "equity": eq})


def tick(state, prices, now, source="盤中監控"):
    """盤中監控一次：所有啟用策略先處理出場、再處理掛單；回傳這次觸發的動作。"""
    log = []
    for a in state["strategies"].values():
        if not a.get("active", True):
            continue
        process_exits(a, prices, {}, now, log, source)
        process_orders(a, prices, now, log, source)
        record_equity(a, prices, now.strftime("%Y-%m-%d"))
    return log


# ------------------------------------------------------------------ 績效與報告
def metrics(a, prices):
    unreal = 0.0
    for tk, pos in a["positions"].items():
        px = prices.get(tk)
        px = pos["cost"] if (px is None or not np.isfinite(px)) else px
        unreal += pos["shares"] * px * (1 - FEE - TAX) - pos["shares"] * pos["cost"] * (1 + FEE)
    realized = sum(t["損益"] for t in a["trades"])
    eq = equity_of(a, prices)
    closed = a["trades"]
    win = (sum(1 for t in closed if t["損益"] > 0) / len(closed) * 100) if closed else None
    hist = [h["equity"] for h in a["equity_hist"]] + [eq]
    peak, mdd = -np.inf, 0.0
    for v in hist:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100) if peak > 0 else mdd
    return {"equity": eq, "ret": (eq / a["initial_capital"] - 1) * 100, "realized": realized, "unrealized": unreal,
            "n_pos": len(a["positions"]), "n_orders": len(a["orders"]), "trades": len(closed), "win": win, "mdd": mdd}


def _report_path(date_iso):
    return os.path.join(REPORT_DIR, f"sandbox_{date_iso.replace('-', '')}.md")


def build_report(state, log_df, date_iso, prices):
    lines = [f"# 模擬自動交易日報　{date_iso}", "",
             "> 全部是模擬交易，不連券商、不碰真錢。損益已扣除手續費與證交稅的估計值。", ""]
    lines += ["## 一、各策略績效", "", "| 策略 | 權益 | 累積報酬 | 已實現 | 未實現 | 持股 | 掛單 | 已平倉 | 勝率 | 最大回撤 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a in state["strategies"].values():
        if not a.get("active", True):
            continue
        m = metrics(a, prices)
        lines.append(f"| {a['name']} | {m['equity']:,.0f} | {m['ret']:+.2f}% | {m['realized']:+,.0f} | {m['unrealized']:+,.0f} | "
                     f"{m['n_pos']} | {m['n_orders']} | {m['trades']} | {'—' if m['win'] is None else format(m['win'], '.0f') + '%'} | {m['mdd']:.1f}% |")
    lines += ["", f"## 二、{date_iso} 的交易明細", ""]
    day = log_df[log_df["時間"].astype(str).str.startswith(date_iso)] if (log_df is not None and not log_df.empty) else pd.DataFrame()
    if day.empty:
        lines.append("這一天沒有任何自動交易。")
    else:
        lines += ["| 時間 | 策略 | 動作 | 代號 | 名稱 | 價格 | 股數 | 損益 | 原因 |", "|---|---|---|---|---|---:|---:|---:|---|"]
        for _, r in day.iterrows():
            pnl = "" if pd.isna(r["損益"]) else f"{r['損益']:+,.0f}"
            lines.append(f"| {str(r['時間'])[11:]} | {r['策略']} | {r['動作']} | {r['代號']} | {r['名稱']} | {r['價格']} | {r['股數']} | {pnl} | {r['原因']} |")
        sells = day[day["動作"] == "賣出"]
        if not sells.empty:
            lines += ["", f"當日已實現損益合計：**{sells['損益'].fillna(0).sum():+,.0f}**（{len(sells)} 筆賣出）"]
    lines += ["", "## 三、目前持股與掛單", ""]
    any_pos = False
    for a in state["strategies"].values():
        if not a.get("active", True):
            continue
        for tk, pos in a["positions"].items():
            any_pos = True
            px = prices.get(tk, pos["cost"])
            lines.append(f"- **{a['name']}**　{pos['name']}（{tk}）{pos['shares']:,} 股，成本 {pos['cost']:.2f}，現價 {px:.2f}"
                         f"（{(px / pos['cost'] - 1) * 100:+.1f}%），停損 {pos['stop']:.2f}，第一停利 {pos['t1']:.2f}")
        for tk, o in a["orders"].items():
            any_pos = True
            lines.append(f"- **{a['name']}**　掛單 {o['name']}（{tk}）：跌到 {o['trigger']:.2f} 才買 {o['shares']:,} 股，停損 {o['stop']:.2f}")
    if not any_pos:
        lines.append("目前沒有持股或掛單。")
    lines += ["", "---", "報價可能延遲 15～20 分鐘，成交價是觸發當下抓到的價格；跳空時實際成交可能比停損價更差。僅供策略研究，不構成投資建議。"]
    return "\n".join(lines)


def save_report(md, date_iso):
    _ensure()
    with open(_report_path(date_iso), "w", encoding="utf-8") as f:
        f.write(md)


def list_reports():
    _ensure()
    return sorted((f for f in os.listdir(REPORT_DIR) if f.startswith("sandbox_") and f.endswith(".md")), reverse=True)


def read_report(name):
    with open(os.path.join(REPORT_DIR, name), "r", encoding="utf-8") as f:
        return f.read()
