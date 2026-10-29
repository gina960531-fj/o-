# -*- coding: utf-8 -*-
"""
第八批：盤中即時報價與資料時間標示
  1. 熱力圖：新增「盤中即時報價」開關（證交所即時資訊系統 MIS，約 5 秒延遲）；抓不到就退回官方收盤資料
  2. 熱力圖：清楚標示資料是「即時」還是「最近收盤（不是今天盤中）」，資料日期不是今天時會提醒
  3. 到價通知：現價優先用即時報價（原本用 Yahoo，雲端常被擋）
用法：和 app.py、official_quotes.py 放同一個資料夾，執行  python apply_patches8.py
需要先成功套用 apply_patches5.py、apply_patches6.py。每一步獨立；有修改才寫檔（備份成 app.py.bak8）。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))

LIVE_FUNCS = r'''@st.cache_data(ttl=15, show_spinner=False)
def _live_quotes_cached(tickers):
    if oq is None:
        raise RuntimeError("official_quotes 模組不存在")
    return oq.fetch_mis(list(tickers))

def get_live_rows(tickers):
    """盤中即時報價（證交所 MIS）。抓不到回傳 None，失敗後 5 分鐘內不重試，避免拖慢頁面。"""
    fails = _official_fail_log()
    if time.time() - fails.get("mis", 0) < 300:
        return None
    try:
        return _live_quotes_cached(tuple(tickers))
    except Exception:
        fails["mis"] = time.time()
        return None

def fetch_live_heat_quotes(tickers):
    rows = get_live_rows(tickers)
    if not rows:
        return None
    df = pd.DataFrame([{"ticker": t, "close": r["close"], "prev": r["prev"], "chg": r["chg"], "value": r["value"], "asof": r["asof"]}
                       for t, r in rows.items()])
    return df if len(df) >= 5 else None

'''
HEAT_ANCHOR = "def heatmap_pool(directory, size):"

FETCH_OLD = ('    with st.spinner(f"抓取 {len(_tickers)} 檔個股報價中…（首次載入較久）"):\n'
             '        _quotes = fetch_heat_quotes(_tickers)\n')
FETCH_NEW = ('    _live_on = st.toggle("⚡ 盤中即時報價（證交所即時資訊，約 5 秒延遲）", value=(market_status()[0] == "盤中"), key="hm_live",\n'
             '                         help="開啟時用即時報價；抓不到會自動退回最近一個收盤日的官方資料。官方收盤資料要到傍晚才會更新當天。")\n'
             '    _quotes, _src_note = None, "收盤"\n'
             '    with st.spinner(f"抓取 {len(_tickers)} 檔個股報價中…（首次載入較久）"):\n'
             '        if _live_on:\n'
             '            _quotes = fetch_live_heat_quotes(_tickers)\n'
             '            if _quotes is not None:\n'
             '                _src_note = "即時"\n'
             '            else:\n'
             '                st.warning("即時報價暫時抓不到，改顯示最近一個收盤日的官方資料。")\n'
             '        if _quotes is None:\n'
             '            _quotes = fetch_heat_quotes(_tickers)\n')

CAP_OLD = "st.caption(f\"資料日期 {_q['asof'].mode().iloc[0]}　·　樣本"
CAP_NEW = ("_asof = str(_q['asof'].mode().iloc[0])\n"
           "        st.caption((\"⚡ 即時報價\" if _src_note == \"即時\" else \"🕓 最近收盤資料（不是今天盤中）\") + f\"　·　資料時間 {_asof}　·　樣本")
STALE_OLD = "        _q, _sec = build_sector_table(_quotes, _hm_directory)\n"
STALE_NEW = ("        _q, _sec = build_sector_table(_quotes, _hm_directory)\n"
             "        _today_md = pd.Timestamp.now(tz=\"Asia/Taipei\").strftime(\"%m/%d\")\n"
             "        if _src_note == \"收盤\" and str(_q['asof'].mode().iloc[0]) != _today_md and market_status()[0] in (\"盤中\", \"已收盤\"):\n"
             "            st.warning(f\"目前顯示的是 {_q['asof'].mode().iloc[0]} 的收盤資料，不是今天。官方當日收盤資料通常傍晚才公布；\"\n"
             "                       \"今天盤中的漲跌請開啟上方「⚡ 盤中即時報價」。\")\n")
TOP_OLD = "顏色＝今日漲跌幅。"
TOP_NEW = "顏色＝漲跌幅（盤中為即時、收盤後為當日；頁面會標示資料時間）。"

ALERT_OLD = ('    px = {}\n'
             '    try:\n'
             '        live, _src = sb_live_prices(tuple(tickers))\n'
             '        px.update(live)\n'
             '    except Exception:\n'
             '        pass\n')
ALERT_NEW = ('    px = {}\n'
             '    _mis = get_live_rows(tickers)\n'
             '    if _mis:\n'
             '        px.update({t: r["close"] for t, r in _mis.items()})\n'
             '    _rest = [t for t in tickers if t not in px]\n'
             '    if _rest:\n'
             '        try:\n'
             '            live, _src = sb_live_prices(tuple(_rest))\n'
             '            px.update(live)\n'
             '        except Exception:\n'
             '            pass\n')


def main():
    if not os.path.exists(APP):
        sys.exit(f"❌ 找不到 {APP}。請把這支腳本放在 app.py 所在的資料夾。")
    with open(APP, "r", encoding="utf-8") as f:
        orig = f.read()
    app = orig
    done, skipped = [], []

    def need(t, s, label, n=1):
        c = t.count(s)
        if c != n:
            raise ValueError(f"{label}：找不到唯一的片段（找到 {c} 處）")

    # 1+2 熱力圖
    try:
        if "def fetch_live_heat_quotes" in app:
            raise LookupError("已經套用過")
        if "def _official_fail_log" not in app:
            raise ValueError("需要先成功套用 apply_patches6.py（以及 apply_patches5.py）")
        for s, label in ((HEAT_ANCHOR, "熱力圖函式"), (FETCH_OLD, "熱力圖頁的報價抓取"), (CAP_OLD, "熱力圖資料日期說明"),
                         (STALE_OLD, "熱力圖頁的彙總計算"), (TOP_OLD, "熱力圖頁的說明文字")):
            need(app, s, label)
        app = app.replace(HEAT_ANCHOR, LIVE_FUNCS + HEAT_ANCHOR)
        app = app.replace(FETCH_OLD, FETCH_NEW).replace(CAP_OLD, CAP_NEW).replace(STALE_OLD, STALE_NEW).replace(TOP_OLD, TOP_NEW)
        done.append("1. 熱力圖：盤中即時報價開關＋資料時間標示")
    except LookupError as e:
        skipped.append(f"1. 熱力圖：盤中即時報價開關＋資料時間標示 → {e}")
    except ValueError as e:
        skipped.append(f"1. 熱力圖：盤中即時報價開關＋資料時間標示 → {e}")

    # 3 到價通知
    try:
        if "_mis = get_live_rows(tickers)" in app:
            raise LookupError("已經套用過")
        if "def get_live_rows" not in app:
            raise ValueError("需要第 1 步先成功")
        need(app, ALERT_OLD, "到價通知的現價來源（需要先成功套用 apply_patches6.py）")
        app = app.replace(ALERT_OLD, ALERT_NEW)
        done.append("2. 到價通知：現價優先用即時報價")
    except (LookupError, ValueError) as e:
        skipped.append(f"2. 到價通知：現價優先用即時報價 → {e}")

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)
    if app != orig:
        bak = APP + ".bak8"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    if not os.path.exists(os.path.join(HERE, "official_quotes.py")):
        print("⚠️ 資料夾裡沒有 official_quotes.py，即時報價會退回收盤資料。")


if __name__ == "__main__":
    main()
