# -*- coding: utf-8 -*-
"""
ETF 專區的資料層（純 pandas，不依賴 Streamlit）。

重要：ETF 的指數規則與持股會調整（例如指數改版、成分股大幅換血），各來源對檔數與調整月份的說法也不一致，
所以下面的 ETF_CATALOG 只寫「結構性、長期穩定」的策略說明，不放具體持股與權重。
持股與權重請從投信官網下載後匯入，系統會自己存快照、比較前後差異。
"""
import io
import json
import os
import re

import numpy as np
import pandas as pd

ETF_CATALOG = {
    "0050": dict(
        name="元大台灣50", issuer="元大投信", kind="市值型（被動）",
        summary="追蹤臺灣50指數：以上市公司市值最大的一批大型股為成分股，依市值加權。",
        logic="沒有經理人主觀選股，完全依指數規則定期調整；市值越大權重越高，所以大型權值股（尤其半導體龍頭）影響很大。",
        pros=["成分股換手低、規則透明", "代表台股大型股整體表現", "費用率通常較低"],
        risks=["權重集中在少數權值股", "不特別追求配息，殖利率通常低於高股息型"],
        who="想用低成本持有台股大盤核心部位的人。",
        checked="結構性描述；成分股家數與調整頻率請以指數編製規則為準。"),
    "006208": dict(
        name="富邦台50", issuer="富邦投信", kind="市值型（被動）",
        summary="與 0050 同樣追蹤臺灣50指數，只是發行投信不同。",
        logic="選股與加權邏輯與 0050 相同；差異主要在費用率、規模、流動性與配息安排。",
        pros=["與 0050 持股高度相同", "可作為同指數的替代選擇"],
        risks=["同樣集中於大型權值股", "成交量通常低於 0050，掛單要注意價差"],
        who="想持有同一指數、但在費用或價格上有不同偏好的人。",
        checked="請自行核對追蹤指數與費用率。"),
    "0056": dict(
        name="元大高股息", issuer="元大投信", kind="高股息型（被動）",
        summary="追蹤臺灣高股息指數：從大型與中型股的選股池中，挑「預測未來一年現金股利殖利率」較高者。",
        logic="選股池為臺灣50與臺灣中型100成分股；以「預測」殖利率排序入選，不分產業，所以可能納入景氣循環股；每半年定期審核成分股。",
        pros=["配息導向、持股分散在多檔", "規則公開，依預測殖利率機械式調整"],
        risks=["預測殖利率可能與實際配息有落差", "高殖利率股可能是景氣高峰的獲利，不一定能持續", "成分股可能集中在電子與景氣循環產業"],
        who="重視現金流、能接受成分股定期換血的人。",
        checked="已對照公開報導（追蹤指數與選股邏輯）；實際檔數、審核月份各來源說法不一，請以公開說明書為準。"),
    "00878": dict(
        name="國泰永續高股息", issuer="國泰投信", kind="高股息型（被動）",
        summary="追蹤 MSCI 臺灣 ESG 永續高股息精選 30 指數：先看 ESG 條件，再以股息分數排序取前 30 檔。",
        logic="股息分數同時參考近 12 個月與近 3 年的平均殖利率，是「用過去資料加權」而非預測；入選後依規則調整。",
        pros=["兼顧 ESG 篩選與配息", "成分股檔數固定、規則清楚"],
        risks=["目前持股可能偏重電子與半導體權值股，不再只是傳統金融股印象", "ESG 評級與股息排序會讓成分股變動"],
        who="想要高股息、同時重視永續篩選的人。",
        checked="已對照公開報導（追蹤指數與選股邏輯）；持股與產業比重變動快，請看最新持股。"),
    "00919": dict(
        name="群益台灣精選高息", issuer="群益投信", kind="高股息型（被動）",
        summary="高股息策略 ETF，季配息；持股集中度偏高，成分股曾在 2026 年 6 月大幅調整（報導指 18 檔進、18 檔出）。",
        logic="選股因子與指數規則請以公開說明書為準；觀察重點是成分股更換幅度與前十大持股占比。",
        pros=["配息導向", "規則化調整"],
        risks=["持股集中度高時，單一產業或個股的影響放大", "成分股大幅換血時，過去的持股與配息特性可能改變"],
        who="能接受集中持股、且願意定期檢視成分股變化的人。",
        checked="只對照了配息與近期成分股調整的報導；指數名稱與選股因子請自行核對。"),
    "00929": dict(
        name="復華台灣科技優息", issuer="復華投信", kind="高股息型（被動，月配息）",
        summary="追蹤臺灣指數公司特選臺灣上市上櫃科技優息指數，結合科技類股與配息，採月配息。",
        logic="選股池偏科技產業，並以股息相關條件篩選；報導提到指數曾改版（所謂 3.0 版），規則可能已與早期不同。",
        pros=["月配息，現金流較頻繁", "持股偏科技、兼顧成長與配息"],
        risks=["持股集中於科技產業，景氣與半導體循環影響大", "指數改版後成分股與權重可能明顯改變"],
        who="想要每月有現金流、並能接受科技股波動的人。",
        checked="已對照公開報導（追蹤指數、月配息、指數改版）；詳細規則請以公開說明書為準。"),
    "00713": dict(
        name="元大台灣高息低波", issuer="元大投信", kind="高股息型（被動，因子）",
        summary="同時考慮「高股息」與「低波動」兩個因子的指數型 ETF，季配息。",
        logic="先找殖利率較高的股票，再挑波動度較低者；目的是在配息之外降低價格波動。",
        pros=["兼顧配息與低波動", "通常防禦性較高息型更好"],
        risks=["低波動不等於不會跌", "大多頭時，漲幅可能落後市值型"],
        who="想降低波動、同時要配息的人。",
        checked="只依名稱與公開報導的因子概念整理；指數規則與成分股請自行核對。"),
    "00891": dict(
        name="中信關鍵半導體", issuer="中信投信", kind="主題型（半導體）",
        summary="集中投資半導體產業鏈的主題型 ETF。",
        logic="成分股限定在半導體相關公司，並依指數規則加權；詳細選股條件請看公開說明書。",
        pros=["直接參與半導體產業趨勢"],
        risks=["高度集中單一產業，景氣循環與費半連動明顯", "與持有 2330 等個股高度重疊，要留意整體曝險"],
        who="看好半導體產業、並了解主題型波動較大的人。",
        checked="未逐項查證，請自行核對發行商、追蹤指數與規則。"),
    "00892": dict(
        name="富邦台灣半導體", issuer="富邦投信", kind="主題型（半導體）",
        summary="聚焦台灣半導體產業的主題型 ETF。",
        logic="成分股限定在台灣半導體相關公司；詳細選股條件與權重上限請看公開說明書。",
        pros=["直接參與台灣半導體產業趨勢"],
        risks=["高度集中單一產業", "與 0050、個股持股可能大量重疊"],
        who="想以單一 ETF 持有台灣半導體族群的人。",
        checked="未逐項查證，請自行核對發行商、追蹤指數與規則。"),
}

