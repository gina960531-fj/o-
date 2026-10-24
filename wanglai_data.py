# -*- coding: utf-8 -*-
"""
大戶籌碼資料層（給 quant_radar_app.py 和 wanglai_collector.py 共用，不依賴 Streamlit）

資料來源
  集保結算所（TDCC）「集保戶股權分散表」開放資料，只提供「最新一週」，
  所以要靠每週下載一份存在本機（~/.quant_radar_data/wanglai/），累積起來才算得出週變動。
  融資融券：證交所（上市）、櫃買中心（上櫃）公開資料，抓不到時該欄顯示「—」，不影響其他欄位。

持股分級（TDCC 規定）：1=1~999股 … 12=400~600張 13=600~800張 14=800~1000張 15=1000張以上，17=合計
"""
import io
import os
import re

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:          # 沒裝 requests 時仍可使用示範資料與手動上傳
    requests = None

UA = {"User-Agent": "Mozilla/5.0"}
TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
LEVEL_COLS = [f"p{i}" for i in range(1, 16)]
STOCK_RE = r"[1-9]\d{3}"      # 個股代號：4 碼且首碼 1~9（0 開頭是 ETF，如 0050、0056，不列入）

# 使用者可調整的定義：big_from=從第幾級開始算大戶（12=400張以上、11=200張以上），retail_to=散戶算到第幾級
DEFAULT_CFG = {"big_from": 12, "retail_to": 8}


# ------------------------------------------------------------------ 儲存位置
def data_dir(demo=False):
    d = os.path.join(os.path.expanduser("~"), ".quant_radar_data", "wanglai_demo" if demo else "wanglai")
    os.makedirs(d, exist_ok=True)
    return d


def _date_from_name(fn, prefix):
    m = re.fullmatch(prefix + r"_(\d{8})\.csv", fn)
    return f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None


def list_dates(demo=False):
    ds = [_date_from_name(f, "tdcc") for f in os.listdir(data_dir(demo))]
    return sorted(d for d in ds if d)


def _path(kind, date_iso, demo=False):
    return os.path.join(data_dir(demo), f"{kind}_{date_iso.replace('-', '')}.csv")


def save_snapshot(wide, date_iso, demo=False):
    wide.to_csv(_path("tdcc", date_iso, demo), encoding="utf-8-sig")


def save_margin(margin, date_iso, demo=False):
    margin.to_csv(_path("margin", date_iso, demo), encoding="utf-8-sig")


def load_all(demo=False):
    """回傳 (日期清單, {日期: 持股分級寬表}, {日期: 融資融券表})。"""
    dates = list_dates(demo)
    snaps, margins = {}, {}
    for d in dates:
        snaps[d] = pd.read_csv(_path("tdcc", d, demo), index_col=0, dtype={0: str}, encoding="utf-8-sig")
        snaps[d].index = snaps[d].index.astype(str)
        mp = _path("margin", d, demo)
        if os.path.exists(mp):
            m = pd.read_csv(mp, index_col=0, dtype={0: str}, encoding="utf-8-sig")
            m.index = m.index.astype(str)
            margins[d] = m
    return dates, snaps, margins


def clear_demo():
    d = data_dir(True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))


