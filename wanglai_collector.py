# -*- coding: utf-8 -*-
"""
每週下載一次最新的集保戶股權分散表（和融資融券），存到你的電腦裡，讓「🐋 大戶籌碼」頁面可以算出週變動。

用法（在命令提示字元，先 cd 到這個檔案所在的資料夾）：
    python wanglai_collector.py          下載並儲存最新一週
    python wanglai_collector.py --list   列出目前已經存了哪幾週

同一週重複執行不會有問題，只會覆蓋同一份檔案。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wanglai_data as wl  # noqa: E402


def main():
    if "--list" in sys.argv:
        dates = wl.list_dates()
        print(f"資料夾：{wl.data_dir()}")
        print(f"已存 {len(dates)} 週：" + (", ".join(dates) if dates else "（還沒有資料）"))
        return 0

    print("開始下載集保戶股權分散表…（約需 10～60 秒）")
    res = wl.collect_latest()
    for m in res["messages"]:
        print(" -", m)
    if not res["ok"]:
        print("❌ 失敗。如果是網路或公司防火牆問題，可以改用網頁版：")
        print("   用瀏覽器開 https://opendata.tdcc.com.tw/getOD.ashx?id=1-5 下載 CSV，")
        print("   再到『🐋 大戶籌碼』頁面用「手動上傳」匯入。")
        return 1
    dates = wl.list_dates()
    print(f"✅ 已儲存資料日期 {res['date']}（{res['n_stocks']} 檔個股）。目前累積 {len(dates)} 週。")
    if len(dates) < 2:
        print("   再累積 1 週就能看到第一份「週增減」報表；累積 3 週就有「成績單」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