PASSIVE_VS_ACTIVE = (
    "**被動式 ETF**沒有經理人主觀選股：持股由指數規則決定，經理人的工作是「讓 ETF 貼近指數」，所以研究重點是『指數怎麼編』。\n\n"
    "**主動式 ETF**才由經理人決定買什麼、何時調整，研究重點是經理人的風格、換手率與每日公布的持股變化。"
    "本系統的『自訂 ETF』可以加入主動式 ETF，並用持股快照追蹤它的調整。")


# ------------------------------------------------------------------ 儲存
def etf_dir(data_dir):
    d = os.path.join(data_dir, "etf")
    os.makedirs(d, exist_ok=True)
    return d


def _custom_path(data_dir):
    return os.path.join(etf_dir(data_dir), "custom_etfs.json")


def load_custom(data_dir):
    p = _custom_path(data_dir)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_custom(data_dir, code, entry):
    d = load_custom(data_dir)
    d[str(code)] = entry
    with open(_custom_path(data_dir), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def all_etfs(data_dir):
    out = {k: dict(v) for k, v in ETF_CATALOG.items()}
    for k, v in load_custom(data_dir).items():
        base = dict(name=v.get("name", k), issuer=v.get("issuer", ""), kind=v.get("kind", "自訂"),
                    summary=v.get("summary", ""), logic=v.get("logic", ""), pros=[], risks=[], who="",
                    checked="自訂資料，由你自行維護。")
        out[k] = base
    return out


def snapshot_path(data_dir, code, date_iso):
    return os.path.join(etf_dir(data_dir), f"hold_{code}_{date_iso.replace('-', '')}.csv")


def save_snapshot(data_dir, code, date_iso, df):
    df.to_csv(snapshot_path(data_dir, code, date_iso), index=False, encoding="utf-8-sig")


def list_snapshots(data_dir, code):
    pat = re.compile(rf"hold_{re.escape(str(code))}_(\d{{8}})\.csv$")
    out = []
    for f in os.listdir(etf_dir(data_dir)):
        m = pat.match(f)
        if m:
            s = m.group(1)
            out.append(f"{s[:4]}-{s[4:6]}-{s[6:]}")
    return sorted(out)


def load_snapshot(data_dir, code, date_iso):
    df = pd.read_csv(snapshot_path(data_dir, code, date_iso), dtype={"code": str}, encoding="utf-8-sig")
    df["code"] = df["code"].astype(str)
    return df


# ------------------------------------------------------------------ 解析
_CODE_KEYS = ["股票代號", "證券代號", "標的代號", "代號", "代碼", "code", "symbol", "ticker"]
_NAME_KEYS = ["股票名稱", "證券名稱", "標的名稱", "名稱", "name"]
_W_KEYS = ["持股權重", "權重", "比重", "占比", "佔比", "持股比例", "比例", "weight"]
_SH_KEYS = ["股數", "持股數", "shares"]


def _find_col(cols, keys):
    low = {c: str(c).strip().lower() for c in cols}
    for k in keys:                                    # 先找完全相同
        for c, l in low.items():
            if l == k.lower():
                return c
    for k in keys:                                    # 再找包含
        for c, l in low.items():
            if k.lower() in l:
                return c
    return None


def _to_num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("%", "").str.strip(), errors="coerce")


