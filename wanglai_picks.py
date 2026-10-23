# -*- coding: utf-8 -*-
"""
大戶選股：把「集保週報（wanglai_data.build_week 的輸出）」轉成每檔股票的籌碼分數與理由。
純 pandas，不依賴 Streamlit。權重是經驗設定，沒有統計驗證；請搭配「🏆 成績單」分頁看這套籌碼訊號到底有沒有用。
"""
import numpy as np
import pandas as pd

EMPTY_COLS = ["chip_score", "reasons", "risks"]


def _row_score(r):
    score, why, risk = 0.0, [], []

    big_d = r["big_d"]
    score += min(big_d, 6.0) * 5.0
    why.append(f"大戶持股週增 {big_d:+.2f} 個百分點")

    mega_d = r["mega_d"]
    if pd.notna(mega_d):
        if mega_d >= 1:
            score += 8
            why.append(f"千張大戶同步增加 {mega_d:+.2f}pp")
        elif mega_d <= -1:
            score -= 8
            risk.append(f"千張大戶反而減少 {mega_d:+.2f}pp（增加的可能只是 400～999 張層）")

    holders_d = r["holders_d"]
    if pd.notna(holders_d):
        if holders_d < 0:
            score += 6
            why.append(f"股東人數減少 {abs(holders_d):,.0f} 人（籌碼趨向集中）")
        elif holders_d > 0:
            score -= 6
            risk.append(f"股東人數增加 {holders_d:,.0f} 人（持股在分散）")

    streak = int(r["streak_up"]) if pd.notna(r["streak_up"]) else 0
    if streak >= 2:
        score += min(streak, 4) * 3
        why.append(f"大戶連續 {streak} 週增持")

    tags = r["tag_list"] if isinstance(r["tag_list"], (list, tuple)) else []
    if "中大戶升格" in tags:
        score += 5
        why.append("中大戶升格（400～999 張層往千張以上移動）")
    if "回頭車" in tags:
        score += 4
        why.append("回頭車（上週減持、本週回補）")
    if "千張降級" in tags:
        score -= 5
        risk.append("千張降級（千張大戶減少、往下一層移）")

    retail_d = r["retail_d"]
    if pd.notna(retail_d):
        if retail_d <= -1:
            score += 4
            why.append(f"散戶持股比例下降 {retail_d:+.2f}pp")
        elif retail_d >= 1:
            score -= 4
            risk.append(f"散戶持股比例上升 {retail_d:+.2f}pp")

    margin = r["margin_chg"]
    if pd.notna(margin):
        if margin > 10:
            score -= 6
            risk.append(f"融資餘額增加 {margin:.1f}%（散戶可能在追價，籌碼較不乾淨）")
        elif margin < -5:
            score += 3
            why.append(f"融資餘額減少 {abs(margin):.1f}%（融資退場，籌碼較乾淨）")

    ratio = r["ratio"]
    if pd.notna(ratio) and ratio >= 10:
        risk.append(f"券資比 {ratio:.0f}%（空單比重高，波動可能放大）")

    return score, why, risk


def chip_pick_score(wk, min_big_d=1.0, min_big_pct=0.0):
    """
    wk：wanglai_data.build_week() 的輸出（index=代號）。
    只保留大戶週增 >= min_big_d 個百分點、且大戶持股比例 >= min_big_pct 的股票，
    回傳 DataFrame（index=代號，依 chip_score 由高到低）：chip_score, reasons, risks。
    """
    if wk is None or len(wk) == 0:
        return pd.DataFrame(columns=EMPTY_COLS)
    d = wk[(wk["big_d"] >= min_big_d) & (wk["big"] >= min_big_pct)]
    if d.empty:
        return pd.DataFrame(columns=EMPTY_COLS)
    out = {}
    for code, r in d.iterrows():
        s, why, risk = _row_score(r)
        out[code] = {"chip_score": round(s, 1), "reasons": why, "risks": risk}
    res = pd.DataFrame.from_dict(out, orient="index")
    return res.sort_values("chip_score", ascending=False)
