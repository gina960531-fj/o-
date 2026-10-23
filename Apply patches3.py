# -*- coding: utf-8 -*-
"""
第三批：功能擴充
  1. 首頁：明日大盤走勢預測（0050 代理＋歷史勝率＋總經傾向）
  2. 投資組合管理：資金平衡診斷與「明日買進推薦」
  3. 📊 ETF 專區
  5. 📰 盤前必讀
（第 4 項「模擬自動交易」程式本來就有，不需要修補。）

用法：和 app.py、portfolio_balance.py、etf_data.py、premarket.py 放同一個資料夾，執行  python apply_patches3.py
每一步獨立，找不到對應位置的會「略過並說明」；有任何修改才寫檔（先備份成 app.py.bak3）。
建議先成功執行 apply_patches.py 與 apply_patches2.py（第 2 項的掃描會用到平行掃描版 scan_candidates）。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))

IMPORTS = '''
# 功能擴充模組（缺少時，只有對應的頁面／區塊會顯示提示）
try:
    import portfolio_balance as pbal
except Exception:
    pbal = None
try:
    import etf_data as etfd
except Exception:
    etfd = None
try:
    import premarket as pmk
except Exception:
    pmk = None
'''

# ======================================================================
# 共用小工具＋首頁「明日大盤走勢預測」
# ======================================================================
FORECAST_UI = r'''# ==========================================
# 功能擴充：明日大盤走勢預測／資金平衡推薦／ETF 專區／盤前必讀
# ==========================================
def _new_pool(n=6):
    fn = globals().get("_st_thread_pool")
    return fn(n) if fn else ThreadPoolExecutor(max_workers=n)

def _jump(mode):
    st.session_state["_pending_app_mode"] = mode
    st.rerun()

@st.cache_data(ttl=900, show_spinner=False)
def get_market_forecast(symbol="0050.TW"):
    """大盤隔日預測：個股用的同一套評分與回測，套用在 0050（大盤代理）上，並附上分期檢驗。"""
    info, df, _ = load_stock_data(symbol)
    if df is None or df.empty or len(df) < 40:
        return None
    d = compute_indicators(df)
    latest, prev = d.iloc[-1], d.iloc[-2]
    k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
    pattern_msgs, _ = detect_advanced_patterns(d.tail(150))
    bt = backtest_score_system(d)
    direction, action, buy_price, _r, color, score, bucket = predict_next_day(latest, prev, k_name, pattern_msgs, bt)
    wr = n = None
    if bt is not None and not bt.empty and bucket in bt.index:
        wr, n = float(bt.loc[bucket, '上漲機率(%)']), int(bt.loc[bucket, '樣本數'])
    s1, s2, l1, l2 = walk_forward_bucket_stats(d)
    prev_close = float(prev['Close'])
    return dict(symbol=symbol, asof=str(d.index[-1].date()), price=float(latest['Close']),
                chg_pct=(float(latest['Close']) / prev_close - 1) * 100 if prev_close else 0.0,
                direction=direction, action=action, score=score, bucket=bucket, wr=wr, n=n,
                stats=bt, first=s1, second=s2, labels=(l1, l2))

def render_market_forecast(tone=0):
    st.markdown("#### 🔮 明日大盤走勢預測（以 0050 為代理）")
    fc = get_market_forecast("0050.TW")
    if not fc:
        st.info("大盤預測資料暫時抓不到。")
        return
    score, wr, n = fc["score"], fc["wr"], fc["n"]
    tech = 1 if score >= 40 else (-1 if score <= -30 else 0)
    macro = 1 if tone >= 2 else (-1 if tone <= -2 else 0)
    if tech > 0 and macro > 0:
        call, lvl = "多方共振", "green"
    elif tech < 0 and macro < 0:
        call, lvl = "空方共振", "red"
    elif tech * macro == -1:
        call, lvl = "訊號分歧", "yellow"
    elif tech > 0 or macro > 0:
        call, lvl = "偏多（單一訊號）", "green"
    elif tech < 0 or macro < 0:
        call, lvl = "偏空（單一訊號）", "red"
    else:
        call, lvl = "中性", "gray"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("0050 技術面", fc["direction"], f"分數 {score}", delta_color="off")
    c2.metric("隔日上漲機率", f"{wr:.1f}%" if wr is not None else "—", f"下跌機率 {100 - wr:.1f}%" if wr is not None else None, delta_color="off")
    c3.metric("歷史相似樣本", f"N = {n}" if n else "—", help="過去 0050 分數落在同一區間的交易日數")
    with c4:
        st.markdown("**綜合研判**（技術面＋隔夜總經）")
        st.markdown(pill(call, lvl), unsafe_allow_html=True)
    st.caption(f"資料日期 {fc['asof']}　·　0050 收 {fc['price']:.2f}（{fc['chg_pct']:+.2f}%）　·　信心：{confidence_label(n)}")
    verdict = discrimination_verdict(fc["stats"])
    if verdict:
        {"warning": st.warning, "info": st.info, "success": st.success}[verdict[0]](verdict[1])
    with st.expander("看歷史統計與前後半段是否一致"):
        if fc["stats"] is not None and not fc["stats"].empty:
            s = fc["stats"].copy()
            s['平均隔日報酬(%)'] = s['平均隔日報酬(%)'].round(2)
            s['上漲機率(%)'] = s['上漲機率(%)'].round(1)
            st.dataframe(s, **STRETCH)
        cc1, cc2 = st.columns(2)
        for col, s_, lab in ((cc1, fc["first"], fc["labels"][0]), (cc2, fc["second"], fc["labels"][1])):
            with col:
                st.markdown(f"**{lab}**")
                if s_ is not None and not s_.empty:
                    x = s_.copy()
                    x['平均隔日報酬(%)'] = x['平均隔日報酬(%)'].round(2)
                    x['上漲機率(%)'] = x['上漲機率(%)'].round(1)
                    st.dataframe(x, **STRETCH)
                else:
                    st.caption("樣本不足")
    st.caption("⚠️ 這是規則式試算：機率是『過去同分數區間隔日上漲的比例』，不是對明天的保證；綜合研判只是把技術分數與隔夜總經方向（費半、VIX、匯率）放在一起看，不是預測模型。")
    if st.button("📰 開盤前完整情報 → 盤前必讀", key="mf_go_premarket"):
        _jump("📰 盤前必讀")

'''

# ======================================================================
# 投資組合：資金平衡與明日買進推薦
# ======================================================================
BALANCE_UI = r'''def render_portfolio_balance(rows, cash_on_hand, total_capital, total_mv, directory):
    st.markdown("#### ⚖️ 資金平衡與明日買進推薦")
    if pbal is None:
        st.error("找不到 portfolio_balance.py。請把它和 app.py 放在同一個資料夾，再重新整理。")
        return
    st.caption("先診斷目前的產業集中度、風格與現金水位，再從「每日候選股」的評分結果挑出能平衡部位的標的。門檻都可以調整，推薦只是規則式試算。")
    with st.container(border=True):
        a1, a2, a3, a4 = st.columns(4)
        max_ind = a1.slider("單一產業上限 %", 20, 80, 40, 5, key="pb_max_ind")
        max_single = a2.slider("新買單檔上限 %（占總資金）", 5, 40, 15, 5, key="pb_max_single")
        risk_pct = a3.slider("單筆風險 %（占總資金）", 0.5, 3.0, 1.0, 0.5, key="pb_risk")
        base_cash = a4.slider("目標現金水位 %", 0, 50, 15, 5, key="pb_cash")
        b1, b2, b3 = st.columns([1.4, 1.6, 1.4])
        style_pref = b1.radio("配置偏好", ["平衡", "偏防禦", "偏動能"], horizontal=True, key="pb_style")
        pool_choice = b2.radio("候選池", ["🕒 自動觀察清單", "🚀 全市場流動性池"], horizontal=True, key="pb_pool")
        pool_size = b3.slider("流動性池大小", 30, 200, 80, 10, key="pb_pool_size") if pool_choice.startswith("🚀") else None

    flags = get_macro_risk_flags()
    tgt_cash = pbal.target_cash_pct(base_cash, flags)
    diag, issues = pbal.snapshot(rows, cash_on_hand, total_capital, max_industry_pct=max_ind, max_single_pct=40.0, target_cash_pct=tgt_cash)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("現金水位", f"{diag['cash_pct']:.0f}%" if cash_on_hand > 0 else "未填", f"目標 {tgt_cash:.0f}%", delta_color="off")
    k2.metric("最大產業", f"{diag['top_ind']} {diag['ind_pct'][diag['top_ind']]:.0f}%" if diag['top_ind'] else "—")
    sp = diag["style_pct"]
    k3.metric("防禦／分散型", f"{sp.get('防禦型', 0) + sp.get('分散型', 0):.0f}%")
    k4.metric("動能型", f"{sp.get('動能型', 0):.0f}%")
    if flags:
        st.warning("📡 總經雷達目前有風險訊號（" + "、".join(flags) + f"），目標現金水位已自動上調到 {tgt_cash:.0f}%。")
    if cash_on_hand <= 0:
        st.info("你還沒在上方「現金水位設定」填入可用現金，現金水位與可動用資金無法計算；也可以直接在下面輸入本次可動用資金。")
    for lvl, txt in issues:
        {"error": st.error, "warning": st.warning, "info": st.info}[lvl](txt)
    for t in pbal.trim_suggestions(rows, total_capital, max_ind):
        st.markdown(f"- **減碼參考**：「{t['industry']}」{t['pct']:.0f}% → 降到 {max_ind}% 約需減碼 ${t['trim_amt']:,.0f}，可優先檢視 {t['biggest']}。")

    capital_base = total_capital if total_capital > 0 else total_mv
    default_deploy = max(0.0, cash_on_hand - tgt_cash / 100.0 * capital_base) if cash_on_hand > 0 else 0.0
    deploy = st.number_input("本次可動用資金（TWD）", min_value=0, value=int(default_deploy), step=10000, key=f"pb_deploy_{int(default_deploy)}",
                             help="預設＝現金扣掉目標現金水位後的餘額，可自行修改。")
    if st.button("🎯 產生明日買進建議", type="primary", key="pb_run"):
        if deploy <= 0:
            st.session_state["pb_cands"] = None
            st.warning("可動用資金是 0，不產生建議。")
        else:
            pool = get_watchlist() or list(INDUSTRY_MAP.keys())
            if pool_choice.startswith("🚀"):
                pool, ok = build_smart_pool(directory, size=pool_size)
                if not ok:
                    st.warning("全市場成交量排行抓不到，已改用內建常用清單。")
            with st.spinner(f"掃描 {len(pool)} 檔候選股中…"):
                streak_map = get_institutional_streaks([t.split(".")[0] for t in pool], days=5) or {}
                cands = scan_candidates(pool, streak_map, directory=directory)
            st.session_state["pb_cands"] = dict(cands=cands, n_pool=len(pool))

    res = st.session_state.get("pb_cands")
    if res:
        recs, left = pbal.recommend(rows, res["cands"], directory, deploy, capital_base, max_industry_pct=max_ind,
                                    max_single_pct=max_single, risk_pct=risk_pct, n=5, style_pref=style_pref)
        st.caption(f"候選池 {res['n_pool']} 檔，成功分析 {len(res['cands'])} 檔；已排除已持有、風報比不足、會讓產業超過上限的標的。")
        if recs.empty:
            st.info("沒有符合條件的建議：可能是候選都已持有、產業已達上限、風報比不足，或可動用資金太少。可以放寬上限或換候選池。")
        else:
            view = pd.DataFrame({"代號": recs["code"], "名稱": recs["name"], "產業": recs["industry"], "風格": recs["style"],
                                 "綜合分": recs["composite"], "參考買價": recs["buy_price"], "近端停損": recs["stop"], "第一停利": recs["target1"],
                                 "風報比": recs["rr"], "建議股數": recs["shares"], "金額": recs["amount"], "最大虧損": recs["risk_amt"],
                                 "買後產業占比%": recs["post_ind_pct"], "為什麼": recs["why"]})
            st.dataframe(view.round(2), hide_index=True, **STRETCH)
            st.caption(f"合計投入約 ${recs['amount'].sum():,.0f}，剩餘可動用資金 ${left:,.0f}；若全部觸及停損，合計最大虧損約 ${recs['risk_amt'].sum():,.0f}（{recs['risk_amt'].sum() / capital_base * 100:.1f}% 總資金）。")
            st.download_button("⬇️ 匯出建議 CSV", data=view.to_csv(index=False).encode("utf-8-sig"), file_name="buy_suggestions.csv", mime="text/csv", key="pb_dl")
    st.caption("⚠️ 建議股數＝（總資金×單筆風險%）÷（買價−停損），再受單檔上限、產業剩餘額度、可動用現金三重封頂；未計手續費與稅。"
               "風格與產業分類是粗略規則，推薦不是買賣建議，下單前請自行確認最新報價與基本面。")

'''

# ======================================================================
# 盤前必讀
# ======================================================================
PREMARKET_UI = r'''@st.cache_data(ttl=300, show_spinner=False)
def _pm_fetch():
    syms = [s for s, _ in pmk.SYMBOLS]

    def one(s):
        r = get_macro_series(s)
        if not r:
            return s, None
        ser = r["series"]
        d5 = (ser.iloc[-1] / ser.iloc[-6] - 1) * 100 if len(ser) > 5 else None
        bp = (ser.iloc[-1] - ser.iloc[-2]) * 100 if (s == "^TNX" and ser.iloc[-1] < 25) else None
        return s, dict(value=float(r["value"]), chg_pct=float(r["chg_pct"]), d5=d5, bp=bp, asof=ser.index[-1])

    with _new_pool(6) as ex:
        return dict(ex.map(one, syms))

PM_EVENTS_FILE = os.path.join(DATA_DIR, "premarket_events.txt")

def render_premarket_page():
    st.title("📰 盤前必讀")
    st.caption("開盤前 10 分鐘快速掌握全貌：隔夜美股與期貨、總經風險、新聞與昨日盤面熱點。全部是自動抓取＋規則整理，請點進原文確認重要消息。")
    if pmk is None:
        st.error("找不到 premarket.py。請把它和 app.py 放在同一個資料夾，再重新整理。")
        return
    directory, _ = get_directory()
    quotes = _pm_fetch()
    summ = pmk.build_summary(quotes)
    gs = quotes.get("^GSPC")
    asof = gs["asof"].strftime("%m/%d") if gs and gs.get("asof") is not None else "—"
    st.caption(f"美股最近交易日：{asof}　·　現在台北時間 {pd.Timestamp.now(tz='Asia/Taipei').strftime('%m/%d %H:%M')}")

    st.markdown("#### 1️⃣ 一句話總結")
    box = {"success": st.success, "error": st.error, "warning": st.warning, "info": st.info}[summ["level"]]
    box(f"**隔夜氣氛：{summ['label']}**（規則加總分 {summ['score']:+.0f}，使用 {summ['used']} 項指標）")
    if summ["bullets"]:
        for pts, text in summ["bullets"]:
            st.markdown(f"- {'🟢' if pts > 0 else '🔴'} {text}")
    else:
        st.caption("目前沒有達到門檻的明顯多空訊號。")
    if summ["missing"]:
        st.caption("抓不到的項目：" + "、".join(summ["missing"]))
    fc = get_market_forecast("0050.TW")
    if fc:
        st.markdown(f"**0050 技術面**：{fc['direction']}（分數 {fc['score']}），歷史相似情境隔日上漲機率 "
                    + (f"{fc['wr']:.0f}%（N={fc['n']}）" if fc['wr'] is not None else "樣本不足") + "。")
    st.caption("這只是把幾項隔夜指標按規則加減分，不是預測；同分不代表開盤一定同方向。")

    st.markdown("#### 2️⃣ 隔夜行情一覽")
    rows = []
    for sym, name in pmk.SYMBOLS:
        q = quotes.get(sym)
        if not q:
            rows.append({"項目": name, "最新": None, "漲跌%": None, "近5日%": None})
            continue
        rows.append({"項目": name, "最新": q["value"], "漲跌%": q["chg_pct"], "近5日%": q["d5"]})
    qdf = pd.DataFrame(rows)
    try:
        sty = qdf.style.format({"最新": "{:,.2f}", "漲跌%": "{:+.2f}", "近5日%": "{:+.2f}"}, na_rep="—")
        color = lambda v: ("color:#c0504d;font-weight:600" if v > 0 else "color:#3f8f66;font-weight:600" if v < 0 else "") if pd.notna(v) else ""
        st.dataframe((getattr(sty, "map", None) or sty.applymap)(color, subset=["漲跌%", "近5日%"]), hide_index=True, **STRETCH)
    except Exception:
        st.dataframe(qdf.round(2), hide_index=True, **STRETCH)
    st.caption("紅漲綠跌（台股慣例）。期貨與 ADR 的報價時間可能不同步；VIX 與殖利率的「漲」代表恐慌／利率上升，不是好消息。")

    st.markdown("#### 3️⃣ 今日關鍵風險提醒")
    risks = list(summ["risks"])
    try:
        tx = get_taifex_foreign_tx()
        if tx and tx.get("net") is not None and tx["net"] < 0:
            risks.append(f"台指期外資淨空單 {abs(tx['net']):,} 口，短線籌碼偏空。")
    except Exception:
        pass
    if risks:
        for r in risks:
            st.error("⚠️ " + r)
    else:
        st.success("目前沒有觸發任何風險門檻。這不代表沒有風險，只是沒有達到規則設定的警戒線。")

    st.markdown("#### 4️⃣ 國際總經與財經新聞")
    items = get_news_items()
    picks = pmk.pick_macro_news(items or [], 8)
    if picks:
        for it in picks:
            tag = classify_news(it["title"], directory)
            icon = "🟢" if tag["impact"] == "正面" else ("🔴" if tag["impact"] == "負面" else "⚪")
            st.markdown(f"{icon} [{it['title']}]({it['link']})　<span style='color:#7b8794;font-size:0.85em'>{' '.join(tag['categories'])}</span>", unsafe_allow_html=True)
        st.caption("以關鍵字挑出和開盤有關的標題，不是語意分析，請以原文為準。")
    elif items:
        st.info("今天抓到的新聞裡沒有符合關鍵字的標題。")
    else:
        st.info("新聞來源暫時抓不到（RSS 可能改版或失效）。")
    default_events = ""
    if os.path.exists(PM_EVENTS_FILE):
        try:
            with open(PM_EVENTS_FILE, "r", encoding="utf-8") as f:
                default_events = f.read()
        except Exception:
            pass
    ev = st.text_area("📅 本週重大事件備忘（自己維護：例如 FOMC 利率決議日、CPI／非農公布日、重要財報日）", value=default_events, height=100, key="pm_events",
                      help="系統不會自動抓經濟行事曆，請從官方行事曆自行填入。")
    if st.button("💾 儲存備忘", key="pm_save_events"):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(PM_EVENTS_FILE, "w", encoding="utf-8") as f:
                f.write(ev)
            st.success("已儲存。")
        except Exception:
            st.error("儲存失敗，可能是檔案系統無法寫入。")
    if ev.strip():
        st.info("**你記錄的本週事件**\n\n" + ev.replace("\n", "\n\n"))

    st.markdown("#### 5️⃣ 昨日盤面熱點")
    if st.button("🔥 載入昨日族群資金與漲跌", key="pm_heat"):
        with st.spinner("抓取成交量前 100 大個股報價中…"):
            pool, _ok = heatmap_pool(directory, 100)
            tk = tuple(c + directory.get(c, {}).get("suffix", ".TW") for c in pool)
            hq = fetch_heat_quotes(tk)
        if hq is None or hq.empty or len(hq) < 5:
            st.session_state["pm_heat_res"] = None
            st.warning("報價抓不到，暫時無法顯示盤面熱點。")
        else:
            st.session_state["pm_heat_res"] = build_sector_table(hq, directory)
    hres = st.session_state.get("pm_heat_res")
    if hres:
        q_, sec_ = hres
        big = sec_[sec_["share"] >= 3]
        pool_s = big if not big.empty else sec_
        best, worst, top = pool_s.sort_values("chg", ascending=False).iloc[0], pool_s.sort_values("chg").iloc[0], sec_.iloc[0]
        st.markdown(f"**成交最集中**：{top['sector']}（占 {top['share']:.0f}%，{top['chg']:+.2f}%）　**最強**：{best['sector']}（{best['chg']:+.2f}%）　**最弱**：{worst['sector']}（{worst['chg']:+.2f}%）")
        h1, h2 = st.columns(2)
        with h1:
            st.markdown("**🟢 領漲個股**")
            for _, r in q_.sort_values("chg", ascending=False).head(5).iterrows():
                st.markdown(f"- {r['name']}（{r['code']}）{r['chg']:+.2f}%　{r['sector']}")
        with h2:
            st.markdown("**🔴 領跌個股**")
            for _, r in q_.sort_values("chg").head(5).iterrows():
                st.markdown(f"- {r['name']}（{r['code']}）{r['chg']:+.2f}%　{r['sector']}")
        st.caption("成交值是買賣雙方總量，不等於資金淨流入；只涵蓋成交量前 100 大個股。")

    st.markdown("#### 6️⃣ 開盤前 10 分鐘檢查清單")
    st.markdown(
        "1. 看上面的「一句話總結」與風險提醒，決定今天偏積極還是偏保守。\n"
        "2. 到「💼 投資組合管理」確認持股離停損價還有多遠、有沒有已觸價的部位。\n"
        "3. 到「⭐ 每日候選股」或投資組合頁的「明日買進推薦」，只挑風報比與部位大小都合理的標的。\n"
        "4. 若風險提醒有 2 項以上被觸發，考慮降低單筆風險或把部分停損收緊。")
    c1, c2, c3 = st.columns(3)
    if c1.button("💼 檢查我的持股", key="pm_to_pf", **STRETCH):
        _jump("💼 投資組合管理")
    if c2.button("⭐ 看每日候選股", key="pm_to_cand", **STRETCH):
        _jump("⭐ 每日候選股")
    if c3.button("📡 完整總經雷達", key="pm_to_macro", **STRETCH):
        _jump("📡 總經雷達")
    st.caption("⚠️ 以上為自動整理的參考資訊與規則式提醒，不是預測也不構成投資建議；資料來自 Yahoo Finance 與公開新聞來源，可能有延遲或缺漏。")

'''

# ======================================================================
# ETF 專區
# ======================================================================
ETF_UI = r'''def _etf_tech_check(codes, directory):
    loader = globals().get("load_price_only")

    def one(code):
        suf = directory.get(code, {}).get("suffix", ".TW")
        df = None
        for sfx in (suf, ".TWO" if suf == ".TW" else ".TW"):
            df = loader(code + sfx) if loader else load_stock_data(code + sfx)[1]
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
            return dict(score=sc, price=float(latest['Close']), above_ma=bool(latest['Close'] > latest['MA20']), rr=lv['rr'], stop=lv['near_stop'])
        except Exception:
            return None

    with _new_pool(6) as ex:
        return list(ex.map(one, codes))

def render_etf_page():
    st.title("📊 ETF 專區")
    st.caption("了解熱門 ETF 的選股邏輯、比較績效，並匯入持股明細追蹤權重變化，作為量化選股的參考。")
    if etfd is None:
        st.error("找不到 etf_data.py。請把它和 app.py 放在同一個資料夾，再重新整理。")
        return
    directory, _ = get_directory()
    etfs = etfd.all_etfs(DATA_DIR)
    t1, t2, t3, t4 = st.tabs(["📖 ETF 導覽", "📈 績效比較", "🔍 持股透視", "➕ 自訂 ETF"])

    with t1:
        code = st.selectbox("選擇 ETF", list(etfs), format_func=lambda c: f"{c}　{etfs[c]['name']}", key="etf_pick")
        e = etfs[code]
        st.markdown(f"### {code}　{e['name']}")
        st.caption(f"{e['issuer']}　·　{e['kind']}")
        st.info(e["summary"])
        st.markdown("**選股／加權邏輯**")
        st.write(e["logic"])
        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**✅ 特色**")
            for x in e["pros"] or ["—"]:
                st.markdown(f"- {x}")
        with p2:
            st.markdown("**⚠️ 要留意**")
            for x in e["risks"] or ["—"]:
                st.markdown(f"- {x}")
        if e["who"]:
            st.markdown(f"**適合誰**：{e['who']}")
        st.caption("資料狀態：" + e["checked"])
        with st.expander("被動式 vs 主動式 ETF：『經理人策略』指的是什麼？"):
            st.markdown(etfd.PASSIVE_VS_ACTIVE)
        st.warning("⚠️ 指數規則與持股會調整（例如指數改版、成分股大幅換血），這裡只整理結構性說明，不含最新持股與權重。投資前請以投信公開說明書與官網最新資料為準。")

    with t2:
        sel = st.multiselect("選擇要比較的 ETF", list(etfs), default=[c for c in ("0050", "0056", "00878", "00929") if c in etfs],
                             format_func=lambda c: f"{c} {etfs[c]['name']}", key="etf_cmp")
        if not sel:
            st.info("請至少選一檔。")
        else:
            with st.spinner("抓取價格中…"):
                closes = get_peer_closes(tuple(sel))
            if closes is None or closes.empty:
                st.warning("抓不到價格資料。")
            else:
                rows = []
                for c in closes.columns:
                    s = closes[c].dropna()
                    if len(s) < 25:
                        continue
                    dd = (s / s.cummax() - 1).min() * 100
                    rows.append({"ETF": f"{c} {etfs.get(c, {}).get('name', '')}", "近1月%": _ret(s, 20) * 100, "近3月%": _ret(s, 60) * 100,
                                 "近6月%": _ret(s, 120) * 100, "近1年%": (s.iloc[-1] / s.iloc[0] - 1) * 100,
                                 "年化波動%": s.pct_change().std() * (252 ** 0.5) * 100, "期間最大回撤%": dd})
                if rows:
                    st.dataframe(pd.DataFrame(rows).round(1), hide_index=True, **STRETCH)
                fig = go.Figure()
                for c in closes.columns:
                    s = closes[c].dropna()
                    if len(s) >= 5:
                        fig.add_trace(go.Scatter(x=s.index, y=s / s.iloc[0] * 100, mode="lines", name=f"{c} {etfs.get(c, {}).get('name', '')}"))
                fig.update_layout(height=360, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="起點 = 100", legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig, **STRETCH, key="etf_cmp_chart")
                st.caption("價格來自 Yahoo Finance，是否含股利還原依其資料設定而定，高股息型的報酬可能被低估或高估；僅供相對比較，過去表現不代表未來。")

    with t3:
        hc = st.selectbox("選擇 ETF", list(etfs), format_func=lambda c: f"{c}　{etfs[c]['name']}", key="etf_hold_pick")
        with st.expander("📥 匯入／更新持股明細", expanded=not etfd.list_snapshots(DATA_DIR, hc)):
            st.caption("到投信官網下載該 ETF 的持股明細（Excel／CSV），貼上或上傳。需要有「代號」與「權重」欄位。每匯入一份就存成一個日期快照，累積 2 份以上就能比較權重變化。")
            if st.button("嘗試從 Yahoo 抓取（台股 ETF 常常抓不到）", key="etf_yf"):
                got = etfd.fetch_yf_holdings(hc)
                if got is None:
                    st.warning("Yahoo 沒有這檔的持股資料，請改用下方貼上或上傳。")
                else:
                    etfd.save_snapshot(DATA_DIR, hc, pd.Timestamp.now().strftime("%Y-%m-%d"), got)
                    st.success(f"已存入 {len(got)} 檔（僅前幾大持股，可能不完整）。")
                    st.rerun()
            snap_date = st.date_input("這份持股的資料日期", value=pd.Timestamp.now().date(), key="etf_snap_date")
            up = st.file_uploader("上傳 CSV", type=["csv"], key="etf_up")
            txt = st.text_area("或直接貼上（含標題列）", height=120, key="etf_paste")
            if st.button("儲存這份持股", type="primary", key="etf_save"):
                try:
                    if up is not None:
                        raw = up.getvalue()
                        try:
                            txt_in = raw.decode("utf-8-sig")
                        except UnicodeDecodeError:
                            txt_in = raw.decode("big5", errors="replace")
                    else:
                        txt_in = txt
                    parsed, notes = etfd.parse_holdings(txt_in)
                    etfd.save_snapshot(DATA_DIR, hc, snap_date.strftime("%Y-%m-%d"), parsed)
                    st.success(f"已儲存 {len(parsed)} 檔持股（{snap_date}）。")
                    for n_ in notes:
                        st.warning(n_)
                except Exception as ex_:
                    st.error(f"匯入失敗：{ex_}")
        snaps = etfd.list_snapshots(DATA_DIR, hc)
        if not snaps:
            st.info("還沒有這檔 ETF 的持股資料，請先匯入。")
        else:
            cur_date = st.selectbox("查看哪一天的持股", snaps[::-1], key="etf_snap_view")
            cur = etfd.load_snapshot(DATA_DIR, hc, cur_date)
            con = etfd.concentration(cur)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("持股檔數", f"{con['n']}")
            m2.metric("第一大持股", f"{con['top1']:.1f}%")
            m3.metric("前五大合計", f"{con['top5']:.1f}%")
            m4.metric("前十大合計", f"{con['top10']:.1f}%")
            mine = set()
            try:
                pf_ = load_portfolio()
                mine = set(pf_["代號"].astype(str)) if pf_ is not None and not pf_.empty else set()
            except Exception:
                pass
            view = cur.assign(產業=cur["code"].map(lambda c: directory.get(c, {}).get("ind", "")),
                              我持有=cur["code"].map(lambda c: "✔" if c in mine else "")).rename(columns={"code": "代號", "name": "名稱", "weight": "權重%"})
            st.dataframe(view.round(2), hide_index=True, **STRETCH, height=min(38 * (len(view) + 1), 520))
            ov = [c for c in cur["code"] if c in mine]
            if ov:
                st.caption("與你的投資組合重疊：" + "、".join(f"{directory.get(c, {}).get('name', c)}（{c}）" for c in ov))
            iw = etfd.industry_weights(cur, directory)
            st.markdown("**產業分布（依證交所產業別）**")
            st.bar_chart(iw)
            if len(snaps) >= 2:
                others = [s for s in snaps if s != cur_date]
                base_date = st.selectbox("和哪一天比較", others[::-1], key="etf_snap_cmp")
                dif = etfd.diff_holdings(cur, etfd.load_snapshot(DATA_DIR, hc, base_date))
                chg = dif[dif["status"] != "不變"]
                st.markdown(f"**{base_date} → {cur_date} 的持股變化**　新增 {int((dif.status == '新增').sum())}　剔除 {int((dif.status == '剔除').sum())}　"
                            f"增持 {int((dif.status == '增持').sum())}　減持 {int((dif.status == '減持').sum())}")
                if chg.empty:
                    st.caption("兩份持股沒有明顯差異。")
                else:
                    st.dataframe(chg.rename(columns={"code": "代號", "name": "名稱", "w_new": "新權重%", "w_old": "舊權重%", "delta": "變動pp", "status": "狀態"}).round(2),
                                 hide_index=True, **STRETCH)
                st.caption("權重變動小於 0.05 個百分點視為不變。權重變動也可能只是價格漲跌造成，不一定是經理人或指數主動調整。")
            nchk = st.slider("技術面體檢：前幾大持股", 5, 15, 10, key="etf_nchk")
            if st.button("🩺 替前幾大持股做技術面體檢", key="etf_chk"):
                tops = list(cur.head(nchk)["code"])
                with st.spinner("計算技術面中…"):
                    res = _etf_tech_check(tops, directory)
                rows = [{"代號": c, "名稱": directory.get(c, {}).get("name", ""), "權重%": float(cur.loc[cur.code == c, "weight"].iloc[0]),
                         "技術分": r["score"] if r else None, "站上月線": ("是" if r["above_ma"] else "否") if r else "—",
                         "風報比": r["rr"] if r else None} for c, r in zip(tops, res)]
                st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, **STRETCH)
                st.caption("用和個股分析相同的技術評分看權重最大的幾檔，只是『參考ETF在買什麼、這些標的現在強不強』，不構成建議。")

    with t4:
        st.caption("加入你自己關注的 ETF（包含主動式 ETF），之後就能匯入它的持股並追蹤調整。")
        with st.form("etf_custom_form"):
            f1, f2 = st.columns(2)
            ccode = f1.text_input("ETF 代號", placeholder="例如 00981A")
            cname = f2.text_input("名稱")
            f3, f4 = st.columns(2)
            cissuer = f3.text_input("發行投信")
            ckind = f4.selectbox("類型", ["主動式", "市值型（被動）", "高股息型（被動）", "主題型", "債券型", "其他"])
            csum = st.text_area("一句話策略說明")
            clogic = st.text_area("選股／調整邏輯（可貼上公開說明書重點）")
            if st.form_submit_button("儲存", type="primary"):
                if not ccode.strip() or not cname.strip():
                    st.warning("請至少填代號與名稱。")
                else:
                    etfd.save_custom(DATA_DIR, ccode.strip().upper(), dict(name=cname.strip(), issuer=cissuer.strip(), kind=ckind, summary=csum.strip(), logic=clogic.strip()))
                    st.success("已儲存，重新整理後會出現在上面的下拉選單。")
    st.caption("⚠️ ETF 資料僅供研究參考，不構成投資建議。持股明細與權重請以投信官網為準。")

'''

NAV_OLD = '("research", "📈 研究室",   ["📈 個股分析", "📡 總經雷達"]),'
NAV_NEW = '("research", "📈 研究室",   ["📰 盤前必讀", "📈 個股分析", "📡 總經雷達", "📊 ETF 專區"]),'
ROUTE_OLD = 'elif app_mode == "🤖 模擬自動交易":\n    render_sandbox_page()'
ROUTE_NEW = ('elif app_mode == "📰 盤前必讀":\n    render_premarket_page()\n\n'
             'elif app_mode == "📊 ETF 專區":\n    render_etf_page()\n\n' + ROUTE_OLD)
HOME_ANCHOR = 'if app_mode == "🏠 戰情室首頁":\n    st.title("🏠 戰情室首頁")'
HOME_HOOK_OLD = '    st.divider()\n    st.markdown("#### 📊 大盤與總經快照")'
HOME_HOOK_NEW = '    st.divider()\n    render_market_forecast(tone)\n\n' + HOME_HOOK_OLD
PF_OLD = '        exp_p1, exp_p2 = st.columns(2)\n        with exp_p1:\n            csv_pf = table_df.to_csv(index=False).encode("utf-8-sig")'
PF_NEW = '        render_portfolio_balance(rows, cash_on_hand, total_capital, total_mv, directory)\n\n' + PF_OLD
IMPORT_ANCHOR = "except Exception:\n    sbe = None\n"


class Skip(Exception):
    pass


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

    def s0(t):
        if "import portfolio_balance as pbal" in t:
            raise Skip("已經套用過")
        return once(t, IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORTS, "匯入區")

    def s1(t):
        if "def render_market_forecast" in t:
            raise Skip("已經套用過")
        if "import portfolio_balance as pbal" not in t:
            raise Skip("需要第 0 步先成功")
        once(t, HOME_ANCHOR, "", "首頁區塊")
        once(t, HOME_HOOK_OLD, "", "首頁『大盤與總經快照』位置")
        t = once(t, HOME_HOOK_OLD, HOME_HOOK_NEW, "首頁預測區塊")
        return once(t, HOME_ANCHOR, FORECAST_UI + HOME_ANCHOR, "首頁函式")

    def s2(t):
        if "def render_portfolio_balance" in t:
            raise Skip("已經套用過")
        if "def render_market_forecast" not in t:
            raise Skip("需要第 1 步先成功（共用工具函式）")
        once(t, PF_OLD, "", "投資組合頁位置")
        t = once(t, PF_OLD, PF_NEW, "投資組合頁區塊")
        return once(t, HOME_ANCHOR, BALANCE_UI + HOME_ANCHOR, "資金平衡函式")

    def s3(t):
        if "def render_premarket_page" in t:
            raise Skip("已經套用過")
        if "def render_market_forecast" not in t:
            raise Skip("需要第 1 步先成功（共用工具函式）")
        for old, label in ((NAV_OLD, "導覽列分組"), (ROUTE_OLD, "頁面路由")):
            once(t, old, "", label)
        t = once(t, NAV_OLD, NAV_NEW, "導覽列分組")
        t = once(t, ROUTE_OLD, ROUTE_NEW, "頁面路由")
        return once(t, HOME_ANCHOR, PREMARKET_UI + ETF_UI + HOME_ANCHOR, "盤前必讀與 ETF 函式")

    step("0", "0. 載入三個新模組", s0)
    step("1", "1. 首頁：明日大盤走勢預測", s1)
    step("2", "2. 投資組合：資金平衡與明日買進推薦", s2)
    step("3", "3＋5. 新增「📰 盤前必讀」與「📊 ETF 專區」頁面", s3)

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)
    if app != orig:
        bak = APP + ".bak3"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    for m in ("portfolio_balance.py", "etf_data.py", "premarket.py"):
        if not os.path.exists(os.path.join(HERE, m)):
            print(f"⚠️ 資料夾裡沒有 {m}，對應功能會顯示找不到模組。")


if __name__ == "__main__":
    main()Apply patches3 · PY
