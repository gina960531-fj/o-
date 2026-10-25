# -*- coding: utf-8 -*-
"""
第五批：熱力圖與全市場流動性排行，改用證交所／櫃買「每日收盤」開放資料（Yahoo 當備援）
用法：和 app.py、official_quotes.py 放同一個資料夾，執行  python apply_patches5.py
找不到對應位置的步驟會略過並說明；有修改才寫檔（備份成 app.py.bak5）。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))

IMPORT_ANCHOR = "except Exception:\n    pmk = None\n"
IMPORT_ADD = "try:\n    import official_quotes as oq\nexcept Exception:\n    oq = None\n"

FUNCS = r'''@st.cache_data(ttl=600, show_spinner=False)
def _official_cached():
    """證交所＋櫃買每日收盤行情。抓失敗或檔數太少就丟例外（不會被快取），由外層退回 Yahoo。"""
    if oq is None:
        raise RuntimeError("official_quotes 模組不存在")
    rows, _msgs = oq.fetch_official()
    if len(rows) < 300:
        raise RuntimeError("官方資料檔數過少")
    return rows

def get_official_daily():
    try:
        return _official_cached()
    except Exception:
        return None

def get_official_liquidity():
    """{代號: 成交值}，用成交值排流動性（比成交股數更不會被低價股誤導）。"""
    off = get_official_daily()
    return oq.liquidity(off) if off else None

'''

HEAT_ANCHOR = "def heatmap_pool(directory, size):"
FETCH_OLD = ('    rows, got = [], set()\n    try:\n'
             '        raw = yf.download(list(tickers), period="5d", group_by="ticker", progress=False, threads=True, auto_adjust=False)')
FETCH_NEW = ('    rows, got = [], set()\n'
             '    _off = get_official_daily()\n'
             '    if _off:\n'
             '        _by_code = {r["code"]: r for r in _off.values()}\n'
             '        for t in tickers:\n'
             '            r = _by_code.get(str(t).split(".")[0])\n'
             '            if r:\n'
             '                rows.append({"ticker": t, "close": r["close"], "prev": r["prev"], "chg": r["chg"], "value": r["value"], "asof": r["asof"]})\n'
             '                got.add(t)\n'
             '    try:\n'
             '        raw = yf.download([t for t in tickers if t not in got], period="5d", group_by="ticker", progress=False, threads=True, auto_adjust=False)')
VOL_OLD = "    vol_map = get_market_volume_snapshot()"
VOL_NEW = "    vol_map = get_official_liquidity() or get_market_volume_snapshot()"


class Skip(Exception):
    pass


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

    def need_once(t, old, label):
        n = t.count(old)
        if n != 1:
            raise Skip(f"{label}：找不到唯一的片段（找到 {n} 處）")

    def s1(t):
        if "import official_quotes as oq" in t:
            raise Skip("已經套用過")
        need_once(t, IMPORT_ANCHOR, "premarket 匯入區（需要先成功套用 apply_patches3.py）")
        return t.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_ADD)

    def s2(t):
        if "def get_official_daily" in t:
            raise Skip("已經套用過")
        if "import official_quotes as oq" not in t:
            raise Skip("需要第 1 步先成功")
        need_once(t, HEAT_ANCHOR, "熱力圖函式")
        need_once(t, FETCH_OLD, "fetch_heat_quotes 的批次下載")
        if t.count(VOL_OLD) != 2:
            raise Skip(f"成交量排行呼叫：預期 2 處，找到 {t.count(VOL_OLD)} 處")
        t = t.replace(FETCH_OLD, FETCH_NEW)
        t = t.replace(VOL_OLD, VOL_NEW)
        return t.replace(HEAT_ANCHOR, FUNCS + HEAT_ANCHOR)

    step("1. 載入 official_quotes 模組", s1)
    step("2. 熱力圖報價與流動性排行改用官方每日收盤資料", s2)

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)
    if app != orig:
        bak = APP + ".bak5"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    if not os.path.exists(os.path.join(HERE, "official_quotes.py")):
        print("⚠️ 資料夾裡沒有 official_quotes.py，熱力圖會退回 Yahoo。")


if __name__ == "__main__":
    main()