def parse_holdings(text_or_df):
    """
    把貼上的文字（CSV／Tab 分隔皆可）或 DataFrame 轉成標準持股表：code, name, weight(%), shares(可選)。
    回傳 (DataFrame, 提醒文字 list)。找不到代號欄與權重欄就丟 ValueError。
    """
    if isinstance(text_or_df, pd.DataFrame):
        df = text_or_df.copy()
    else:
        txt = str(text_or_df).lstrip("\ufeff").strip()
        if not txt:
            raise ValueError("內容是空的")
        df = pd.read_csv(io.StringIO(txt), sep=None, engine="python", dtype=str)
    if df.empty:
        raise ValueError("沒有任何資料列")
    cc, nc, wc, sc = (_find_col(df.columns, k) for k in (_CODE_KEYS, _NAME_KEYS, _W_KEYS, _SH_KEYS))
    if cc is None or wc is None:
        raise ValueError(f"找不到「代號」或「權重」欄位。目前欄位：{list(df.columns)}")
    out = pd.DataFrame({
        "code": df[cc].astype(str).str.strip().str.upper().str.replace(r"\.(TW|TWO)$", "", regex=True),
        "name": df[nc].astype(str).str.strip() if nc else "",
        "weight": _to_num(df[wc]),
    })
    if sc:
        out["shares"] = _to_num(df[sc])
    out = out[out["code"].str.fullmatch(r"[0-9A-Z]{4,6}") & out["weight"].notna()]
    notes = []
    if out.empty:
        raise ValueError("解析後沒有任何有效的持股列（請確認代號欄是股票代號、權重欄是數字）")
    total = out["weight"].sum()
    if 0.9 <= total <= 1.1:                           # 權重是小數（總和≈1）：換成百分比
        out["weight"] *= 100
        notes.append("權重總和約為 1，已視為小數並換算成百分比。")
        total *= 100
    if not (80 <= total <= 105):
        notes.append(f"權重總和為 {total:.1f}%，不在 80～105% 之間，可能漏列了部分持股（現金、期貨等不計入）或欄位選錯，請自行核對。")
    out = out.groupby("code", as_index=False).agg({**{"name": "first", "weight": "sum"}, **({"shares": "sum"} if "shares" in out else {})})
    return out.sort_values("weight", ascending=False).reset_index(drop=True), notes


def fetch_yf_holdings(code):
    """盡力從 Yahoo 抓前幾大持股；台股 ETF 常常沒有資料，抓不到就回傳 None。"""
    try:
        import yfinance as yf
        fd = yf.Ticker(code + ".TW").funds_data
        th = fd.top_holdings
        if th is None or len(th) == 0:
            return None
        th = th.reset_index()
        sym = th.columns[0]
        out = pd.DataFrame({
            "code": th[sym].astype(str).str.replace(r"\.(TW|TWO)$", "", regex=True),
            "name": th["Name"] if "Name" in th else "",
            "weight": pd.to_numeric(th["Holding Percent"], errors="coerce") * 100 if "Holding Percent" in th else np.nan,
        })
        out = out[out["weight"].notna()]
        return out if len(out) else None
    except Exception:
        return None


# ------------------------------------------------------------------ 分析
def diff_holdings(new, old, tol=0.05):
    """兩份持股快照相比：新增、剔除、增持、減持（權重變動 > tol 個百分點才算）。"""
    n = new.set_index("code")
    o = old.set_index("code")
    codes = sorted(set(n.index) | set(o.index))
    rows = []
    for c in codes:
        wn = float(n.loc[c, "weight"]) if c in n.index else 0.0
        wo = float(o.loc[c, "weight"]) if c in o.index else 0.0
        name = (n.loc[c, "name"] if c in n.index else o.loc[c, "name"])
        if c not in o.index:
            st = "新增"
        elif c not in n.index:
            st = "剔除"
        elif wn - wo > tol:
            st = "增持"
        elif wo - wn > tol:
            st = "減持"
        else:
            st = "不變"
        rows.append(dict(code=c, name=name, w_new=wn, w_old=wo, delta=wn - wo, status=st))
    d = pd.DataFrame(rows)
    order = {"新增": 0, "剔除": 1, "增持": 2, "減持": 3, "不變": 4}
    d["_o"] = d["status"].map(order)
    return d.sort_values(["_o", "delta"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


def concentration(df):
    w = df["weight"].sort_values(ascending=False)
    return dict(n=len(w), top1=float(w.iloc[:1].sum()), top5=float(w.iloc[:5].sum()), top10=float(w.iloc[:10].sum()))


def industry_weights(df, directory):
    ind = df["code"].map(lambda c: directory.get(c, {}).get("ind", "未分類"))
    return df.assign(ind=ind).groupby("ind")["weight"].sum().sort_values(ascending=False)
