# -*- coding: utf-8 -*-
"""
一鍵套用四項修改到 quant_radar_app.py 與 wanglai_data.py。
用法：把這支檔案放在兩個檔案所在的資料夾，執行  python apply_patches.py
- 會先備份成 *.bak（已存在就不覆蓋）
- 任何一處找不到對應原始碼就整支中止、什麼都不寫，不會改一半
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "quant_radar_app.py")
WL = os.path.join(HERE, "wanglai_data.py")


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def sub_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        sys.exit(f"❌ 找不到唯一的原始碼片段（{label}，找到 {n} 處）。檔案可能已被改過或版本不同，已中止，沒有寫入任何檔案。")
    return text.replace(old, new)


def sub_block(text, pattern, new, label):
    m = list(re.finditer(pattern, text, flags=re.S))
    if len(m) != 1:
        sys.exit(f"❌ 找不到唯一的區塊（{label}，找到 {len(m)} 處）。已中止，沒有寫入任何檔案。")
    return text[:m[0].start()] + new + text[m[0].end():]


# ======================================================================
# 修改 1：wanglai_data.py — score_weeks 避免前視偏誤
# ======================================================================
NEW_SCORE_WEEKS = r'''def score_weeks(dates, snaps, closes, bench, cfg=None, top_n=50, tie=0.1, price_dates=None):
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


'''

# ======================================================================
# 修改 2：隔日開盤成交的回測引擎
# ======================================================================
NEW_SIMULATE = r'''@st.cache_data(ttl=900, show_spinner=False)
def simulate_strategy(df, entry_score=40, exit_score=0, max_hold_days=10, stop_loss_pct=0.07,
                      cost_bps=15, entry_max=None):
    """
    訊號用當日收盤算出，隔日開盤成交（避免用同一根 K 棒的收盤價既算訊號又成交）。
    停損：盤中最低價觸及即出場，成交價 = min(開盤, 停損價)，跳空時比停損價更差。
    entry_max：進場分數上限（None＝不限），用來測「只在某個分數區間進場」。
    """
    dates = df.index
    opens, lows, closes = df['Open'].values, df['Low'].values, df['Close'].values
    n = len(df)
    equity = 1.0
    equity_curve = np.ones(n)
    position, pending, pending_reason, trades = None, None, None, []
    cost = cost_bps / 10000.0

    def close_position(i, px, reason):
        nonlocal equity, position
        gross = (px - position['entry_price']) / position['entry_price']
        net = (1 + gross) * (1 - cost) * (1 - cost) - 1
        equity *= (1 + net)
        trades.append({
            "進場日": dates[position['entry_i']], "出場日": dates[i],
            "進場價": round(position['entry_price'], 2), "出場價": round(px, 2),
            "報酬率(%)": round(net * 100, 2), "出場原因": reason})
        position = None

    for i in range(30, n):
        # 1) 先執行昨天收盤後決定的單，以今日開盤價成交
        if pending == "enter" and position is None:
            position = {"entry_i": i, "entry_price": opens[i]}
        elif pending == "exit" and position is not None:
            close_position(i, opens[i], pending_reason)
        pending, pending_reason = None, None

        # 2) 盤中停損
        if position is not None:
            stop_price = position['entry_price'] * (1 - stop_loss_pct)
            if lows[i] <= stop_price:
                close_position(i, min(opens[i], stop_price), "停損")

        # 3) 收盤後用今日資料算訊號，留到明天開盤執行
        latest, prev = df.iloc[i], df.iloc[i - 1]
        k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
        score_today = compute_score(latest, prev, k_name, patterns=None)
        if position is not None:
            if i - position['entry_i'] >= max_hold_days:
                pending, pending_reason = "exit", "到期(持有天數上限)"
            elif score_today < exit_score:
                pending, pending_reason = "exit", "訊號轉弱"
        elif score_today >= entry_score and (entry_max is None or score_today < entry_max):
            pending = "enter"

        equity_curve[i] = equity * (closes[i] / position['entry_price']) if position is not None else equity

    equity_series = pd.Series(equity_curve, index=dates).iloc[30:]
    return pd.DataFrame(trades), equity_series

'''

# ======================================================================
# 修改 3：失敗不快取的工具
# ======================================================================
CACHE_HELPER = r'''

class _NotCached(Exception):
    pass

def cache_if_ok(ttl, is_ok=lambda r: r is not None):
    """只有成功才快取。st.cache_data 不會快取例外，所以失敗時丟例外、外層再接住回傳原值。
    fn_name 當作參數傳入，讓不同函式的快取不會互相混在一起（注意：底線開頭的參數不會參與快取鍵，所以不能用 _fn_name）。"""
    def deco(fn):
        @st.cache_data(ttl=ttl, show_spinner=False)
        def _inner(fn_name, *a, **k):
            r = fn(*a, **k)
            if not is_ok(r):
                raise _NotCached(r)
            return r
        def _outer(*a, **k):
            try:
                return _inner(fn.__name__, *a, **k)
            except _NotCached as e:
                return e.args[0]
        _outer.__name__ = fn.__name__
        return _outer
    return deco
'''

DECORATORS = {
    "get_t86_by_date": "@cache_if_ok(21600)",
    "get_taifex_foreign_tx": "@cache_if_ok(1800)",
    "get_news_items": "@cache_if_ok(1800)",
    "get_market_volume_snapshot": "@cache_if_ok(3600)",
    "get_macro_series": "@cache_if_ok(900)",
    "get_institutional_streaks": "@cache_if_ok(21600, is_ok=lambda r: bool(r))",
    "get_taiwan_chips": '@cache_if_ok(900, is_ok=lambda r: r[2] == "success")',
}

# ======================================================================
# 修改 4：區間進場的歷史統計
# ======================================================================
NEW_HORIZON_FUNC = r'''def historical_horizon_stats(df, bucket, max_hold_days=10, stop_loss_pct=0.08):
    """
    拿這檔股票過去的走勢，模擬『分數落在這個區間就進場』的交易，
    統計真正發生過的平均報酬與平均持有天數（隔日開盤成交版回測引擎的結果）。
    """
    lo, hi = BUCKET_RANGE.get(bucket, (0, None))
    exit_score = 0 if lo >= 0 else -999     # 偏弱區間不套「分數<0就出場」，否則隔天就出場
    trades_df, _ = simulate_strategy(df, entry_score=lo, exit_score=exit_score, entry_max=hi,
                                     max_hold_days=max_hold_days, stop_loss_pct=stop_loss_pct, cost_bps=15)
    if trades_df is None or trades_df.empty:
        return None
    t = trades_df.copy()
    t['持有天數'] = (pd.to_datetime(t['出場日']) - pd.to_datetime(t['進場日'])).dt.days.clip(lower=1)
    return dict(avg_return=t['報酬率(%)'].mean(), avg_days=t['持有天數'].mean(),
               win_rate=(t['報酬率(%)'] > 0).mean() * 100, n=len(t))

'''

NEW_SCORE_TAB = '''            WL_LAG_DAYS = 3   # 假設：週五快照 → 下週一收盤才拿得到名單。可自行調整
            pdates = None
            if not demo:
                today = pd.Timestamp.now().normalize()
                pdates = {d: (pd.Timestamp(d) + pd.Timedelta(days=WL_LAG_DAYS)).strftime("%Y-%m-%d")
                          for d in use if pd.Timestamp(d) + pd.Timedelta(days=WL_LAG_DAYS) <= today}
            with st.spinner(f"取得 {len(cand)} 檔股價中…" if not demo else "計算中…"):
                if demo:
                    closes, bench = d_closes, d_bench
                else:
                    pl = sorted(pdates.values())
                    if pl:
                        closes, bench = wl_build_closes(cand, pl, directory), wl_bench(pl)
                    else:
                        closes, bench = pd.DataFrame(), pd.Series(dtype=float)
            sc = wl.score_weeks(use, snaps, closes, bench, cfg, price_dates=pdates)
'''

OLD_SCORE_TAB = '''            with st.spinner(f"取得 {len(cand)} 檔股價中…" if not demo else "計算中…"):
                if demo:
                    closes, bench = d_closes, d_bench
                else:
                    closes, bench = wl_build_closes(cand, use, directory), wl_bench(use)
            sc = wl.score_weeks(use, snaps, closes, bench, cfg)
'''


def main():
    for p in (APP, WL):
        if not os.path.exists(p):
            sys.exit(f"❌ 找不到 {p}，請把這支腳本放在兩個檔案所在的資料夾。")
    app, wl = read(APP), read(WL)

    # ---- 修改 1 ----
    wl = sub_block(wl, r"def score_weeks\(.*?(?=def score_summary\()", NEW_SCORE_WEEKS, "wanglai_data.score_weeks")
    app = sub_once(app, "{last['list_date']} 收盤至 {last['end_date']} 收盤", "{last['entry_date']} 收盤至 {last['end_date']} 收盤", "最新一週標題")
    app = sub_once(app, 'sc["list_date"].str[5:] + " → " + sc["end_date"].str[5:]', 'sc["entry_date"].str[5:] + " → " + sc["end_date"].str[5:]', "報酬區間欄")
    app = sub_once(app, "報酬＝名單日收盤到下一份快照日收盤，等權平均，不含交易成本。",
                   "報酬＝名單公布後第一個交易日收盤，到下一週同一天收盤，等權平均，不含交易成本。", "說明文字")
    app = sub_once(app, OLD_SCORE_TAB, NEW_SCORE_TAB, "成績單取股價段")

    # ---- 修改 2 ----
    app = sub_block(app, r"@st\.cache_data\(ttl=900, show_spinner=False\)\ndef simulate_strategy\(.*?(?=def compute_backtest_metrics\()",
                    NEW_SIMULATE, "simulate_strategy")

    # ---- 修改 3 ----
    stretch = 'STRETCH = {"width": "stretch"} if _st_version() >= (1, 50) else {"use_container_width": True}\n'
    app = sub_once(app, stretch, stretch + CACHE_HELPER, "STRETCH 定義")
    for name, deco in DECORATORS.items():
        pat = rf"@st\.cache_data\(ttl=\d+, show_spinner=False\)\n(def {name}\()"
        if len(re.findall(pat, app)) != 1:
            sys.exit(f"❌ 找不到 {name} 的快取裝飾器。已中止，沒有寫入任何檔案。")
        app = re.sub(pat, lambda m, d=deco: d + "\n" + m.group(1), app)

    # ---- 修改 4 ----
    app = sub_once(app, 'BUCKET_ENTRY_SCORE = {"≥40 (強勢偏多)": 40, "0~39 (溫和偏多)": 0, "-29~-1 (中性偏弱)": -30, "≤-30 (偏空)": -60}\n',
                   'BUCKET_RANGE = {"≥40 (強勢偏多)": (40, None), "0~39 (溫和偏多)": (0, 40),\n'
                   '                "-29~-1 (中性偏弱)": (-29, 0), "≤-30 (偏空)": (-999, -29)}\n', "BUCKET_ENTRY_SCORE")
    app = sub_block(app, r"def historical_horizon_stats\(.*?(?=# -{10,}\n# C：全市場流動性篩選池)", NEW_HORIZON_FUNC, "historical_horizon_stats")
    app = sub_once(app, "historical_horizon_stats(df_ind, BUCKET_ENTRY_SCORE.get(bucket, 0))", "historical_horizon_stats(df_ind, bucket)", "scan_candidates 呼叫")
    app = sub_once(app, "historical_horizon_stats(df, BUCKET_ENTRY_SCORE.get(bucket, 0))", "historical_horizon_stats(df, bucket)", "個股日誌按鈕呼叫")
    if "BUCKET_ENTRY_SCORE" in app:
        sys.exit("❌ 仍有殘留的 BUCKET_ENTRY_SCORE 參照，已中止。")

    # ---- 寫入（先備份）----
    for p, txt in ((APP, app), (WL, wl)):
        bak = p + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)
    print("✅ 已套用四項修改（原檔備份為 *.bak）。")
    print("   接著請執行：python -m py_compile quant_radar_app.py wanglai_data.py  檢查語法，再啟動 streamlit。")


if __name__ == "__main__":
    main()
