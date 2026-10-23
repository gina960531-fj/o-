# -*- coding: utf-8 -*-
"""
第二批修改：效能優化 ＋ 「🎯 大戶選股」分頁。
用法：和 app.py、wanglai_data.py、wanglai_picks.py 放同一個資料夾，執行  python apply_patches2.py

每一步彼此獨立：找不到對應位置的那一步會「略過並說明」，不影響其他步驟。
第 4、6 步需要第 1 步成功；第 4 步另外需要先跑過 apply_patches.py（修改 4）。
有任何修改才會寫檔，寫之前先備份成 app.py.bak2（已存在就不覆蓋）。
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))


# ======================================================================
# 步驟 1：向量化評分、回測、工具函式
# ======================================================================
HELPERS_AND_BACKTEST = r'''def vector_score(df):
    """向量化版的 compute_score(patterns=None)：一次算出整段歷史的分數，結果與逐列版完全一致。"""
    n = len(df)
    h = df['Hist'].values.astype(float)
    ph = np.roll(h, 1)
    ph[0] = np.nan
    s = np.zeros(n)
    s += np.where(h > 0, np.where(ph <= 0, 35, np.where(h > ph, 25, 5)), 0)
    s += np.where(h < 0, np.where(ph >= 0, -35, np.where(h < ph, -25, -5)), 0)
    w = df['WPR'].values.astype(float)
    s += np.where(w < -80, 20, 0) + np.where(w > -20, -20, 0)
    o, hi, lo, c = (df[x].values.astype(float) for x in ('Open', 'High', 'Low', 'Close'))
    tr = np.maximum(hi - lo, 0.001)
    body = np.abs(c - o)
    us, ls = hi - np.maximum(o, c), np.minimum(o, c) - lo
    doji = body / tr < 0.05
    up = ~doji & (c > o)
    down = ~doji & ~(c > o)
    hammer = (up | down) & (ls > body * 1.5)
    s += np.where(up, 15, 0) + np.where(down, -15, 0) + np.where(hammer, 10, 0)
    s += np.where(c > df['MA20'].values.astype(float), 10, -10)
    return pd.Series(s, index=df.index)


@st.cache_data(ttl=900, show_spinner=False)
def load_price_only(ticker_symbol):
    """只抓日線（不抓 info 與財報），掃描時先用價量條件篩掉大部分股票，再對通過的才抓基本面。"""
    try:
        df = yf.Ticker(ticker_symbol).history(period="2y")
        if df is not None and not df.empty:
            df = df.dropna(subset=['Close', 'High', 'Low', 'Open', 'Volume'])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def load_info_only(ticker_symbol):
    try:
        info = yf.Ticker(ticker_symbol).info
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _st_thread_pool(max_workers=6):
    """執行緒池；盡量把 Streamlit 的執行環境帶進工作執行緒，避免快取函式在執行緒內報警告。"""
    try:
        import threading
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()

        def _init():
            if ctx is not None:
                add_script_run_ctx(threading.current_thread(), ctx)
        return ThreadPoolExecutor(max_workers=max_workers, initializer=_init)
    except Exception:
        return ThreadPoolExecutor(max_workers=max_workers)


@st.cache_data(ttl=900, show_spinner=False)
def backtest_score_system(df):
    df = df.reset_index(drop=True)
    n = len(df)
    if n < 32:
        return pd.DataFrame()
    scores = vector_score(df).values
    close = df['Close'].values.astype(float)
    nxt = np.full(n, np.nan)
    nxt[:-1] = (close[1:] - close[:-1]) / close[:-1] * 100
    idx = np.arange(n)
    valid = (idx >= 30) & (idx <= n - 2) & (close > 0) & np.isfinite(nxt)
    if not valid.any():
        return pd.DataFrame()
    sc = scores[valid]
    bucket = np.select([sc >= 40, sc >= 0, sc > -30],
                       ["≥40 (強勢偏多)", "0~39 (溫和偏多)", "-29~-1 (中性偏弱)"], default="≤-30 (偏空)")
    rec_df = pd.DataFrame({"bucket": bucket, "next_return": nxt[valid]})
    summary = rec_df.groupby("bucket").agg(
        樣本數=("next_return", "count"),
        平均隔日報酬=("next_return", "mean"),
        上漲機率=("next_return", lambda x: (x > 0).mean() * 100)
    )
    summary = summary.rename(columns={"平均隔日報酬": "平均隔日報酬(%)", "上漲機率": "上漲機率(%)"})
    order = ["≥40 (強勢偏多)", "0~39 (溫和偏多)", "-29~-1 (中性偏弱)", "≤-30 (偏空)"]
    return summary.reindex([b for b in order if b in summary.index])

'''

# ======================================================================
# 步驟 2：模擬進出場改用預先算好的分數
# ======================================================================
NEW_SIMULATE = r'''@st.cache_data(ttl=900, show_spinner=False)
def simulate_strategy(df, entry_score=40, exit_score=0, max_hold_days=10, stop_loss_pct=0.07,
                      cost_bps=15, entry_max=None):
    """
    訊號用當日收盤算出，隔日開盤成交（避免用同一根 K 棒的收盤價既算訊號又成交）。
    停損：盤中最低價觸及即出場，成交價 = min(開盤, 停損價)，跳空時比停損價更差。
    entry_max：進場分數上限（None＝不限），用來測「只在某個分數區間進場」。
    分數用 vector_score 一次算完，不再逐列呼叫評分函式。
    """
    dates = df.index
    opens, lows, closes = df['Open'].values, df['Low'].values, df['Close'].values
    scores = vector_score(df).values
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

        # 3) 收盤後用今日分數決定，留到明天開盤執行
        score_today = scores[i]
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
# 步驟 3：CCI
# ======================================================================
OLD_CCI = "mad_tp = tp.rolling(14, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean()).replace(0, np.nan)"
NEW_CCI = "mad_tp = tp.rolling(14, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True).replace(0, np.nan)"

# ======================================================================
# 步驟 4：平行掃描＋先價量後基本面
# ======================================================================
NEW_SCAN = r'''def scan_candidates(tickers, streak_map, fund_filter=None, q_income_cache=None, directory=None, tech_filter=None,
                    min_rr=None, industry_filter=None):
    """
    平行掃描。先只抓日線，用技術條件與風報比篩掉大部分股票；
    通過的才額外抓 info（基本面），所以多數股票不用等最慢的 info 請求。
    各篩選條件彼此是「且」的關係，先後順序不影響結果。
    """
    fund_filter = fund_filter or {}
    streak_map = streak_map or {}

    def _one(tk):
        try:
            code_bare = tk.split(".")[0]
            if industry_filter:
                ind = (directory or {}).get(code_bare, {}).get("ind")
                if ind not in industry_filter:
                    return None

            df = load_price_only(tk)
            if df is None or df.empty or len(df) < 40:
                return None

            df_ind = compute_indicators(df)
            latest, prev = df_ind.iloc[-1], df_ind.iloc[-2]
            if not passes_tech_filter(latest, prev, tech_filter):
                return None
            k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
            tech_comps = score_components(latest, prev, k_name, patterns=None)
            tech_score = sum(p for _, p in tech_comps)
            bucket = score_to_bucket(tech_score)

            lv = compute_levels(df_ind, latest, latest['Close'], tech_score)
            if min_rr is not None and (lv['rr'] is None or lv['rr'] < min_rr):
                return None

            bt = backtest_score_system(df_ind)
            wr = n = None
            if bt is not None and not bt.empty and bucket in bt.index:
                wr, n = bt.loc[bucket, '上漲機率(%)'], int(bt.loc[bucket, '樣本數'])

            info = load_info_only(tk)
            if fund_filter and not passes_fundamental_filter(info, None, **fund_filter):
                return None
            fund_comps = fundamental_score_components(info)
            fund_score = sum(p for _, p in fund_comps)

            streak = streak_map.get(code_bare, {})
            has_chip_data = bool(streak) and (streak.get("foreign") is not None)
            chip_comps = chip_score_components(streak) if has_chip_data else []
            chip_sc = sum(p for _, p in chip_comps)

            bt_bonus = 10 if (wr is not None and n is not None and n >= 10 and wr - 50 >= 15) else 0
            composite = tech_score + fund_score + chip_sc + bt_bonus

            name = resolve_display_name(tk, code_bare, info, directory)
            all_comps = tech_comps + fund_comps + chip_comps
            reasons = [t for t, p in all_comps if p > 0]
            risks = [t for t, p in all_comps if p < 0]
            if wr is not None and n is not None and n >= 10:
                if wr >= 55:
                    reasons.append(f"歷史同分數區間隔日上漲機率 {wr:.0f}%（N={n}）")
                elif wr <= 45:
                    risks.append(f"歷史同分數區間隔日上漲機率僅 {wr:.0f}%（N={n}）")
            if not has_chip_data:
                risks.append("籌碼資料（連續買賣超）暫時抓不到，此項未計入評分")

            direction, action, buy_price, _r, color, _s, _b = predict_next_day(latest, prev, k_name, [], bt)
            horizon = historical_horizon_stats(df_ind, bucket)

            return dict(ticker=tk, code=code_bare, name=name, price=latest['Close'],
                        composite=composite, tech=tech_score, fund=fund_score, chip=chip_sc,
                        wr=wr, n=n, reasons=reasons, risks=risks, has_chip_data=has_chip_data,
                        direction=direction, entry_action=action, buy_price=buy_price,
                        stop=lv['near_stop'], target1=lv['target1'], target2=lv['target2'], rr=lv['rr'],
                        horizon=horizon)
        except Exception:
            return None

    tickers = list(tickers)
    if not tickers:
        return []
    with _st_thread_pool(6) as ex:
        rows = [r for r in ex.map(_one, tickers) if r]
    return sorted(rows, key=lambda r: r['composite'], reverse=True)


'''

# ======================================================================
# 步驟 5、6：大戶選股
# ======================================================================
WP_IMPORT = '''
# 大戶選股（wanglai_picks.py 要和本檔放在同一個資料夾；缺少時只有「大戶籌碼 → 大戶選股」分頁會顯示提示）
try:
    import wanglai_picks as wp
except Exception:
    wp = None
'''

PICKS_UI = r'''def render_big_holder_picks(wk, directory, demo, week_label):
    st.markdown(f"#### 🎯 大戶選股　<span style='color:#7b8794;font-size:0.85em'>{week_label} 這週的集保變動</span>", unsafe_allow_html=True)
    st.caption("流程：先用集保週報挑出「大戶這週明顯增持」的股票並打籌碼分，再對前幾名用日線技術面做確認、算出停損停利與風報比。"
               "兩個分數的權重是經驗設定，沒有經過統計驗證。")
    if wp is None:
        st.error("找不到 wanglai_picks.py。請把它和 app.py 放在同一個資料夾，再重新整理。")
        return
    if demo:
        st.warning("⚠️ 目前是隨機產生的示範籌碼資料，只能預覽畫面；技術面是真實股價，但兩者沒有關係，結果不具任何意義。")

    c1, c2, c3, c4 = st.columns(4)
    min_big = c1.slider("大戶週增至少（百分點）", 0.5, 5.0, 1.0, 0.5, key="pk_min_big")
    pool_n = c2.slider("取籌碼分前幾名做技術確認", 10, 60, 30, 5, key="pk_pool")
    need_ma = c3.checkbox("技術面要站上月線", value=False, key="pk_ma")
    min_rr = c4.selectbox("風報比至少", [0.0, 1.0, 1.5, 2.0], format_func=lambda x: "不限" if x == 0 else f"1 : {x}", key="pk_rr")
    run = st.button("🎯 開始選股", type="primary", key="pk_run")

    if run:
        chip = wp.chip_pick_score(wk, min_big_d=min_big)
        if chip.empty:
            st.session_state["pk_result"] = {"rows": [], "week": week_label, "n_chip": 0}
        else:
            top = chip.head(pool_n)

            def _tech(code):
                suf = directory.get(code, {}).get("suffix", ".TW")
                df = None
                for sfx in (suf, ".TWO" if suf == ".TW" else ".TW"):
                    df = load_price_only(code + sfx)
                    if df is not None and len(df) >= 40:
                        break
                else:
                    return None
                try:
                    d = compute_indicators(df)
                    latest, prev = d.iloc[-1], d.iloc[-2]
                    k = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
                    sc = compute_score(latest, prev, k, patterns=None)
                    lv = compute_levels(d, latest, latest['Close'], sc)
                    return dict(score=sc, price=float(latest['Close']), stop=lv['near_stop'], t1=lv['target1'],
                                rr=lv['rr'], above_ma=bool(latest['Close'] > latest['MA20']))
                except Exception:
                    return None

            with st.spinner(f"抓取 {len(top)} 檔股價並做技術確認中…"):
                with _st_thread_pool(6) as ex:
                    techs = list(ex.map(_tech, list(top.index)))
            rows = []
            for (code, r), t in zip(top.iterrows(), techs):
                w = wk.loc[code]
                comp = r["chip_score"] + (0.5 * t["score"] if t else 0)
                rows.append(dict(code=code, name=directory.get(code, {}).get("name", code), ind=directory.get(code, {}).get("ind", ""),
                                 big_d=w["big_d"], mega_d=w["mega_d"], holders_d=w["holders_d"], streak=int(w["streak_up"]),
                                 chip=r["chip_score"], tech=t["score"] if t else None, comp=round(comp, 1),
                                 price=t["price"] if t else None, stop=t["stop"] if t else None, t1=t["t1"] if t else None,
                                 rr=t["rr"] if t else None, above_ma=t["above_ma"] if t else None,
                                 tags=w["tags"], reasons=r["reasons"], risks=r["risks"]))
            st.session_state["pk_result"] = {"rows": rows, "week": week_label, "n_chip": len(chip)}

    res = st.session_state.get("pk_result")
    if not res:
        st.info("設好條件後按「開始選股」。")
        return
    rows = res["rows"]
    if not rows:
        st.info("這週沒有任何股票的大戶增幅達到你設的門檻，可以把「大戶週增至少」調低。")
        return
    if need_ma:
        rows = [r for r in rows if r["above_ma"]]
    if min_rr:
        rows = [r for r in rows if r["rr"] is not None and r["rr"] >= min_rr]
    sort_key = st.radio("排序", ["綜合分", "大戶籌碼分", "技術分"], horizontal=True, key="pk_sort")
    kf = {"綜合分": lambda r: r["comp"], "大戶籌碼分": lambda r: r["chip"], "技術分": lambda r: r["tech"] if r["tech"] is not None else -999}[sort_key]
    rows = sorted(rows, key=kf, reverse=True)
    st.caption(f"{res['week']} 週：符合大戶增幅門檻 {res['n_chip']} 檔，取前幾名做技術確認，目前顯示 {len(rows)} 檔。"
               "綜合分＝大戶籌碼分＋技術分×0.5；沒有技術資料的股票只計籌碼分。")
    if not rows:
        st.info("套用「站上月線／風報比」之後沒有股票符合，請放寬條件。")
        return

    view = pd.DataFrame([{"排名": i, "代號": r["code"], "名稱": r["name"], "產業": r["ind"],
                          "大戶Δ(pp)": r["big_d"], "千張Δ(pp)": r["mega_d"], "股東人數Δ": r["holders_d"], "連買週數": r["streak"],
                          "籌碼分": r["chip"], "技術分": r["tech"], "綜合分": r["comp"], "現價": r["price"],
                          "近端停損": r["stop"], "第一停利": r["t1"], "風報比": r["rr"], "標籤": r["tags"]}
                         for i, r in enumerate(rows, 1)])
    st.dataframe(view.round(2), hide_index=True, **STRETCH)
    st.download_button("⬇️ 匯出成 CSV", data=view.to_csv(index=False).encode("utf-8-sig"), file_name="big_holder_picks.csv", mime="text/csv", key="pk_dl")

    st.markdown("#### 前 10 名的入選理由與風險")
    for i, r in enumerate(rows[:10], 1):
        with st.expander(f"#{i}　{r['name']}（{r['code']}）　綜合 {r['comp']}　籌碼 {r['chip']}　技術 {r['tech'] if r['tech'] is not None else '—'}"):
            x1, x2 = st.columns(2)
            with x1:
                st.markdown("**✅ 籌碼面理由**")
                for t in r["reasons"]:
                    st.markdown(f"- {t}")
            with x2:
                st.markdown("**⚠️ 籌碼面風險**")
                for t in (r["risks"] or ["—"]):
                    st.markdown(f"- {t}")
            if r["price"] is not None:
                st.caption(f"現價 {r['price']:.2f}　·　近端停損 {r['stop']:.2f}　·　第一停利 {r['t1']:.2f}　·　風報比 " +
                           (f"1 : {r['rr']:.1f}" if r["rr"] is not None else "—") + "　·　" + ("站上月線" if r["above_ma"] else "在月線之下"))
    st.warning("⚠️ 大戶持股比例增加不等於會漲：集保資料每週才更新、看不出是誰在買，而且公布時已經是過去式。"
               "請先到「🏆 成績單」分頁看這套籌碼訊號在歷史上到底有沒有贏過大盤與賣組；成績單週數很少時，勝負多半是運氣。"
               "本頁是整理資訊的工具，不構成投資建議。")


'''

OLD_TABS = 't_inc, t_dec, t_swap, t_score, t_info = st.tabs(["📈 週增 TOP", "📉 週減 TOP", "🔄 大戶換手", "🏆 成績單", "ℹ️ 說明與資料狀態"])'
NEW_TABS = 't_inc, t_dec, t_swap, t_score, t_pick, t_info = st.tabs(["📈 週增 TOP", "📉 週減 TOP", "🔄 大戶換手", "🏆 成績單", "🎯 大戶選股", "ℹ️ 說明與資料狀態"])'
OLD_TINFO = '    with t_info:\n        st.markdown("#### 已存資料")'
NEW_TINFO = '    with t_pick:\n        render_big_holder_picks(wk, directory, demo, sel)\n\n' + OLD_TINFO


# ----------------------------------------------------------------------
class Skip(Exception):
    pass


def block(text, pattern, new, label):
    m = list(re.finditer(pattern, text, flags=re.S))
    if len(m) != 1:
        raise Skip(f"{label}：找不到唯一的區塊（找到 {len(m)} 處）")
    return text[:m[0].start()] + new + text[m[0].end():]


def once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise Skip(f"{label}：找不到唯一的片段（找到 {n} 處）")
    return text.replace(old, new)


def main():
    if not os.path.exists(APP):
        sys.exit(f"❌ 找不到 {APP}。請把這支腳本放在 app.py 所在的資料夾。")
    with open(APP, "r", encoding="utf-8") as f:
        orig = f.read()
    app = orig
    done, skipped = [], []
    ok = {}

    def step(key, title, fn):
        nonlocal app
        try:
            app = fn(app)
            ok[key] = True
            done.append(title)
        except Skip as e:
            ok[key] = False
            skipped.append(f"{title} → {e}")

    def s1(t):
        if "def vector_score" in t:
            raise Skip("已經套用過")
        return block(t, r"@st\.cache_data\(ttl=900, show_spinner=False\)\ndef backtest_score_system\(df\):.*?(?=def walk_forward_bucket_stats)",
                     HELPERS_AND_BACKTEST, "backtest_score_system")

    def s2(t):
        if not ok.get("1") and "def vector_score" not in t:
            raise Skip("需要第 1 步先成功")
        if "scores = vector_score(df).values\n    n = len(df)" in t:
            raise Skip("已經套用過")
        return block(t, r"@st\.cache_data\(ttl=900, show_spinner=False\)\ndef simulate_strategy\(.*?(?=def compute_backtest_metrics\()",
                     NEW_SIMULATE, "simulate_strategy")

    def s3(t):
        if NEW_CCI in t:
            raise Skip("已經套用過")
        return once(t, OLD_CCI, NEW_CCI, "CCI")

    def s4(t):
        if "def _one(tk):" in t:
            raise Skip("已經套用過")
        if not ok.get("1") and "def load_price_only" not in t:
            raise Skip("需要第 1 步先成功")
        if "def historical_horizon_stats(df, bucket" not in t:
            raise Skip("需要先成功執行 apply_patches.py（修改 4）")
        return block(t, r"def scan_candidates\(.*?(?=@st\.cache_data\(ttl=900, show_spinner=False\)\ndef get_market_direction)",
                     NEW_SCAN, "scan_candidates")

    def s5(t):
        if "import wanglai_picks as wp" in t:
            raise Skip("已經套用過")
        return once(t, "except Exception:\n    wl = None\n", "except Exception:\n    wl = None\n" + WP_IMPORT, "wanglai_data 匯入區")

    def s6(t):
        if "def render_big_holder_picks" in t:
            raise Skip("已經套用過")
        if not ok.get("1") and "def load_price_only" not in t:
            raise Skip("需要第 1 步先成功")
        for old, label in ((OLD_TABS, "大戶籌碼頁的分頁列"), (OLD_TINFO, "說明分頁"), ("def render_wanglai_page():", "render_wanglai_page")):
            once(t, old, "", label)          # 先全部確認找得到，再動手
        t = once(t, OLD_TABS, NEW_TABS, "大戶籌碼頁的分頁列")
        t = once(t, OLD_TINFO, NEW_TINFO, "說明分頁")
        return once(t, "def render_wanglai_page():", PICKS_UI + "def render_wanglai_page():", "render_wanglai_page")

    step("1", "1. 向量化評分與回測（backtest_score_system）", s1)
    step("2", "2. 模擬進出場改用預算分數（simulate_strategy）", s2)
    step("3", "3. CCI 計算加速", s3)
    step("4", "4. 平行掃描＋先價量後基本面（scan_candidates）", s4)
    step("5", "5. 載入 wanglai_picks 模組", s5)
    step("6", "6. 新增「🎯 大戶選股」分頁", s6)

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)

    if app != orig:
        bak = APP + ".bak2"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    if not os.path.exists(os.path.join(HERE, "wanglai_picks.py")):
        print("⚠️ 資料夾裡沒有 wanglai_picks.py，大戶選股分頁會顯示找不到模組。")


if __name__ == "__main__":
    main()