# ------------------------------------------------------------------ 集保資料解析
def parse_tdcc_csv(text):
    """集保開放資料 CSV → 長表。欄位依位置讀：資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%"""
    df = pd.read_csv(io.StringIO(text.lstrip("\ufeff")), dtype=str, header=None)
    if df.empty:
        raise ValueError("檔案是空的")
    if not re.fullmatch(r"\d{8}", str(df.iloc[0, 0]).strip()):   # 第一列是標題就丟掉
        df = df.iloc[1:]
    if df.shape[1] < 6:
        raise ValueError("欄位數不足 6 欄，可能不是集保股權分散表")
    df = df.iloc[:, :6].copy()
    df.columns = ["date", "code", "level", "holders", "shares", "pct"]
    df["code"] = df["code"].astype(str).str.strip()
    for c in ["level", "holders", "shares", "pct"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    df = df.dropna(subset=["level"])
    df["level"] = df["level"].astype(int)
    return df


def to_wide(long_df):
    """長表 → 每檔一列：p1..p15（各級距占比%）、holders（股東總人數）、shares（總股數）。只留 4 碼個股。"""
    d = long_df[long_df["code"].str.fullmatch(STOCK_RE)]
    if d.empty:
        raise ValueError("找不到 4 碼個股資料")
    date_raw = str(int(d["date"].iloc[0])) if str(d["date"].iloc[0]).strip().isdigit() else str(d["date"].iloc[0]).strip()
    date_iso = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
    pct = d[d["level"].between(1, 15)].pivot_table(index="code", columns="level", values="pct", aggfunc="sum")
    pct.columns = [f"p{int(c)}" for c in pct.columns]
    pct = pct.reindex(columns=LEVEL_COLS).fillna(0.0)
    tot = d[d["level"] == 17].drop_duplicates("code").set_index("code")[["holders", "shares"]]
    lv = d[d["level"].between(1, 15)].groupby("code")[["holders", "shares"]].sum()
    wide = pct.join(tot, how="left")
    wide["holders"] = wide["holders"].fillna(lv["holders"])
    wide["shares"] = wide["shares"].fillna(lv["shares"])
    return wide, date_iso


def ingest_tdcc_text(text, demo=False):
    wide, date_iso = to_wide(parse_tdcc_csv(text))
    if len(wide) < 800:
        raise ValueError(f"只解析出 {len(wide)} 檔個股，數量太少，集保檔案格式可能改版了")
    save_snapshot(wide, date_iso, demo)
    return {"date": date_iso, "n_stocks": len(wide)}


def download_tdcc_text(timeout=90):
    if requests is None:
        raise RuntimeError("沒有安裝 requests，請先執行：pip install requests")
    r = requests.get(TDCC_URL, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.content.decode("utf-8-sig", errors="replace")


# ------------------------------------------------------------------ 融資融券（盡力而為）
def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return np.nan


def fetch_margin_twse(date_iso):
    ds = date_iso.replace("-", "")
    url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=ALL&response=json"
    js = requests.get(url, headers=UA, timeout=30).json()
    tables = js.get("tables") or ([{"fields": js.get("fields"), "data": js.get("data")}] if js.get("data") else [])
    out = {}
    for t in tables:
        fields, data = t.get("fields") or [], t.get("data") or []
        if len(fields) >= 14:
            for r in data:
                code = str(r[0]).strip()
                if re.fullmatch(STOCK_RE, code):
                    out[code] = (_num(r[6]), _num(r[12]))      # 融資今日餘額、融券今日餘額（張）
    return out


def fetch_margin_tpex(date_iso):
    y, m, d = date_iso.split("-")
    url = ("https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php"
           f"?l=zh-tw&o=json&d={int(y) - 1911}/{m}/{d}")
    js = requests.get(url, headers=UA, timeout=30).json()
    rows = js.get("aaData") or ((js.get("tables") or [{}])[0].get("data")) or []
    out = {}
    for r in rows:
        code = str(r[0]).strip()
        if re.fullmatch(STOCK_RE, code) and len(r) > 14:
            out[code] = (_num(r[6]), _num(r[14]))
    return out


def fetch_margin(date_iso):
    got, notes = {}, []
    for name, fn in (("上市", fetch_margin_twse), ("上櫃", fetch_margin_tpex)):
        try:
            part = fn(date_iso)
            if part:
                got.update(part)
            else:
                notes.append(f"{name}融資融券沒有抓到資料")
        except Exception as e:
            notes.append(f"{name}融資融券抓取失敗：{str(e)[:60]}")
    df = pd.DataFrame.from_dict(got, orient="index", columns=["margin_long", "margin_short"]) if got else pd.DataFrame()
    return df, notes


def collect_latest(demo=False):
    """下載最新一週集保資料並存檔，再抓同一天的融資融券。回傳 dict(ok, date, n_stocks, messages)。"""
    res = {"ok": False, "date": None, "n_stocks": 0, "messages": []}
    try:
        info = ingest_tdcc_text(download_tdcc_text(), demo)
    except Exception as e:
        res["messages"].append(f"下載或解析集保資料失敗：{e}")
        return res
    res.update(info, ok=True)
    if requests is not None:
        margin, notes = fetch_margin(info["date"])
        res["messages"] += notes
        if not margin.empty:
            save_margin(margin, info["date"], demo)
            res["messages"].append(f"融資融券已存檔（{len(margin)} 檔）")
    return res


# ------------------------------------------------------------------ 週變動計算
def layers(wide, cfg=None):
    cfg = cfg or DEFAULT_CFG
    big = wide[[f"p{i}" for i in range(cfg["big_from"], 16)]].sum(axis=1)
    retail = wide[[f"p{i}" for i in range(1, cfg["retail_to"] + 1)]].sum(axis=1)
    return pd.DataFrame({"big": big, "mega": wide["p15"], "retail": retail, "holders": wide["holders"]})


def weekly_delta(new, old, cfg=None, m_new=None, m_old=None):
    """兩週快照相減：大戶Δ、千張Δ、散戶Δ（百分點）、400~999張層Δ、股東人數變化、融資增減%、券資比。"""
    a, b = layers(new, cfg), layers(old, cfg)
    idx = a.index.intersection(b.index)
    d = pd.DataFrame(index=idx)
    d["big"] = a.loc[idx, "big"].round(2)
    d["big_d"] = (a.loc[idx, "big"] - b.loc[idx, "big"]).round(2)
    d["mega_d"] = (a.loc[idx, "mega"] - b.loc[idx, "mega"]).round(2)
    d["retail_d"] = (a.loc[idx, "retail"] - b.loc[idx, "retail"]).round(2)
    d["mid_d"] = (d["big_d"] - d["mega_d"]).round(2)         # 400~999張這一層的變化
    d["holders_d"] = a.loc[idx, "holders"] - b.loc[idx, "holders"]
    d["margin_chg"] = np.nan
    d["ratio"] = np.nan
    if m_new is not None and m_old is not None and not m_new.empty and not m_old.empty:
        ml_n = m_new["margin_long"].reindex(idx)
        ml_o = m_old["margin_long"].reindex(idx)
        ms_n = m_new["margin_short"].reindex(idx)
        d["margin_chg"] = np.where(ml_o > 0, (ml_n / ml_o - 1) * 100, np.nan)
        d["ratio"] = np.where(ml_n > 0, ms_n / ml_n * 100, np.nan)
    return d


def streaks(hist, thr=1.0):
    """hist：各週大戶Δ（欄位由新到舊）。回傳連續『大戶增≥thr』與『大戶減≤-thr』的週數（含本週）。"""
    up = pd.Series(0, index=hist.index)
    dn = pd.Series(0, index=hist.index)
    alive_up = pd.Series(True, index=hist.index)
    alive_dn = pd.Series(True, index=hist.index)
    for c in hist.columns:
        alive_up &= hist[c] >= thr
        alive_dn &= hist[c] <= -thr
        up += alive_up.astype(int)
        dn += alive_dn.astype(int)
    return up, dn


def make_tags(row):
    """標籤規則（由使用者提供的截圖數字反推，並用截圖中 40 多檔股票驗證過）。"""
    tags = []
    if row["mid_d"] > 0 and row["mega_d"] < 0:
        tags.append("千張降級")       # 千張大戶減少，但 400~999張層增加：大戶從千張往下掉一級
    if row["mid_d"] < 0 and row["mega_d"] > 0:
        tags.append("中大戶升格")     # 400~999張層減少，千張大戶增加：中大戶往上升一級
    p = row.get("prev_big_d", np.nan)
    if pd.notna(p):
        if p <= -1 and row["big_d"] >= 1:
            tags.append("回頭車")
        if p >= 1 and row["big_d"] <= -1:
            tags.append("下車")
    if row.get("streak_up", 0) >= 2:
        tags.append(f"連買{int(row['streak_up'])}")
    if row.get("streak_dn", 0) >= 2:
        tags.append(f"連賣{int(row['streak_dn'])}")
    return tags


def build_week(dates, snaps, margins, k, cfg=None):
    """第 k 週（dates[k]）相對上一週的完整報表，含上週變動、連買連賣、標籤。k 至少為 1。"""
    cur, prev = dates[k], dates[k - 1]
    d = weekly_delta(snaps[cur], snaps[prev], cfg, margins.get(cur), margins.get(prev))
    hist = {}
    for i in range(1, k + 1):
        hist[dates[i]] = weekly_delta(snaps[dates[i]], snaps[dates[i - 1]], cfg)["big_d"]
    hist = pd.DataFrame(hist).reindex(d.index)
    d["prev_big_d"] = hist[dates[k - 1]] if k >= 2 else np.nan
    up, dn = streaks(hist.iloc[:, ::-1])
    d["streak_up"], d["streak_dn"] = up, dn
    d["tag_list"] = d.apply(make_tags, axis=1)
    d["tags"] = d["tag_list"].apply(lambda t: " · ".join(t))
    return d


def exchange_groups(d, thr=1.0):
    """大戶換手四組：上週與本週大戶Δ都要超過 ±thr 個百分點才列入。"""
    p, c = d["prev_big_d"], d["big_d"]
    return {
        "續買": d[(p >= thr) & (c >= thr)],
        "回頭車": d[(p <= -thr) & (c >= thr)],
        "下車": d[(p >= thr) & (c <= -thr)],
        "續賣": d[(p <= -thr) & (c <= -thr)],
    }


# ------------------------------------------------------------------ 成績單
def week_returns(codes, closes, d0, d1):
    """等權平均報酬：d0 收盤 → d1 收盤。closes：index=代號、欄位=日期(ISO) 的收盤價表。"""
    c = [x for x in codes if x in closes.index]
    r = ((closes.loc[c, d1] / closes.loc[c, d0] - 1) * 100).dropna()
    return r


def score_weeks(dates, snaps, closes, bench, cfg=None, top_n=50, tie=0.1, price_dates=None):
    """
    名單＝dates[k-1]→dates[k] 的集保變動；報酬＝「進場價日」收盤 → 「下一週進場價日」收盤。
    price_dates：{快照日: 實際可進場的價格日}。集保資料是事後才公布，不能用快照日（週五）收盤當進場價。
    price_dates=None 時退回舊行為（只給示範資料用）。
    """
    pdm = price_dates if price_dates is not None else {d: d for d in dates}
    rows = []
    for k in range(1, len(dates) - 1):
        d0, d1 = pdm.get(dates[k]), pdm.get(dates[k + 1])
        if d0 is None or d1 is None:
            continue
        if d0 not in closes.columns or d1 not in closes.columns:
            continue
        d = weekly_delta(snaps[dates[k]], snaps[dates[k - 1]], cfg)
        buy = d.sort_values("big_d", ascending=False).head(top_n).index
        sell = d.sort_values("big_d", ascending=True).head(top_n).index
        rb, rs = week_returns(buy, closes, d0, d1), week_returns(sell, closes, d0, d1)
        if rb.empty or rs.empty or d0 not in bench.index or d1 not in bench.index:
            continue
        b = (bench[d1] / bench[d0] - 1) * 100
        diff = rb.mean() - rs.mean()
        rows.append({
            "list_date": dates[k], "entry_date": d0, "end_date": d1,
            "buy_avg": rb.mean(), "sell_avg": rs.mean(), "bench": b,
            "buy_med": rb.median(), "sell_med": rs.median(),
            "buy_up": int((rb > 0).sum()), "buy_dn": int((rb < 0).sum()), "buy_n": len(rb),
            "sell_up": int((rs > 0).sum()), "sell_dn": int((rs < 0).sum()), "sell_n": len(rs),
            "buy_beat": int((rb > b).sum()), "sell_beat": int((rs > b).sum()),
            "result": "買組勝" if diff > tie else ("賣組勝" if diff < -tie else "平"),
            "buy_codes": list(rb.index), "sell_codes": list(rs.index), "buy_ret": rb, "sell_ret": rs,
        })
    return pd.DataFrame(rows)


def score_summary(sc):
    """多週彙總：平均、複利累積、正報酬週數、直接比輸贏。"""
    if sc is None or sc.empty:
        return None
    comp = lambda s: (np.prod(1 + s / 100) - 1) * 100
    return {
        "weeks": len(sc),
        "buy_mean": sc["buy_avg"].mean(), "sell_mean": sc["sell_avg"].mean(),
        "buy_cum": comp(sc["buy_avg"]), "sell_cum": comp(sc["sell_avg"]), "bench_cum": comp(sc["bench"]),
        "buy_pos": int((sc["buy_avg"] > 0).sum()), "sell_pos": int((sc["sell_avg"] > 0).sum()),
        "win": int((sc["result"] == "買組勝").sum()), "lose": int((sc["result"] == "賣組勝").sum()),
        "tie": int((sc["result"] == "平").sum()),
    }


def split_stats(ret, cond):
    """把一組報酬依條件切成 符合／不符合 兩半，各算檔數、平均、上漲／下跌檔數。"""
    out = {}
    for name, mask in (("符合", cond), ("不符合", ~cond)):
        r = ret[mask.reindex(ret.index).fillna(False)]
        out[name] = {"n": len(r), "avg": r.mean() if len(r) else np.nan,
                     "up": int((r > 0).sum()), "dn": int((r < 0).sum())}
    return out


# ------------------------------------------------------------------ 示範資料（隨機產生，非真實）
def make_demo(codes, n_weeks=14, seed=7, end_date=None):
    """產生 n_weeks 週的隨機示範資料（集保、融資融券、股價、大盤）。股價與籌碼完全無關，所以示範成績單不會有 edge。"""
    rng = np.random.RandomState(seed)
    codes = [str(c) for c in codes if re.fullmatch(STOCK_RE, str(c))][:240]
    n = len(codes)
    end = pd.Timestamp(end_date) if end_date else pd.Timestamp.now().normalize()
    while end.weekday() != 4:
        end -= pd.Timedelta(days=1)
    dates = [(end - pd.Timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(n_weeks - 1, -1, -1)]

    big = rng.uniform(8, 60, n)
    retail = (100 - big) * rng.uniform(0.35, 0.75, n)
    w_r = rng.dirichlet([6, 5, 4, 3, 2, 2, 1.5, 1], n)
    w_m = rng.dirichlet([4, 3, 2], n)
    w_b = rng.dirichlet([5, 3, 2, 4], n)
    holders = rng.uniform(3000, 90000, n)
    shares = rng.uniform(5e7, 3e9, n)
    mlong = rng.uniform(200, 8000, n)
    mratio = rng.uniform(0.001, 0.15, n)
    px = rng.uniform(20, 800, n)
    bench = 20000.0
    clear_demo()
    price_rows, bench_rows = [], []
    for d in dates:
        db = rng.normal(0, 1.1, n)
        big = np.clip(big + db, 2, 85)
        retail = np.clip(retail - 0.8 * db + rng.normal(0, 0.3, n), 3, 92 - big)
        mid = 100 - big - retail
        holders = holders * (1 - 0.01 * db + rng.normal(0, 0.004, n))
        mlong = mlong * np.exp(rng.normal(0, 0.04, n))
        px = px * np.exp(rng.normal(0.002, 0.045, n))
        bench *= np.exp(rng.normal(0.003, 0.02))
        cols = {}
        for j in range(8):
            cols[f"p{j + 1}"] = retail * np.clip(w_r[:, j] + rng.normal(0, 0.01, n), 0.001, None)
        for j in range(3):
            cols[f"p{j + 9}"] = mid * w_m[:, j]
        for j in range(4):
            cols[f"p{j + 12}"] = big * w_b[:, j]
        wide = pd.DataFrame(cols, index=codes)
        wide = wide.div(wide.sum(axis=1), axis=0) * 100
        wide["holders"] = holders.round()
        wide["shares"] = shares.round()
        save_snapshot(wide, d, True)
        save_margin(pd.DataFrame({"margin_long": mlong.round(), "margin_short": (mlong * mratio).round()}, index=codes), d, True)
        price_rows += [(d, c, p) for c, p in zip(codes, px)]
        bench_rows.append((d, bench))
    pd.DataFrame(price_rows, columns=["date", "code", "close"]).to_csv(os.path.join(data_dir(True), "prices.csv"), index=False)
    pd.DataFrame(bench_rows, columns=["date", "close"]).to_csv(os.path.join(data_dir(True), "bench.csv"), index=False)
    return dates


def load_demo_prices():
    p = pd.read_csv(os.path.join(data_dir(True), "prices.csv"), dtype={"code": str})
    closes = p.pivot(index="code", columns="date", values="close")
    b = pd.read_csv(os.path.join(data_dir(True), "bench.csv")).set_index("date")["close"]
    return closes, b
