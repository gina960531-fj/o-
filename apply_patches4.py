# -*- coding: utf-8 -*-
"""
第四批：在「📰 盤前必讀」加入大盤走勢預測區塊
  - 0050 技術面預測（歷史相似情境的上漲機率、樣本數、信心水準）
  - 隔夜費半／那斯達克 對 0050 的歷史預測力（過去兩年的實際配對統計＋顯著性檢定）
用法：和 app.py、overnight_edge.py 放同一個資料夾，執行  python apply_patches4.py
需要先成功套用 apply_patches3.py。找不到對應位置的步驟會略過並說明；有修改才寫檔（備份成 app.py.bak4）。
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))

IMPORT_OLD = "try:\n    import premarket as pmk\nexcept Exception:\n    pmk = None\n"
IMPORT_NEW = IMPORT_OLD + "try:\n    import overnight_edge as oed\nexcept Exception:\n    oed = None\n"

DEF_OLD = "def render_market_forecast(tone=0):"
DEF_NEW = "def render_market_forecast(tone=0, show_nav=True):"
BTN_OLD = '    if st.button("📰 開盤前完整情報 → 盤前必讀", key="mf_go_premarket"):'
BTN_NEW = '    if show_nav and st.button("📰 開盤前完整情報 → 盤前必讀", key="mf_go_premarket"):'

FUNCS = r'''@st.cache_data(ttl=3600, show_spinner=False)
def _oe_load_cached():
    out = {}
    for key, sym in (("tw", "0050.TW"), ("sox", "^SOX"), ("ndx", "^IXIC")):
        try:
            h = yf.Ticker(sym).history(period="2y")
            out[key] = _norm_series(h["Close"]) if (h is not None and len(h) > 50) else None
        except Exception:
            out[key] = None
    if out["tw"] is None or (out["sox"] is None and out["ndx"] is None):
        raise RuntimeError("歷史資料不足")
    return out

def _oe_load():
    try:
        return _oe_load_cached()
    except Exception:
        return None

def render_overnight_edge(quotes):
    if oed is None:
        st.info("找不到 overnight_edge.py，無法做隔夜統計。請把它和 app.py 放在同一個資料夾。")
        return
    data = _oe_load()
    if not data:
        st.info("歷史價格暫時抓不到，無法做隔夜統計。")
        return
    now = pd.Timestamp.now(tz="Asia/Taipei")
    if now.weekday() < 5 and (now.hour * 100 + now.minute) < 1330:
        st.caption("現在還沒收盤：下面的隔夜漲跌，對應的就是「今天」的台股走勢。")
    else:
        st.caption("⚠️ 台股已收盤或休市：美股要到今晚才收盤，下面是「已經影響過今天」的隔夜資料；要預測下一個交易日，請等美股收盤後再看。")
    cols = st.columns(2)
    for col, key, sym, label in ((cols[0], "sox", "^SOX", "費城半導體"), (cols[1], "ndx", "^IXIC", "那斯達克")):
        with col:
            st.markdown(f"**{label} → 隔天的 0050**")
            ser, q = data.get(key), quotes.get(sym)
            if ser is None or not q:
                st.caption("資料不足")
                continue
            pairs = oed.build_pairs(data["tw"], ser)
            e = oed.edge_for(q["chg_pct"], pairs)
            if e["bucket"] is None:
                st.caption("歷史樣本不足")
                continue
            st.metric(f"最近美股日 {label}", f"{q['chg_pct']:+.2f}%", e["bucket"], delta_color="off")
            if e["n"]:
                st.write(f"過去兩年同樣情況共 **{e['n']}** 次，0050 當天上漲 **{e['up_prob']:.0f}%**、平均漲跌 {e['mean_ret']:+.2f}%（所有日子的上漲基準是 {e['base_up']:.0f}%）。")
            r, p = e["corr"], e["p"]
            if e["verdict"] == "useful":
                st.success(f"整體關聯在統計上站得住腳（相關係數 {r:.2f}，p={p:.3f}），可以當參考；但 r² 只有 {r * r * 100:.0f}%，解釋力有限。")
            elif e["verdict"] == "weak":
                st.info(f"整體關聯很弱（相關係數 {r:.2f}，p={p:.2f}）：過去兩年，這個隔夜漲跌對 0050 當天走勢沒有可靠的預測力，不要只靠它判斷。")
            else:
                st.caption("這個區間的歷史樣本太少（少於 20 次），數字不具統計意義。")
            with st.expander("各區間歷史統計"):
                bt = oed.bucket_table(pairs)
                if not bt.empty:
                    st.dataframe(bt.round(1), **STRETCH)
    st.caption("做法：每個台股交易日，配上『嚴格早於當天的最近一個美股交易日』的漲跌，統計過去兩年的實際結果。這是描述歷史，不是預測保證；區間與樣本數越少越不可靠。")

def render_tomorrow_forecast(summ, quotes):
    st.markdown("#### 🔮 大盤走勢預測（以 0050 為代理）")
    tone = 2 if summ["score"] >= 3 else (-2 if summ["score"] <= -3 else 0)
    render_market_forecast(tone, show_nav=False)
    st.markdown("##### 🌙 隔夜美股對 0050 的歷史預測力")
    render_overnight_edge(quotes)

'''

PAGE_PATTERN = (r'    fc = get_market_forecast\("0050\.TW"\)\n    if fc:\n        st\.markdown\(f"\*\*0050 技術面\*\*.*?'
                r'同分不代表開盤一定同方向。"\)\n')
PAGE_NEW = '    render_tomorrow_forecast(summ, quotes)\n'


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

    def step(title, fn):
        nonlocal app
        try:
            app = fn(app)
            done.append(title)
        except Skip as e:
            skipped.append(f"{title} → {e}")

    def s_import(t):
        if "import overnight_edge as oed" in t:
            raise Skip("已經套用過")
        return once(t, IMPORT_OLD, IMPORT_NEW, "premarket 匯入區（需要先成功套用 apply_patches3.py）")

    def s_page(t):
        if "def render_tomorrow_forecast" in t:
            raise Skip("已經套用過")
        if "def render_premarket_page" not in t or "def render_market_forecast" not in t:
            raise Skip("找不到盤前必讀頁（需要先成功套用 apply_patches3.py）")
        t = once(t, DEF_OLD, DEF_NEW, "預測區塊函式定義")
        t = once(t, BTN_OLD, BTN_NEW, "預測區塊的導覽按鈕")
        m = list(re.finditer(PAGE_PATTERN, t, flags=re.S))
        if len(m) != 1:
            raise Skip(f"盤前必讀頁的舊預測行：找不到唯一的區塊（找到 {len(m)} 處）")
        t = t[:m[0].start()] + PAGE_NEW + t[m[0].end():]
        return once(t, "def render_premarket_page():", FUNCS + "def render_premarket_page():", "盤前必讀頁函式")

    step("1. 載入 overnight_edge 模組", s_import)
    step("2. 盤前必讀：加入大盤走勢預測與隔夜歷史預測力", s_page)

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)
    if app != orig:
        bak = APP + ".bak4"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    if not os.path.exists(os.path.join(HERE, "overnight_edge.py")):
        print("⚠️ 資料夾裡沒有 overnight_edge.py，預測區塊會顯示找不到模組。")


if __name__ == "__main__":
    main()
