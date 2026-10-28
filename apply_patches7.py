# -*- coding: utf-8 -*-
"""
第七批：資料持久化（雲端重啟後資料不消失）
  - 啟動時從「私人 GitHub 資料專案」把資料抓回來，之後約每 60 秒把有變動的檔案存回去
  - 首頁顯示同步狀態（沒設定時會提醒）
  - 沒有設定金鑰時，程式維持原本行為（不會當機）
用法：和 app.py、persist.py 放同一個資料夾，執行  python apply_patches7.py
有修改才寫檔（備份成 app.py.bak7）。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),
           os.path.join(HERE, "app.py"))

DATA_DIR_LINE = 'DATA_DIR = os.path.join(os.path.expanduser("~"), ".quant_radar_data")\n'
BOOT = r'''
# ---- 資料持久化：和私人 GitHub 資料專案同步（需要在 Secrets 設定 GITHUB_DATA_TOKEN 與 GITHUB_DATA_REPO）----
try:
    import persist
except Exception:
    persist = None

def _secret(name):
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.environ.get(name)

@st.cache_resource(show_spinner="同步雲端資料中…")
def _persist_boot(token, repo):
    sync = persist.make_sync(DATA_DIR, token, repo) if persist else None
    if sync is not None:
        sync.boot_pull()
        sync.start_background(60)
    return sync

try:
    PERSIST = _persist_boot(_secret("GITHUB_DATA_TOKEN"), _secret("GITHUB_DATA_REPO"))
except Exception:
    PERSIST = None
'''

STATUS_FUNC = r'''def render_sync_status():
    if PERSIST is None:
        st.warning("☁️ 雲端資料同步：尚未設定。目前資料只存在伺服器的暫存硬碟，App 重啟或重新部署後會消失"
                   "（觀察清單、持股、模擬交易、到價通知、大戶籌碼累積都會受影響）。設定方式：在 App 的 Secrets 填入 GITHUB_DATA_TOKEN 與 GITHUB_DATA_REPO。")
        return
    if not PERSIST.pulled:
        st.error(f"☁️ 雲端資料同步失敗：{PERSIST.last_error or '尚未完成'}。在恢復之前，系統不會上傳任何資料，以免覆蓋雲端的舊資料。")
        if st.button("🔄 重新同步", key="persist_retry"):
            PERSIST.boot_pull()
            st.rerun()
        return
    c = PERSIST.counts
    msg = f"☁️ 雲端資料同步：已啟用　·　啟動時還原 {c['down']} 個檔案　·　最近一次上傳 {PERSIST.last_push or '尚未'}"
    if PERSIST.last_error:
        st.warning(msg + f"　·　⚠️ {PERSIST.last_error}")
    else:
        st.caption(msg)
    for n in PERSIST.notes:
        st.caption("⚠️ " + n)

'''
HOME_ANCHOR = 'if app_mode == "🏠 戰情室首頁":\n    st.title("🏠 戰情室首頁")'


def main():
    if not os.path.exists(APP):
        sys.exit(f"❌ 找不到 {APP}。請把這支腳本放在 app.py 所在的資料夾。")
    with open(APP, "r", encoding="utf-8") as f:
        orig = f.read()
    app = orig
    done, skipped = [], []

    if "def _persist_boot" in app:
        skipped.append("1. 啟動時還原與背景同步 → 已經套用過")
    elif app.count(DATA_DIR_LINE) != 1:
        skipped.append(f"1. 啟動時還原與背景同步 → 找不到唯一的 DATA_DIR 定義（找到 {app.count(DATA_DIR_LINE)} 處）")
    else:
        app = app.replace(DATA_DIR_LINE, DATA_DIR_LINE + BOOT)
        done.append("1. 啟動時還原與背景同步")

    if "def render_sync_status" in app:
        skipped.append("2. 首頁同步狀態 → 已經套用過")
    elif "def _persist_boot" not in app:
        skipped.append("2. 首頁同步狀態 → 需要第 1 步先成功")
    elif app.count(HOME_ANCHOR) != 1:
        skipped.append(f"2. 首頁同步狀態 → 找不到唯一的首頁區塊（找到 {app.count(HOME_ANCHOR)} 處）")
    else:
        app = app.replace(HOME_ANCHOR, STATUS_FUNC + HOME_ANCHOR + "\n    render_sync_status()")
        done.append("2. 首頁同步狀態")

    print("— 套用結果 —")
    for t in done:
        print("✅", t)
    for t in skipped:
        print("⏭️ 略過", t)
    if app != orig:
        bak = APP + ".bak7"
        if not os.path.exists(bak):
            shutil.copy2(APP, bak)
        with open(APP, "w", encoding="utf-8") as f:
            f.write(app)
        print(f"\n已寫入 {os.path.basename(APP)}（備份：{os.path.basename(bak)}）。請執行 python -m py_compile {os.path.basename(APP)} 檢查語法。")
    else:
        print("\n沒有任何變更，檔案未被修改。")
    if not os.path.exists(os.path.join(HERE, "persist.py")):
        print("⚠️ 資料夾裡沒有 persist.py，同步功能不會啟用。")


if __name__ == "__main__":
    main()
