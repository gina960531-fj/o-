# -*- coding: utf-8 -*-
"""
隔夜美股 → 下一個台股交易日 的歷史統計（純 pandas，不依賴 Streamlit）。

做法：對每個台股交易日 T，找「嚴格早於 T 的最近一個美股交易日 d」（美股 d 日收盤是台北 T 日清晨），
配成一對 (美股 d 日漲跌, 台股 T 日漲跌)。之後可以問：
「過去隔夜費半跌超過 1.5% 時，隔天 0050 上漲的比例是多少？樣本有多少？這個關聯在統計上站得住腳嗎？」
這是描述歷史，不是保證未來。
"""
import math

import numpy as np
import pandas as pd

BUCKETS = [(-np.inf, -1.5, "隔夜大跌（≤ -1.5%）"), (-1.5, -0.5, "隔夜小跌（-1.5%～-0.5%）"), (-0.5, 0.5, "隔夜持平（±0.5%）"),
           (0.5, 1.5, "隔夜小漲（0.5%～1.5%）"), (1.5, np.inf, "隔夜大漲（≥ +1.5%）")]


def _clean(s):
    s = pd.Series(s).dropna().astype(float)
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def build_pairs(tw_close, us_close):
    """回傳 DataFrame：tw_date, us_date, us_ret(%), tw_ret(%)。美股休市造成同一天被重複配對時，只保留第一筆。"""
    tw, us = _clean(tw_close), _clean(us_close)
    if len(tw) < 30 or len(us) < 30:
        return pd.DataFrame(columns=["tw_date", "us_date", "us_ret", "tw_ret"])
    left = pd.DataFrame({"tw_date": tw.index, "tw_ret": tw.pct_change().values * 100}).dropna()
    right = pd.DataFrame({"us_date": us.index, "us_ret": us.pct_change().values * 100}).dropna()
    m = pd.merge_asof(left.sort_values("tw_date"), right.sort_values("us_date"), left_on="tw_date", right_on="us_date",
                      direction="backward", allow_exact_matches=False).dropna()
    m = m[m["us_date"] != m["us_date"].shift()]          # 美股休市：同一個美股日不重複計
    return m.reset_index(drop=True)


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def correlation(pairs):
    """Pearson 相關係數、近似雙尾 p 值。樣本不足回傳 (nan, nan, n)。"""
    n = len(pairs)
    if n < 30:
        return np.nan, np.nan, n
    r = float(np.corrcoef(pairs["us_ret"], pairs["tw_ret"])[0, 1])
    if abs(r) >= 0.999999:
        return r, 0.0, n
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return r, float(2 * (1 - _norm_cdf(abs(t)))), n


def bucket_of(us_ret):
    for lo, hi, label in BUCKETS:
        if lo <= us_ret < hi:
            return label
    return BUCKETS[-1][2]


def bucket_table(pairs):
    """每個隔夜漲跌區間：樣本數、台股隔日上漲比例、平均漲跌%。"""
    if pairs.empty:
        return pd.DataFrame()
    p = pairs.assign(bucket=pairs["us_ret"].map(bucket_of))
    g = p.groupby("bucket").agg(樣本數=("tw_ret", "count"), 上漲比例=("tw_ret", lambda x: (x > 0).mean() * 100), 平均漲跌=("tw_ret", "mean"))
    g = g.rename(columns={"上漲比例": "上漲比例(%)", "平均漲跌": "平均漲跌(%)"})
    return g.reindex([b[2] for b in BUCKETS if b[2] in g.index])


def edge_for(today_us_ret, pairs):
    """
    今天的隔夜漲跌落在哪一區、歷史上同區間台股的表現，以及整體關聯是否顯著。
    verdict：'useful'（相關係數明顯且 p<0.05，且該區間樣本≥20）、'weak'、'insufficient'。
    """
    r, p, n = correlation(pairs)
    base_up = float((pairs["tw_ret"] > 0).mean() * 100) if len(pairs) else np.nan
    out = dict(n_total=n, corr=r, p=p, base_up=base_up, bucket=None, n=0, up_prob=np.nan, mean_ret=np.nan, verdict="insufficient")
    if today_us_ret is None or pd.isna(today_us_ret) or len(pairs) < 30:
        return out
    label = bucket_of(today_us_ret)
    sub = pairs[pairs["us_ret"].map(bucket_of) == label]
    out.update(bucket=label, n=len(sub))
    if len(sub):
        out.update(up_prob=float((sub["tw_ret"] > 0).mean() * 100), mean_ret=float(sub["tw_ret"].mean()))
    if len(sub) < 20:
        out["verdict"] = "insufficient"
    elif pd.notna(p) and p < 0.05 and abs(r) >= 0.1:
        out["verdict"] = "useful"
    else:
        out["verdict"] = "weak"
    return out
