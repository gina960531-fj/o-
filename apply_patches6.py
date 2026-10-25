# -*- coding: utf-8 -*-
"""
第六批：
  1. 修正「模擬自動交易 → 交易紀錄」沒選篩選條件時的 KeyError（原程式的 bug）
  2. 官方每日收盤資料：上市、上櫃各自快取（一邊逾時另一邊照用；失敗 5 分鐘內不重試，避免拖慢頁面）
  3. 股票名單補上新上市 ETF（含主動式）與名單裡缺的個股，讓它們搜得到
  4. ETF 專區改版：新增「🧭 市場總覽」（列出所有上市上櫃 ETF，可一鍵加入追蹤），自訂 ETF 顯示價格與提示
  5. 新增「🔔 到價通知」頁面（操盤室）
用法：和 app.py、official_quotes.py、price_alerts.py 放同一個資料夾，執行  python apply_patches6.py
需要先成功套用 apply_patches3.py 與 apply_patches5.py。每一步獨立；有修改才寫檔（備份成 app.py.bak6）。
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))

# ---------------------------------------------------------------- 1. KeyError 修正
LOG_OLD = 'v = lg[(lg["策略"].isin(pick) if pick else True) & (lg["動作"].isin(acts) if acts else True)].iloc[::-1]'
LOG_NEW = ('v = lg[(lg["策略"].isin(pick) if pick else pd.Series(True, index=lg.index)) '
           '& (lg["動作"].isin(acts) if acts else pd.Series(True, index=lg.index))].iloc[::-1]')

# ---------------------------------------------------------------- 2. 官方資料：分來源快取
OFFICIAL_FUNCS = r'''@st.cache_resource
def _official_fail_log():
    return {}

@st.cache_data(ttl=1800, show_spinner=False)
def _official_src_cached(name):
    """單一來源（twse／tpex）的每日收盤行情。失敗或檔數太少就丟例外（不會被快取）。"""
    if oq is None:
        raise RuntimeError("official_quotes 模組不存在")
    rows = oq.fetch_source(name)
    if len(rows) < (200 if name == "twse" else 30):
        raise RuntimeError("官方資料檔數過少")
    return rows

def get_official_daily():
    """上市＋上櫃合併；任何一邊失敗就只用另一邊，失敗後 5 分鐘內不再重試。回傳 {ticker: row} 或 None。"""
    out, fails = {}, _official_fail_log()
    for name in ("twse", "tpex"):
        if time.time() - fails.get(name, 0) < 300:
            continue
        try:
            out.update(_official_src_cached(name))
        except Exception:
            fails[name] = time.time()
    return out or None

def get_official_liquidity():
    """{代號: 成交值}，用成交值排流動性（比成交股數更不會被低價股誤導）。"""
    off = get_official_daily()
    return oq.liquidity(off) if off else None

def _add_official_names(d):
    """用官方每日收盤行情補上名單裡缺的代號：新上市 ETF（代號 00 開頭）與其他缺漏個股。"""
    off = get_official_daily()
    if not off:
        return d
    for t, r in off.items():
        code = r["code"]
        if code not in d:
            d[code] = dict(name=r["name"] or code, ind="ETF" if code.startswith("00") else "其他", suffix=".TWO" if t.endswith(".TWO") else ".TW")
    return d

'''
OFFICIAL_PATTERN = r'@st\.cache_data\(ttl=600, show_spinner=False\)\ndef _official_cached\(\):.*?(?=def heatmap_pool\(directory, size\):)'
DIR_TRUE_OLD = "            return d, True\n"
DIR_TRUE_NEW = "            _add_official_names(d)\n            return d, True\n"
DIR_FALSE_OLD = "    return d, False\n"
DIR_FALSE_NEW = "    _add_official_names(d)\n    return d, False\n"

# ---------------------------------------------------------------- 4. ETF 專區（整頁取代）
ETF_PAGE = r'''def _guess_etf_kind(name):
    n = str(name)
    if "主動" in n:
        return "主動式"
    if any(k in n for k in ("高息", "高股息", "股息", "優息", "收益", "配息")):
        return "高股息型（被動）"
    if "債" in n:
        return "債券型"
    if any(k in n for k in ("半導體", "科技", "AI", "PCB", "電動車", "5G", "機器人", "太空", "ESG", "永續")):
        return "主題型"
    return "其他"

def render_etf_page():
    st.title("📊 ETF 專區")
    st.caption("了解熱門 ETF 的選股邏輯、查看全市場 ETF（含新上市與主動式）、比較績效，並匯入持股明細追蹤權重變化。")
    if etfd is None:
        st.error("找不到 etf_data.py。請把它和 app.py 放在同一個資料夾，再重新整理。")
        return
    directory, _ = get_directory()
    etfs = etfd.all_etfs(DATA_DIR)
    off = get_official_daily() or {}
    by_code = {r["code"]: r for r in off.values()}
    t0, t1, t2, t3, t4 = st.tabs(["🧭 市場總覽", "📖 ETF 導覽", "📈 績效比較", "🔍 持股透視", "➕ 自訂 ETF"])

    with t0:
        etf_rows = [r for r in off.values() if r["code"].startswith("00")]
        if not off:
            st.warning("官方每日行情暫時抓不到（證交所／櫃買），無法列出市場上的 ETF。稍後按 F5 重試。")
        else:
            has_tpex = any(t.endswith(".TWO") for t in off)
            if not has_tpex:
                st.warning("目前只抓到上市資料，上櫃 ETF 暫時不會顯示（櫃買來源逾時，5 分鐘後會自動重試）。")
            q = st.text_input("搜尋代號或名稱", key="etf_mkt_q", placeholder="例如 主動、半導體、00981")
            kinds = ["全部", "主動式", "高股息型（被動）", "債券型", "主題型", "其他"]
            kf = st.radio("類型（依名稱推測）", kinds, horizontal=True, key="etf_mkt_kind")
            df = pd.DataFrame([{"代號": r["code"], "名稱": r["name"], "市場": "上櫃" if r["ticker"].endswith(".TWO") else "上市",
                                "類型": _guess_etf_kind(r["name"]), "收盤": r["close"], "漲跌%": r["chg"], "成交值(億)": r["value"] / 1e8,
                                "已在追蹤": "✔" if r["code"] in etfs else ""} for r in etf_rows])
            if not df.empty:
                if q.strip():
                    df = df[df["代號"].str.contains(q.strip(), case=False) | df["名稱"].str.contains(q.strip(), case=False)]
                if kf != "全部":
                    df = df[df["類型"] == kf]
                df = df.sort_values("成交值(億)", ascending=False)
            asof = etf_rows[0]["asof"] if etf_rows else ""
            st.caption(f"資料日期 {asof}（官方每日收盤，不是即時報價）　·　共 {len(df)} 檔")
            st.dataframe(df.round(2), hide_index=True, **STRETCH, height=min(38 * (len(df) + 1), 560))
            addable = [c for c in df["代號"] if c not in etfs] if not df.empty else []
            pick = st.multiselect("加入我的 ETF 清單（之後可在導覽、績效比較、持股透視裡使用）", addable[:300],
                                  format_func=lambda c: f"{c} {by_code[c]['name']}" if c in by_code else c, key="etf_mkt_add")
            if st.button("➕ 加入追蹤", key="etf_mkt_add_btn") and pick:
                for c in pick:
                    etfd.save_custom(DATA_DIR, c, dict(name=by_code[c]["name"], issuer="", kind=_guess_etf_kind(by_code[c]["name"]), summary="", logic=""))
                st.success(f"已加入 {len(pick)} 檔。選股邏輯尚未填寫，可到「➕ 自訂 ETF」補上。")
                st.rerun()
            st.caption("類型是依名稱關鍵字推測，不一定準；名單來自證交所與櫃買每日收盤行情，所以新上市的 ETF（含主動式）在有成交後就會出現。")

    with t1:
        code = st.selectbox("選擇 ETF", list(etfs), format_func=lambda c: f"{c}　{etfs[c]['name']}", key="etf_pick")
        e = etfs[code]
        st.markdown(f"### {code}　{e['name']}")
        st.caption(f"{e['issuer'] or '發行投信未填'}　·　{e['kind']}")
        r = by_code.get(code)
        if r:
            m1, m2, m3 = st.columns(3)
            m1.metric("最近收盤", f"{r['close']:.2f}", f"{r['chg']:+.2f}%", delta_color="off")
            m2.metric("成交值", f"{r['value'] / 1e8:.1f} 億")
            m3.metric("資料日期", r["asof"])
        if e["summary"]:
            st.info(e["summary"])
        st.markdown("**選股／加權邏輯**")
        st.write(e["logic"] or "（尚未填寫。到「➕ 自訂 ETF」貼上公開說明書的選股重點，或用「🔍 持股透視」匯入持股後自己觀察。）")
        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**✅ 特色**")
            for x in e["pros"] or ["（尚未填寫）"]:
                st.markdown(f"- {x}")
        with p2:
            st.markdown("**⚠️ 要留意**")
            for x in e["risks"] or ["（尚未填寫）"]:
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
                short = [c for c in sel if c not in closes.columns]
                if short:
                    st.caption("以下抓不到足夠的歷史價格（新上市不到約 25 個交易日，或 Yahoo 沒有資料）：" + "、".join(short))
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
                st.caption("價格來自 Yahoo Finance，是否含股利還原依其資料設定而定；僅供相對比較，過去表現不代表未來。")

    with t3:
        hc = st.selectbox("選擇 ETF", list(etfs), format_func=lambda c: f"{c}　{etfs[c]['name']}", key="etf_hold_pick")
        with st.expander("📥 匯入／更新持股明細", expanded=not etfd.list_snapshots(DATA_DIR, hc)):
            st.caption("到投信官網下載該 ETF 的持股明細（Excel／CSV），貼上或上傳。需要有「代號」與「權重」欄位。每匯入一份就存成一個日期快照，累積 2 份以上就能比較權重變化（主動式 ETF 尤其適合用來看經理人的調整）。")
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
                         "技術分": r_["score"] if r_ else None, "站上月線": ("是" if r_["above_ma"] else "否") if r_ else "—",
                         "風報比": r_["rr"] if r_ else None} for c, r_ in zip(tops, res)]
                st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, **STRETCH)
                st.caption("用和個股分析相同的技術評分看權重最大的幾檔，只是『參考ETF在買什麼、這些標的現在強不強』，不構成建議。")

    with t4:
        st.caption("填寫或修改你關注的 ETF 資料（包含主動式 ETF）。新上市的 ETF 可以先到「🧭 市場總覽」一鍵加入，再回來補上選股邏輯。")
        existing = etfd.load_custom(DATA_DIR)
        edit_code = st.selectbox("要編輯哪一檔", ["（新增一檔）"] + list(existing), key="etf_edit_pick",
                                 format_func=lambda c: c if c.startswith("（") else f"{c}　{existing[c].get('name', '')}")
        cur_e = existing.get(edit_code, {}) if not edit_code.startswith("（") else {}
        kind_opts = ["主動式", "市值型（被動）", "高股息型（被動）", "主題型", "債券型", "其他"]
        with st.form("etf_custom_form"):
            f1, f2 = st.columns(2)
            ccode = f1.text_input("ETF 代號", value="" if edit_code.startswith("（") else edit_code, placeholder="例如 00981A")
            cname = f2.text_input("名稱", value=cur_e.get("name", ""))
            f3, f4 = st.columns(2)
            cissuer = f3.text_input("發行投信", value=cur_e.get("issuer", ""))
            ckind = f4.selectbox("類型", kind_opts, index=kind_opts.index(cur_e.get("kind")) if cur_e.get("kind") in kind_opts else 0)
            csum = st.text_area("一句話策略說明", value=cur_e.get("summary", ""))
            clogic = st.text_area("選股／調整邏輯（可貼上公開說明書重點）", value=cur_e.get("logic", ""))
            if st.form_submit_button("儲存", type="primary"):
                if not ccode.strip() or not cname.strip():
                    st.warning("請至少填代號與名稱。")
                else:
                    etfd.save_custom(DATA_DIR, ccode.strip().upper(), dict(name=cname.strip(), issuer=cissuer.strip(), kind=ckind, summary=csum.strip(), logic=clogic.strip()))
                    st.success("已儲存，重新整理後會更新。")
    st.caption("⚠️ ETF 資料僅供研究參考，不構成投資建議。持股明細與權重請以投信官網為準。")

'''
ETF_PAGE_PATTERN = r'def render_etf_page\(\):.*?(?=if app_mode == "🏠 戰情室首頁":)'

# ---------------------------------------------------------------- 5. 到價通知
ALERT_IMPORT_ANCHOR = "except Exception:\n    oq = None\n"
ALERT_IMPORT = "try:\n    import price_alerts as pal\nexcept Exception:\n    pal = None\n"

ALERT_UI = r'''def _alert_prices(tickers):
    """現價：優先用 Yahoo 分 K（可能延遲 15～20 分鐘）；抓不到的退回官方最近收盤價。"""
    px = {}
    try:
        live, _src = sb_live_prices(tuple(tickers))
        px.update(live)
    except Exception:
        pass
    off = get_official_daily() or {}
    by_code = {r["code"]: r for r in off.values()}
    for t in tickers:
        if t not in px:
            r = by_code.get(t.split(".")[0])
            if r:
                px[t] = r["close"]
    return px

def _telegram_cfg():
    try:
        return st.secrets.get("TELEGRAM_BOT_TOKEN"), st.secrets.get("TELEGRAM_CHAT_ID")
    except Exception:
        return None, None

def render_alerts_page():
    st.title("🔔 到價通知")
    st.caption("設定「漲到／跌到某個價格」就提醒你。網頁沒有背景執行，**只有這個頁面開著時才會檢查**；關掉分頁就停止。報價可能延遲 15～20 分鐘。")
    if pal is None:
        st.error("找不到 price_alerts.py。請把它和 app.py 放在同一個資料夾，再重新整理。")
        return
    directory, _ = get_directory()

    with st.expander("➕ 新增到價通知", expanded=not pal.load_alerts(DATA_DIR)):
        q = st.text_input("搜尋股票或 ETF（代號或名稱）", key="al_q", placeholder="例如 2330 或 台積電")
        opts, total = search_stocks(q, directory)
        code = st.selectbox("選擇", opts, key="al_code", format_func=lambda c: f"{directory[c]['name']}（{c}）" if c in directory else c) if opts else None
        a1, a2, a3 = st.columns([1.2, 1, 2])
        op_label = a1.radio("條件", ["漲到（≥）", "跌到（≤）"], key="al_op")
        price = a2.number_input("目標價", min_value=0.0, step=0.5, key="al_price")
        note = a3.text_input("備註（選填）", key="al_note", placeholder="例如：突破壓力、跌破停損")
        if code:
            r = {x["code"]: x for x in (get_official_daily() or {}).values()}.get(code)
            if r:
                st.caption(f"參考：最近收盤 {r['close']:.2f}（{r['chg']:+.2f}%，{r['asof']}）")
        if st.button("儲存這則通知", type="primary", key="al_add"):
            if not code or price <= 0:
                st.warning("請選擇股票並輸入大於 0 的目標價。")
            else:
                suffix = directory.get(code, {}).get("suffix", ".TW")
                pal.add_alert(DATA_DIR, code + suffix, code, directory.get(code, {}).get("name", code), ">=" if op_label.startswith("漲") else "<=", price, note)
                st.success("已儲存。")
                st.rerun()

    token, chat = _telegram_cfg()
    with st.expander("📲 手機推播（Telegram，選填）"):
        if token and chat:
            st.success("已偵測到 Telegram 設定：觸發時會同時推播到你的手機。")
            if st.button("送一則測試訊息", key="al_tg_test"):
                ok, msg = pal.send_telegram(token, chat, "✅ 到價通知測試訊息")
                (st.success if ok else st.error)("已送出" if ok else f"送出失敗：{msg}")
        else:
            st.markdown(
                "1. 在 Telegram 搜尋 **@BotFather**，傳 `/newbot` 建立機器人，取得 **token**。\n"
                "2. 對你的機器人傳一句話，再開 `https://api.telegram.org/bot<token>/getUpdates` 找到 `chat` 裡的 **id**。\n"
                "3. 到 Streamlit Cloud 的 App 設定 → **Secrets**，貼上：\n\n"
                "```\nTELEGRAM_BOT_TOKEN = \"你的token\"\nTELEGRAM_CHAT_ID = \"你的chat id\"\n```\n"
                "token 是密碼，不要寫進程式或上傳到 GitHub。")

    alerts = pal.load_alerts(DATA_DIR)
    if not alerts:
        st.info("還沒有任何到價通知。")
        return

    c1, c2, c3 = st.columns([1.3, 1, 2])
    monitor = c1.toggle("🔴 自動檢查", key="al_monitor", help="開著這個頁面時，每隔一段時間自動檢查。")
    interval = c2.selectbox("間隔", [30, 60, 120], index=1, format_func=lambda x: f"{x} 秒", key="al_interval")

    def _check_body():
        al = pal.load_alerts(DATA_DIR)
        act = [a for a in al if a.get("active", True)]
        px = _alert_prices(sorted({a["ticker"] for a in al})) if al else {}
        hits = pal.evaluate(al, px)
        if hits:
            pal.mark_triggered(DATA_DIR, hits)
            tk, cid = _telegram_cfg()
            for a, p_ in hits:
                msg = pal.format_message(a, p_)
                st.success(msg)
                st.toast(msg)
                if tk and cid:
                    ok, info = pal.send_telegram(tk, cid, msg)
                    if not ok:
                        st.caption(f"Telegram 推播失敗：{info}")
            al = pal.load_alerts(DATA_DIR)
        rows = []
        for a in al:
            p_ = px.get(a["ticker"])
            rows.append({"股票": f"{a['name']}（{a['code']}）", "條件": f"{pal.OPS[a['op']]} {a['price']:g}", "現價": p_,
                         "距目標%": (a["price"] / p_ - 1) * 100 if p_ else None,
                         "狀態": "✅ 已觸發 " + str(a.get("triggered_at") or "") if not a.get("active", True) else "⏳ 監控中", "備註": a.get("note", "")})
        st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, **STRETCH)
        missing = [a["code"] for a in act if a["ticker"] not in px]
        if missing:
            st.caption("抓不到現價所以暫時無法判斷：" + "、".join(missing))
        st.caption(f"最近檢查：{pd.Timestamp.now(tz='Asia/Taipei').strftime('%H:%M:%S')}　·　報價可能延遲；休市時看到的是最近一個收盤價。")

    frag = getattr(st, "fragment", None)
    if monitor and frag is not None:
        frag(run_every=int(interval))(_check_body)()
    else:
        if monitor:
            st.warning("你的 Streamlit 版本不支援自動重新整理，請改用「立即檢查」。")
        st.button("🔄 立即檢查", key="al_check_now")
        _check_body()

    with st.expander("管理通知"):
        labels = {a["id"]: f"{a['name']}（{a['code']}）{pal.OPS[a['op']]} {a['price']:g}" + ("　[已觸發]" if not a.get("active", True) else "") for a in alerts}
        chosen = st.multiselect("選擇通知", list(labels), format_func=lambda i: labels[i], key="al_manage")
        m1, m2 = st.columns(2)
        if m1.button("🔁 重新啟用", key="al_rearm") and chosen:
            pal.rearm(DATA_DIR, chosen)
            st.rerun()
        if m2.button("🗑️ 刪除", key="al_del") and chosen:
            pal.remove_alerts(DATA_DIR, chosen)
            st.rerun()
    st.caption("⚠️ 雲端環境重啟或重新部署時，本機存的通知可能會消失。要在頁面關閉時也收到通知，需要另外做排程（例如 GitHub Actions），可以再跟我說。")

'''

NAV_DESK_OLD = '("desk",     "💼 操盤室",   ["💼 投資組合管理", "🤖 模擬自動交易"]),'
NAV_DESK_NEW = '("desk",     "💼 操盤室",   ["💼 投資組合管理", "🔔 到價通知", "🤖 模擬自動交易"]),'
ROUTE_OLD = 'elif app_mode == "📰 盤前必讀":\n    render_premarket_page()'
ROUTE_NEW = 'elif app_mode == "🔔 到價通知":\n    render_alerts_page()\n\n' + ROUTE_OLD
HOME_ANCHOR = 'if app_mode == "🏠 戰情室首頁":\n    st.title("🏠 戰情室首頁")'


class Skip(Exception):
    pass


def count(t, s):
    return t.count(s)


def main():
    if not os.path.exists(APP):
        sys.exit(f"❌ 找不到 {APP}。請把這支腳本放在 app.py 所在的資料夾。")
    with open(APP, "r", encoding="utf-8") as f:
        orig = f.read()
    app = orig
    done, skipped = [], []

    def step(title, fn):
        nonlocal app
        try:
            app = fn(app)
            done.append(title)
        except Skip as e:
            skipped.append(f"{title} → {e}")

    def s1(t):
        if LOG_NEW in t:
            raise Skip("已經套用過")
        if count(t, LOG_OLD) != 1:
            raise Skip(f"交易紀錄篩選那一行：找不到唯一的片段（找到 {count(t, LOG_OLD)} 處）")
        return t.replace(LOG_OLD, LOG_NEW)

    def s2(t):
        if "def _official_src_cached" in t:
            raise Skip("已經套用過")
        if "def get_official_daily" not in t:
            raise Skip("需要先成功套用 apply_patches5.py")
        for old, label in ((DIR_TRUE_OLD, "名單函式（成功分支）"), (DIR_FALSE_OLD, "名單函式（備援分支）")):
            if count(t, old) != 1:
                raise Skip(f"{label}：找不到唯一的片段（找到 {count(t, old)} 處）")
        m = list(re.finditer(OFFICIAL_PATTERN, t, flags=re.S))
        if len(m) != 1:
            raise Skip(f"官方資料函式區塊：找不到唯一的區塊（找到 {len(m)} 處）")
        t = t[:m[0].start()] + OFFICIAL_FUNCS + t[m[0].end():]
        t = t.replace(DIR_TRUE_OLD, DIR_TRUE_NEW).replace(DIR_FALSE_OLD, DIR_FALSE_NEW)
        return t

    def s3(t):
        if "def _guess_etf_kind" in t:
            raise Skip("已經套用過")
        if "def _official_src_cached" not in t:
            raise Skip("需要第 2 步先成功")
        m = list(re.finditer(ETF_PAGE_PATTERN, t, flags=re.S))
        if len(m) != 1 or "def render_etf_page" not in t:
            raise Skip(f"ETF 專區頁：找不到唯一的區塊（找到 {len(m)} 處；需要先成功套用 apply_patches3.py）")
        return t[:m[0].start()] + ETF_PAGE + t[m[0].end():]

    def s4(t):
        if "def render_alerts_page" in t:
            raise Skip("已經套用過")
        if "def _official_src_cached" not in t:
            raise Skip("需要第 2 步先成功")
        for old, label in ((ALERT_IMPORT_ANCHOR, "模組匯入區（需要先成功套用 apply_patches5.py）"), (NAV_DESK_OLD, "導覽列『操盤室』分組"),
                           (ROUTE_OLD, "頁面路由（需要先成功套用 apply_patches3.py）"), (HOME_ANCHOR, "首頁區塊")):
            if count(t, old) != 1:
                raise Skip(f"{label}：找不到唯一的片段（找到 {count(t, old)} 處）")
        t = t.replace(ALERT_IMPORT_ANCHOR, ALERT_IMPORT_ANCHOR + ALERT_IMPORT)
        t = t.replace(NAV_DESK_OLD, NAV_DESK_NEW).replace(ROUTE_OLD, ROUTE_NEW)
        return t.replace(HOME_ANCHOR, ALERT_UI + HOME_ANCHOR)

    step("1. 修正交易紀錄篩選的 KeyError", s1)
    step("2. 官方資料上市／上櫃分開快取，並補齊股票名單（含新上市 ETF）", s2)
    step("3. ETF 專區改版（市場總覽、自訂 ETF 顯示）", s3)
    step("4. 新增「🔔 到價通知」頁面", s4)

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)
    if app != orig:
        bak = APP + ".bak6"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    for m in ("official_quotes.py", "price_alerts.py"):
        if not os.path.exists(os.path.join(HERE, m)):
            print(f"⚠️ 資料夾裡沒有 {m}，對應功能會顯示找不到模組或退回備援。")


if __name__ == "__main__":
    main()
