# -*- coding: utf-8 -*-
"""
一鍵執行：
  0. 自動清掉檔案結尾被一起複製進來的「卡片標題」（例如 "Apply patches3 · PY"），並把舊版 apply_patches.py 更新成會自動找 app.py 的版本
  1. 依序套用三批修補
  2. 檢查語法，並列出每個功能有沒有真的寫進 app.py
用法（在 app.py 所在的資料夾，新開的 bash 終端機裡）：  python run_all.py
"""
import os
import py_compile
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
ME = os.path.basename(__file__)

# 複製檔案卡片時，標題（如「Etf data · PY」）可能黏在最後一行後面，或單獨成一行
JUNK_TAIL = re.compile(r"(?<=[\w\)\]\}\"'])[A-Z][A-Za-z0-9_ ]* · [A-Z]{2,4}\s*$")
JUNK_LINE = re.compile(r"[A-Z][A-Za-z0-9_ ]* · [A-Z]{2,4}")


def strip_junk():
    print("0-a. 檢查檔案結尾有沒有多貼進來的文字…")
    fixed = 0
    for f in sorted(os.listdir(".")):
        if not f.endswith(".py") or f == ME:
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                txt = fh.read()
        except UnicodeDecodeError:
            continue
        body = txt.rstrip()
        if not body:
            continue
        lines = body.split("\n")
        last = lines[-1]
        new = None
        if JUNK_LINE.fullmatch(last.strip()):
            new = "\n".join(lines[:-1]).rstrip() + "\n"
        else:
            m = JUNK_TAIL.search(last)
            if m:
                lines[-1] = last[:m.start()]
                new = "\n".join(lines).rstrip() + "\n"
        if new is not None:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            fixed += 1
            print(f"   🧹 {f}：已移除結尾多餘文字")
    if not fixed:
        print("   （沒有發現）")


OLD_APP_LINE = 'APP = os.path.join(HERE, "quant_radar_app.py")\n'
NEW_APP_LINE = ('APP = next((os.path.join(HERE, n) for n in ("quant_radar_app.py", "app.py") if os.path.exists(os.path.join(HERE, n))),\n'
                '           os.path.join(HERE, "app.py"))\n')


def migrate_apply_patches():
    print("0-b. 檢查 apply_patches.py 是不是舊版…")
    if not os.path.exists("apply_patches.py"):
        print("   （找不到 apply_patches.py）")
        return
    with open("apply_patches.py", "r", encoding="utf-8") as fh:
        s = fh.read()
    if OLD_APP_LINE in s:
        with open("apply_patches.py", "w", encoding="utf-8") as fh:
            fh.write(s.replace(OLD_APP_LINE, NEW_APP_LINE))
        print("   🔧 已更新成會自動找 app.py 的版本")
    else:
        print("   （已經是新版）")


def main():
    strip_junk()
    migrate_apply_patches()

    required = ["app.py", "wanglai_data.py", "wanglai_picks.py", "portfolio_balance.py", "etf_data.py", "premarket.py",
                "apply_patches.py", "apply_patches2.py", "apply_patches3.py"]
    missing = [f for f in required if not os.path.exists(f)]
    if missing:
        print("❌ 資料夾裡缺少這些檔案（檔名要完全一致：小寫、用底線、沒有空格）：")
        for f in missing:
            print("   -", f)
        print("\n目前資料夾裡的 .py 檔：", sorted(f for f in os.listdir(".") if f.endswith(".py")))
        sys.exit(1)

    print("0-c. 檢查每個檔案的語法…")
    broken = []
    for f in required:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            broken.append(f)
            print(f"   ❌ {f}：{str(e).strip()[-300:]}")
    if broken:
        print("\n上面這些檔案本身有語法錯誤，請先修好或重新下載（用『下載』按鈕，不要複製貼上）再執行。")
        sys.exit(1)
    print("   ✅ 全部通過")

    for script in ("apply_patches.py", "apply_patches2.py", "apply_patches3.py"):
        print("=" * 60)
        print("執行", script)
        r = subprocess.run([sys.executable, script], capture_output=True, text=True)
        print((r.stdout or "").strip())
        if r.stderr.strip():
            print(r.stderr.strip())
        if r.returncode != 0:
            print(f"（{script} 回報問題，沒有寫入檔案；繼續執行下一批）")

    print("=" * 60)
    try:
        py_compile.compile("app.py", doraise=True)
        print("✅ app.py 語法檢查通過")
    except py_compile.PyCompileError as e:
        print("❌ app.py 語法錯誤：", e)
        print("   可用備份還原：app.py.bak、app.py.bak2、app.py.bak3（依序是各批修補之前的版本）")
        sys.exit(1)

    with open("app.py", "r", encoding="utf-8") as f:
        src = f.read()
    checks = [
        ("第 1 批：區間進場回測（BUCKET_RANGE）", "BUCKET_RANGE"),
        ("第 1 批：失敗不快取（cache_if_ok）", "def cache_if_ok"),
        ("第 2 批：向量化回測（vector_score）", "def vector_score"),
        ("第 2 批：平行掃描（_one）", "def _one(tk):"),
        ("第 2 批：大戶選股分頁", "def render_big_holder_picks"),
        ("第 3 批：首頁明日大盤預測", "def render_market_forecast"),
        ("第 3 批：資金平衡與買進推薦", "def render_portfolio_balance"),
        ("第 3 批：盤前必讀頁", "def render_premarket_page"),
        ("第 3 批：ETF 專區頁", "def render_etf_page"),
        ("第 3 批：導覽列有「盤前必讀」", '"📰 盤前必讀", "📈 個股分析"'),
    ]
    print("\n功能是否已寫進 app.py：")
    bad = 0
    for label, key in checks:
        ok = key in src
        bad += (not ok)
        print(("✅ " if ok else "❌ ") + label)
    n_cfg = src.count("st.set_page_config(")
    print("\napp.py 行數：", len(src.splitlines()))
    if n_cfg != 1:
        print(f"❌ app.py 裡有 {n_cfg} 個 st.set_page_config(，正常只能有 1 個，檔案內容可能被重複貼了。")
        bad += 1
    else:
        print("✅ 沒有重複的程式內容（set_page_config 只出現一次）")
    if bad == 0:
        print("\n🎉 全部套用完成。下一步：把 app.py 推回 GitHub（git add -A ; git commit -m ... ; git push），Streamlit Cloud 會自動更新。")
    else:
        print(f"\n有 {bad} 項沒套用。請把上面整段輸出貼給我。")


if __name__ == "__main__":
    main()
