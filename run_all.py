# -*- coding: utf-8 -*-
"""
一鍵執行：依序套用三批修補 → 檢查語法 → 列出每個功能有沒有真的寫進 app.py。
用法（在 app.py 所在的資料夾，Codespaces 的 Terminal 裡）：  python run_all.py
"""
import os
import py_compile
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

REQUIRED = ["app.py", "wanglai_data.py", "wanglai_picks.py", "portfolio_balance.py", "etf_data.py", "premarket.py",
            "apply_patches.py", "apply_patches2.py", "apply_patches3.py"]
missing = [f for f in REQUIRED if not os.path.exists(f)]
if missing:
    print("❌ 資料夾裡缺少這些檔案（檔名要完全一致：小寫、用底線、沒有空格）：")
    for f in missing:
        print("   -", f)
    print("\n目前資料夾裡的 .py 檔：", sorted(f for f in os.listdir(".") if f.endswith(".py")))
    sys.exit(1)

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
    print(f"❌ app.py 裡有 {n_cfg} 個 st.set_page_config(，正常只能有 1 個。檔案內容可能被重複貼了（整份程式出現兩次），Streamlit 會因此直接報錯，請先把重複的部分刪掉。")
    bad += 1
else:
    print("✅ 沒有重複的程式內容（set_page_config 只出現一次）")
if bad == 0:
    print("\n🎉 全部套用完成。下一步：把 app.py 推回 GitHub（見教學），Streamlit Cloud 會自動更新。")
else:
    print(f"\n有 {bad} 項沒套用。請把上面整段輸出貼給我。")
