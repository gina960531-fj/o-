import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import re
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 大戶籌碼資料層（wanglai_data.py 要和本檔放在同一個資料夾；缺少時只有「大戶籌碼」頁會顯示提示）
try:
    import wanglai_data as wl
except Exception:
    wl = None

# 大戶選股（wanglai_picks.py 要和本檔放在同一個資料夾；缺少時只有「大戶籌碼 → 大戶選股」分頁會顯示提示）
try:
    import wanglai_picks as wp
except Exception:
    wp = None

# 策略沙盒引擎（sandbox_engine.py 要和本檔放在同一個資料夾；缺少時只有「模擬自動交易」頁會顯示提示）
try:
    import sandbox_engine as sbe
except Exception:
    sbe = None

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
try:
    import official_quotes as oq
except Exception:
    oq = None
try:
    import price_alerts as pal
except Exception:
    pal = None
try:
    import overnight_edge as oed
except Exception:
    oed = None

# 嘗試載入爬蟲套件
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_SCRAPER = True
except ImportError:
    HAS_SCRAPER = False

def _st_version():
    try:
        return tuple(int(x) for x in st.__version__.split(".")[:2])
    except Exception:
        return (0, 0)

# 新版 Streamlit 以 width="stretch" 取代 use_container_width；舊版維持原參數，兩者都能跑
STRETCH = {"width": "stretch"} if _st_version() >= (1, 50) else {"use_container_width": True}


class _NotCached(Exception):
    pass

def cache_if_ok(ttl, is_ok=lambda r: r is not None):
    """只有成功才快取。st.cache_data 不會快取例外，所以失敗時丟例外、外層再接住回傳原值。
    fn_name 當作參數傳入，讓不同函式的快取不會互相混在一起（注意：底線開頭的參數不會參與快取鍵，所以不能用 _fn_name）。"""
    def deco(fn):
        @st.cache_data(ttl=ttl, show_spinner=False)
        def _inner(fn_name, *a, **k):
            r = fn(*a, **k)
            if not is_ok(r):
                raise _NotCached(r)
            return r
        def _outer(*a, **k):
            try:
                return _inner(fn.__name__, *a, **k)
            except _NotCached as e:
                return e.args[0]
        _outer.__name__ = fn.__name__
        return _outer
    return deco

st.set_page_config(page_title="J喜金融｜量化投資戰情室", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@500;700&display=swap');

/* ===== 底色與卡片：較深的藍灰底，白色卡片靠邊框與陰影浮起來 ===== */
.stApp {background: linear-gradient(180deg, #d3deec 0, #e2e9f3 380px, #e2e9f3 100%);}
header[data-testid="stHeader"] {background: transparent;}
.block-container {padding-top: 1.2rem; max-width: 1280px;}
h1, h2, h3 {color: #1f2a3d; font-weight: 800;}
h4 {color: #1f2a3d; border-left: 4px solid #b08d57; padding-left: 10px; margin-top: 0.4rem;}
div[data-testid="stMetric"] {
    background: #ffffff; padding: 14px 18px; border-radius: 12px;
    border: 1px solid #c5d0df; border-left: 4px solid #8fa5c4;
    box-shadow: 0 2px 8px rgba(31,42,61,0.10);
}
div[data-testid="stMetric"] label, div[data-testid="stMetricLabel"] {color: #55657b !important; font-weight: 600;}
div[data-testid="stMetricValue"] {color: #1f2a3d;}
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff; border-radius: 14px !important;
    border-color: #c5d0df !important; box-shadow: 0 2px 10px rgba(31,42,61,0.10);
}
div[data-testid="stExpander"] {background: #ffffff; border-radius: 12px; border: 1px solid #c5d0df;}
button[data-baseweb="tab"] {font-weight: 700;}

/* ===== 頂部資訊列：左邊品牌、右邊日期與盤勢狀態，單一橫排 ===== */
.jx-header {display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px;}
.jx-brand {
    display: inline-block; padding: 7px 22px 7px 16px; white-space: nowrap;
    background: #d3dae4; border: 1px solid #b4c0d0; border-radius: 8px;
    box-shadow: -6px 6px 0 #ffffff, 0 2px 5px rgba(31,42,61,0.15);
    font-family: 'Noto Serif TC', 'Songti TC', 'PMingLiU', serif; line-height: 1.1;
}
.jx-brand-j {font-size: 2.1rem; font-style: italic; font-weight: 700; color: #a67c37; margin-right: 3px;}
.jx-brand-name {font-size: 1.65rem; font-weight: 700; color: #6f675b; letter-spacing: 0.16em;}
.jx-brand-sub {display: inline-block; margin-left: 14px; font-size: 0.68rem; letter-spacing: 0.38em; color: #8c8579;}
.jx-status {display: flex; align-items: center; gap: 10px; white-space: nowrap;}
.jx-date {color: #55657b; font-size: 0.95rem; font-weight: 600;}

/* ===== 頂部導覽卡片：白底、極細邊框、柔和陰影；首頁按鈕與各分組下拉在同一水平線 ===== */
.st-key-jx_topnav {
    background: #ffffff; padding: 8px 12px; margin: 0 0 18px 0;
    border: 1px solid #c5d0df; border-radius: 14px; box-shadow: 0 2px 10px rgba(31,42,61,0.08);
}
.st-key-jx_topnav div[data-testid="stHorizontalBlock"] {flex-wrap: wrap; gap: 0.6rem; align-items: center;}
.st-key-jx_topnav [data-testid="stColumn"], .st-key-jx_topnav [data-testid="column"] {min-width: 150px; flex: 1 1 150px;}
.st-key-jx_topnav div[data-testid="stSelectbox"], .st-key-jx_topnav div[data-testid="stButton"] {margin-bottom: 0;}
.st-key-jx_topnav div[data-baseweb="select"] > div,
.st-key-jx_topnav button {
    background: #f1f4f9 !important; border: 1px solid #d3dbe7 !important; border-radius: 10px !important;
    min-height: 42px; font-weight: 700; color: #1f2a3d !important; white-space: nowrap; box-shadow: none !important;
}
.st-key-jx_topnav div[data-baseweb="select"] > div:hover, .st-key-jx_topnav button:hover {border-color: #8fa5c4 !important;}
.st-key-jx_topnav button:focus, .st-key-jx_topnav button:active {outline: none !important; box-shadow: none !important;}
.st-key-jx_topnav div[data-baseweb="select"] * {color: #1f2a3d;}
.st-key-jx_topnav button[kind="primary"], .st-key-jx_topnav button[data-testid="stBaseButton-primary"] {
    background: #2f4064 !important; border-color: #2f4064 !important; color: #ffffff !important;
}
.st-key-jx_topnav button[kind="primary"] p, .st-key-jx_topnav button[data-testid="stBaseButton-primary"] p {color: #ffffff !important;}
.st-key-jx_topnav div[data-testid="stSelectbox"] label {display: none;}
/* 隱藏下拉選單裡的「清除（叉叉）」按鈕，避免誤按；目前頁面會自動維持顯示 */
.st-key-jx_topnav [aria-label="Clear value"], .st-key-jx_topnav [title="Clear value"],
.st-key-jx_topnav [data-testid="stSelectboxClearButton"] {display: none !important;}

/* ===== 燈號膠囊：色彩比之前更飽和一點，仍維持莫蘭迪的柔和感 ===== */
.qr-pill {
    display: inline-block; padding: 3px 11px; border-radius: 999px;
    font-size: 0.85em; font-weight: 700; margin: 1px 2px;
}
.qr-pill-green  {background: #cfe7d8; color: #245c40;}
.qr-pill-yellow {background: #f6e6b8; color: #7a5d12;}
.qr-pill-red    {background: #f0cccc; color: #8f3535;}
.qr-pill-gray   {background: #d9e0ea; color: #44505f;}
</style>
""", unsafe_allow_html=True)

def pill(text, level="gray"):
    """柔和燈號膠囊：level = green(多方/獲利/續抱) / yellow(觀望/接近關卡) / red(停損/偏空/虧損) / gray(中性)"""
    return f'<span class="qr-pill qr-pill-{level}">{text}</span>'

# ==========================================
# 本機持久化儲存（觀察清單 / 策略日誌）
# 寫在執行這支程式的電腦本機硬碟上。若部署在會定期重置磁碟的雲端環境（例如某些免費雲端平台），
# 重新部署後這些檔案可能會消失；本機或自己的伺服器上長期執行則沒有這個問題。
# ==========================================
import json

DATA_DIR = os.path.join(os.path.expanduser("~"), ".quant_radar_data")

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
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal.csv")
JOURNAL_COLUMNS = ["存入時間", "代號", "名稱", "分數", "分數區間", "方向", "存入時股價",
                   "參考買價", "近端停損", "第一停利", "第二停利", "預計天數(歷史平均)"]

def _ensure_data_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        return True
    except Exception:
        return False

def load_watchlist():
    if _ensure_data_dir() and os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []

def get_watchlist():
    if "_watchlist" not in st.session_state:
        st.session_state["_watchlist"] = load_watchlist()
    return st.session_state["_watchlist"]

def touch_watchlist(ticker, max_items=30):
    """個股分析每次成功載入一檔股票時呼叫：加到清單最前面，存檔，供其他模式讀取。"""
    wl = get_watchlist()
    wl = [t for t in wl if t != ticker]
    wl.insert(0, ticker)
    wl = wl[:max_items]
    st.session_state["_watchlist"] = wl
    if _ensure_data_dir():
        try:
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(wl, f, ensure_ascii=False)
        except Exception:
            pass
    return wl

def remove_from_watchlist(ticker):
    wl = [t for t in get_watchlist() if t != ticker]
    st.session_state["_watchlist"] = wl
    if _ensure_data_dir():
        try:
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(wl, f, ensure_ascii=False)
        except Exception:
            pass

def load_journal():
    if _ensure_data_dir() and os.path.exists(JOURNAL_FILE):
        try:
            return pd.read_csv(JOURNAL_FILE, parse_dates=["存入時間"])
        except Exception:
            pass
    return pd.DataFrame(columns=JOURNAL_COLUMNS)

def append_journal_entry(row: dict):
    df = load_journal()
    new_row = pd.DataFrame([row])
    df = pd.concat([df, new_row], ignore_index=True)
    if _ensure_data_dir():
        try:
            df.to_csv(JOURNAL_FILE, index=False)
            return True
        except Exception:
            return False
    return False

def delete_journal_entries(idx_list):
    df = load_journal()
    df = df.drop(index=idx_list).reset_index(drop=True)
    if _ensure_data_dir():
        try:
            df.to_csv(JOURNAL_FILE, index=False)
        except Exception:
            pass
    return df

def merge_watchlist(tickers, max_items=30):
    """匯入觀察清單用：把一批代號合併進現有清單最前面（新匯入的優先），存檔。"""
    wl = get_watchlist()
    merged = list(dict.fromkeys(list(tickers) + wl))[:max_items]
    st.session_state["_watchlist"] = merged
    if _ensure_data_dir():
        try:
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False)
        except Exception:
            pass
    return merged

def import_journal_rows(new_df):
    """匯入日誌用：把上傳的紀錄接到現有日誌後面，存檔；回傳成功合併的筆數。"""
    existing = load_journal()
    combined = pd.concat([existing, new_df], ignore_index=True)
    if _ensure_data_dir():
        try:
            combined.to_csv(JOURNAL_FILE, index=False)
            return len(new_df)
        except Exception:
            return 0
    return 0

PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.csv")

def load_portfolio():
    """
    欄位：代號, 股數, 均價, 方向(Long/Short), 備註。讀不到檔案或壞檔時回傳空表，不會讓整頁掛掉。
    代號強制用字串讀取（dtype=str）——否則 pandas 會把「2330」猜成數字存回「2330.0」，
    之後拿去組 yfinance 代號（2330.0.TW）會整個抓不到股價。
    「方向」欄位是後來加的：讀到舊檔案（沒有這欄）時自動補 Long，不會讓舊資料壞掉或消失。
    """
    if _ensure_data_dir() and os.path.exists(PORTFOLIO_FILE):
        try:
            df = pd.read_csv(PORTFOLIO_FILE, dtype={"代號": str})
            for col in ["代號", "股數", "均價", "方向", "備註", "標籤"]:
                if col not in df.columns:
                    df[col] = "Long" if col == "方向" else ""
            df["代號"] = df["代號"].astype(str).str.strip()
            df["方向"] = df["方向"].fillna("Long").replace("", "Long")
            df["標籤"] = df["標籤"].fillna("")
            return df[["代號", "股數", "均價", "方向", "備註", "標籤"]]
        except Exception:
            pass
    return pd.DataFrame(columns=["代號", "股數", "均價", "方向", "備註", "標籤"])

def save_portfolio(df):
    if not _ensure_data_dir():
        return False
    try:
        df.to_csv(PORTFOLIO_FILE, index=False)
        return True
    except Exception:
        return False

def upsert_portfolio_position(code, shares, avg_cost, direction="Long", note="", tags=""):
    """新增持股；若代號已存在，用新的股數/均價/方向/標籤覆蓋（代表你更新了這筆部位）。"""
    df = load_portfolio()
    df = df[df["代號"].astype(str) != str(code)]
    new_row = pd.DataFrame([{"代號": str(code), "股數": shares, "均價": avg_cost, "方向": direction, "備註": note, "標籤": tags}])
    df = pd.concat([df, new_row], ignore_index=True)
    save_portfolio(df)
    return df

def delete_portfolio_positions(codes):
    df = load_portfolio()
    df = df[~df["代號"].astype(str).isin([str(c) for c in codes])].reset_index(drop=True)
    save_portfolio(df)
    return df

AUTOTRADE_STATE_FILE = os.path.join(DATA_DIR, "autotrade_state.json")
AUTOTRADE_LOG_FILE = os.path.join(DATA_DIR, "autotrade_log.csv")

def load_autotrade_state():
    """
    虛擬帳戶狀態：{cash: 現金, positions: {代號: {shares, avg_cost, entry_date}}}。
    完全是模擬資料，跟「💼 投資組合管理」裡你手動輸入的真實持股分開存放，不會互相污染。
    """
    default = {"cash": 0.0, "positions": {}, "initialized": False}
    if _ensure_data_dir() and os.path.exists(AUTOTRADE_STATE_FILE):
        try:
            with open(AUTOTRADE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "cash" in data:
                return {**default, **data}
        except Exception:
            pass
    return default

def save_autotrade_state(state):
    if not _ensure_data_dir():
        return False
    try:
        with open(AUTOTRADE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        return True
    except Exception:
        return False

def append_autotrade_log(rows):
    """rows: list[dict]，append 進虛擬交易紀錄 CSV。"""
    if not rows or not _ensure_data_dir():
        return
    try:
        new_df = pd.DataFrame(rows)
        if os.path.exists(AUTOTRADE_LOG_FILE):
            old = pd.read_csv(AUTOTRADE_LOG_FILE, dtype={"代號": str})
            new_df = pd.concat([old, new_df], ignore_index=True)
        new_df.to_csv(AUTOTRADE_LOG_FILE, index=False)
    except Exception:
        pass

def load_autotrade_log():
    if _ensure_data_dir() and os.path.exists(AUTOTRADE_LOG_FILE):
        try:
            return pd.read_csv(AUTOTRADE_LOG_FILE, dtype={"代號": str})
        except Exception:
            pass
    return pd.DataFrame(columns=["時間", "代號", "名稱", "動作", "股數", "價格", "金額", "原因"])

def reset_autotrade(initial_capital):
    state = {"cash": float(initial_capital), "positions": {}, "initialized": True, "initial_capital": float(initial_capital)}
    save_autotrade_state(state)
    if _ensure_data_dir() and os.path.exists(AUTOTRADE_LOG_FILE):
        try:
            os.remove(AUTOTRADE_LOG_FILE)
        except Exception:
            pass
    return state

def evaluate_single_stock(tk, directory=None):
    """給模擬自動交易的『賣出檢查』用：不套任何篩選條件，單純回報這檔股票現在的分數與現價。"""
    try:
        info, df, _ = load_stock_data(tk)
        if df is None or df.empty or len(df) < 40:
            return None
        df_ind = compute_indicators(df)
        latest, prev = df_ind.iloc[-1], df_ind.iloc[-2]
        k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
        score = compute_score(latest, prev, k_name, patterns=None)
        name = resolve_display_name(tk, tk.split(".")[0], info, directory)
        prev_close = float(prev['Close'])
        pct_chg = (latest['Close'] - prev_close) / prev_close * 100 if prev_close else None
        return dict(price=float(latest['Close']), score=score, name=name, prev_close=prev_close, pct_chg=pct_chg)
    except Exception:
        return None

def size_virtual_position(cash_available, risk_base_capital, risk_pct, buy_price, stop_price):
    """跟🧮部位試算機同一套風控邏輯：用「願意承受的虧損%」反推股數，並用現有虛擬現金封頂。"""
    risk_per_share = buy_price - stop_price
    if risk_per_share <= 0 or buy_price <= 0:
        return 0
    risk_amount = risk_base_capital * (risk_pct / 100.0)
    raw_shares = risk_amount / risk_per_share
    max_affordable = cash_available / buy_price
    return max(int(min(raw_shares, max_affordable)), 0)

def run_autotrade_cycle(state, pool, streak_map, directory, risk_pct=2.0, entry_threshold=40,
                        exit_threshold=0, max_positions=5, min_rr=1.5):
    """
    執行『一次』自動配置判斷（不是背景常駐、只有被呼叫的這一刻才會動作）：
    1. 先檢查目前持倉：跌破進場當時凍結的停損價、漲過第一/第二停利、或分數轉弱到出場門檻 → 自動賣出。
    2. 再用現有候選股評分邏輯掃一次股池，對還沒持有、分數達門檻、風報比合格的標的，依風控比例自動買進。
    回傳：更新後的 state、以及這次動作的紀錄列表（可能是空的，代表這次沒有任何買賣）。
    """
    positions = dict(state.get("positions", {}))
    cash = float(state.get("cash", 0.0))
    risk_base = float(state.get("initial_capital", cash)) or cash  # 風險%永遠用「一開始設定的本金」換算，不隨損益浮動，才不會越虧風險胃口越小的詭異循環
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    logs = []

    # ---- 1. 賣出檢查：只看目前持倉，不套任何篩選條件 ----
    for tk in list(positions.keys()):
        pos = positions[tk]
        ev = evaluate_single_stock(tk, directory)
        if ev is None:
            continue
        price = ev['price']
        reason = None
        if price <= pos['stop_ref']:
            reason = f"跌破進場時設定的停損價 ${pos['stop_ref']:.2f}"
        elif price >= pos.get('target2_ref', float('inf')):
            reason = f"漲過第二停利 ${pos['target2_ref']:.2f}"
        elif price >= pos.get('target1_ref', float('inf')):
            reason = f"漲過第一停利 ${pos['target1_ref']:.2f}"
        elif ev['score'] <= exit_threshold:
            reason = f"技術面轉弱（分數降到 {ev['score']}）"
        if reason:
            proceeds = price * pos['shares']
            cash += proceeds
            pnl = (price - pos['avg_cost']) * pos['shares']
            logs.append({"時間": now, "代號": tk.split(".")[0], "名稱": pos.get('name', tk), "動作": "🔴 自動賣出",
                        "股數": pos['shares'], "價格": round(price, 2), "金額": round(proceeds, 0),
                        "原因": reason + f"（損益 ${pnl:+,.0f}）"})
            del positions[tk]

    # ---- 2. 買進檢查：掃一次候選股池，排名由高到低，額度夠、還沒持有就買 ----
    if len(positions) < max_positions and cash > 0:
        candidates = scan_candidates(pool, streak_map, directory=directory, min_rr=min_rr)
        for c in candidates:
            if len(positions) >= max_positions or cash <= 0:
                break
            tk = c['ticker']
            if tk in positions or c['composite'] < entry_threshold:
                continue
            buy_price, stop = c['buy_price'], c['stop']
            shares = size_virtual_position(cash, risk_base, risk_pct, buy_price, stop)
            if shares <= 0:
                continue
            cost = shares * buy_price
            cash -= cost
            positions[tk] = dict(shares=shares, avg_cost=buy_price, entry_date=now, name=c['name'],
                                 stop_ref=stop, target1_ref=c['target1'], target2_ref=c['target2'])
            logs.append({"時間": now, "代號": c['code'], "名稱": c['name'], "動作": "🟢 自動買進",
                        "股數": shares, "價格": round(buy_price, 2), "金額": round(cost, 0),
                        "原因": f"綜合分數 {c['composite']}，風報比 1:{c['rr']:.1f}" if c['rr'] else f"綜合分數 {c['composite']}"})

    new_state = {**state, "cash": cash, "positions": positions}
    return new_state, logs

def to_excel_bytes(df):
    """把 DataFrame 轉成 Excel (.xlsx) 的位元組資料；本機沒裝 openpyxl 時回傳 None，呼叫端退回純 CSV 即可。"""
    try:
        import io
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="data")
        return buf.getvalue()
    except Exception:
        return None


TAG_OPTIONS = ["🟢 長線存股", "⚡ 短線動能", "🔥 AI 核心", "🛡️ 防禦型", "🚀 題材股", "💰 高股息", "🌊 景氣循環"]

INDUSTRY_MAP = {
    "3711.TW": {"name": "日月光投控", "target_pe": 14},
    "2330.TW": {"name": "台積電", "target_pe": 22},
    "2303.TW": {"name": "聯電", "target_pe": 12},
    "2454.TW": {"name": "聯發科", "target_pe": 18},
    "2603.TW": {"name": "長榮", "target_pe": 8}
}

# ==========================================
# 公司介紹與產業報告資料庫
# 只放「結構性、長期穩定」的資訊（業務、流程、產業鏈位置、該看的指標）。
# 市佔率、營收等會變動的數字請以公司法說會與公開資訊觀測站為準。
# 想新增公司：複製任一筆，改成自己的代號與內容即可。
# ==========================================
SEMI_CHAIN = ["材料 / 設備 / EDA·IP", "IC 設計", "晶圓製造", "封裝測試", "系統廠 / 終端品牌"]
SHIP_CHAIN = ["造船 / 燃油 / 貨櫃", "航運公司", "港口 / 碼頭 / 貨代", "貨主 / 進口商"]

COMPANY_PROFILES = {
    "2330.TW": {
        "tagline": "全球最大的專業晶圓代工廠：替 IC 設計公司「代工製造晶片」。",
        "category": "半導體｜晶圓代工", "founded": "1987",
        "business": "採「純晶圓代工」模式：自己不做品牌晶片，專心替客戶製造，因此客戶不必擔心被搶生意，這是它長期吸引各大 IC 設計公司的關鍵。"
                    "業務涵蓋最先進的邏輯製程、成熟與特殊製程，並延伸到先進封裝（例如 CoWoS）等後段服務。",
        "chain": SEMI_CHAIN, "me": 2,
        "flow": ["客戶（IC 設計公司）完成晶片設計並交付", "製作光罩（把電路圖轉成曝光用的底片）",
                 "在矽晶圓上反覆進行「沉積 → 微影 → 蝕刻 → 摻雜」數百道工序，逐層蓋出電路",
                 "晶圓針測（挑出良品與壞品）", "先進封裝與測試（部分自行處理，部分交給封測廠）", "出貨給客戶，再流向系統廠與終端產品"],
        "upstream": ["半導體設備：ASML、Applied Materials、Lam Research、Tokyo Electron 等", "矽晶圓：信越、SUMCO、環球晶等",
                     "光阻液、特殊氣體與化學品", "EDA 軟體與 IP 授權：Synopsys、Cadence、Arm 等"],
        "downstream": ["IC 設計公司：Apple、NVIDIA、AMD、Qualcomm、Broadcom、聯發科等", "終端應用：智慧型手機、AI 伺服器、PC、車用、網通"],
        "watch": ["月營收（每月 10 日前後公布）", "先進製程與先進封裝的產能與稼動率", "法說會的毛利率與資本支出指引", "AI 加速器相關需求（帶動先進封裝）", "美元對台幣匯率"],
        "risks": ["地緣政治與供應鏈在地化壓力", "客戶集中度高", "資本支出龐大，自由現金流可能因擴廠而為負（這也是財務體質頁看到負值的常見原因）", "海外新廠的折舊與成本可能壓抑毛利率", "電力、水資源等營運條件"],
        "competitors": ["Samsung Foundry", "Intel Foundry", "中芯國際（成熟製程）"],
        "overview": "半導體產業鏈分工細緻：設計、製造、封測各自專業化。晶圓代工位在中游，是整條鏈中資本密集度與技術門檻最高的一環，先進製程幾乎需要百億美元級的投資，形成很高的進入障礙。",
        "cycle": "半導體有明顯的庫存週期：終端需求轉弱 → 客戶砍單去庫存 → 稼動率下滑 → 需求回溫。但先進製程因 AI 與高效能運算需求，景氣波動通常小於成熟製程。",
        "trends": ["AI 與高效能運算推升先進製程與先進封裝需求", "各國推動半導體在地製造，帶動海外設廠", "製程微縮越來越昂貴，能負擔的玩家越來越少"],
    },
    "2303.TW": {
        "tagline": "專注成熟與特殊製程的晶圓代工廠，走「多元、穩定」路線。",
        "category": "半導體｜晶圓代工（成熟／特殊製程）", "founded": "1980",
        "business": "不追逐最前端製程，聚焦於成熟製程與特殊製程（如電源管理、顯示驅動、微控制器、通訊與感測相關晶片）。"
                    "產品應用面廣、單一客戶依賴度較低，價格波動通常比先進製程小，客戶黏著度高。",
        "chain": SEMI_CHAIN, "me": 2,
        "flow": ["客戶交付設計並導入製程平台", "製作光罩", "在 8 吋或 12 吋晶圓上逐層製作電路", "晶圓針測", "交給封測廠（如日月光）封裝測試", "出貨至各類終端應用"],
        "upstream": ["半導體設備與零組件供應商", "矽晶圓供應商", "化學品與特殊氣體", "EDA 與 IP 授權"],
        "downstream": ["中小型 IC 設計公司（顯示驅動、電源管理、MCU、網通等）", "部分 IDM 大廠的委外訂單", "終端：消費電子、車用、工控、通訊"],
        "watch": ["產能稼動率", "晶圓代工報價與產品組合", "車用與工控占比（需求較穩定）", "客戶庫存去化情況", "中國成熟製程擴產對價格的影響"],
        "risks": ["中國成熟製程大量擴產可能引發價格競爭", "景氣循環與客戶庫存調整", "資本密集，折舊壓力", "技術升級速度不及先進製程廠"],
        "competitors": ["GlobalFoundries", "中芯國際、華虹", "世界先進、力積電"],
        "overview": "成熟製程（約 28 奈米以上）支撐大量的日常電子產品，需求面廣但技術差異較小，競爭重點在成本、產能配置與客戶關係，近年也因各國供應鏈安全考量而受到重視。",
        "cycle": "成熟製程景氣通常受消費電子與工控庫存影響較大；供給端則看各家擴產節奏，供過於求時容易出現報價壓力。",
        "trends": ["車用與工控電子化帶來長期需求", "客戶偏好「非紅供應鏈」的多元供貨來源", "特殊製程的差異化成為擺脫價格戰的關鍵"],
    },
    "2454.TW": {
        "tagline": "台灣最大的 IC 設計公司，自己不蓋廠，專心設計晶片。",
        "category": "半導體｜IC 設計（Fabless）", "founded": "1997",
        "business": "設計手機、智慧電視、Wi-Fi 與藍牙、智慧家庭、車用等各類系統單晶片（SoC），並積極布局客製化晶片等新領域。"
                    "商業模式是「輕資產」：設計完成後委託晶圓代工廠製造、封測廠封裝，自己專注研發與行銷。",
        "chain": SEMI_CHAIN, "me": 1,
        "flow": ["市場調查與規格定義", "架構與電路設計（使用 EDA 工具與授權 IP，如 Arm）", "模擬驗證", "定案送交晶圓代工廠（Tape-out）", "晶圓製造與封裝測試", "出貨給品牌廠，並提供軟體與參考設計支援"],
        "upstream": ["晶圓代工：台積電、聯電等", "封裝測試：日月光等", "EDA 軟體：Synopsys、Cadence", "IP 授權：Arm 等"],
        "downstream": ["手機品牌：小米、OPPO、vivo、三星等", "電視、家電、網通品牌", "車廠與一線車用供應商"],
        "watch": ["法說會的毛利率與營收展望", "旗艦與中階手機晶片的出貨動能", "新領域（車用、客製化晶片）的占比", "終端庫存週期", "先進製程成本上升的影響"],
        "risks": ["手機市場成熟、競爭激烈（Qualcomm、Apple 自研晶片等）", "對中國品牌客戶依賴度高，受政策與出口管制影響", "先進製程流片成本越來越高", "研發費用龐大"],
        "competitors": ["Qualcomm", "Samsung Exynos", "紫光展銳", "Broadcom、Marvell（網通與客製化晶片）"],
        "overview": "IC 設計位在半導體鏈的最上游之一，附加價值高、資本支出低，但仰賴晶圓代工產能與 IP 生態，勝負取決於研發效率與產品組合。",
        "cycle": "受終端消費需求與通路庫存影響明顯；新產品換代週期與高階化程度，決定毛利率高低。",
        "trends": ["邊緣 AI 帶動手機、PC 與家電晶片規格升級", "客製化晶片（ASIC）需求增加", "車用電子成為新成長動能"],
    },
    "3711.TW": {
        "tagline": "全球最大的半導體封裝與測試（OSAT）廠：晶片製造後的最後一哩路。",
        "category": "半導體｜封裝測試", "founded": "1984（日月光；2018 年與矽品合併組成投控）",
        "business": "核心業務是封裝與測試：把晶圓切成一顆顆晶片，保護起來並接出腳位，再做功能測試。"
                    "旗下環旭電子（USI）另提供電子製造服務（EMS）與系統級封裝（SiP）模組。先進封裝（如覆晶、扇出型、2.5D/3D、SiP）附加價值較高。",
        "chain": SEMI_CHAIN, "me": 3,
        "flow": ["接收晶圓代工廠送來的晶圓並檢驗", "晶圓研磨與切割", "黏晶（把晶片固定在基板上）", "打線或覆晶（把晶片與基板電路連通）", "封膠保護", "植球、電鍍等後段處理", "最終功能測試（FT）", "出貨給客戶或系統廠"],
        "upstream": ["晶圓代工廠（晶圓來源）", "封裝材料：基板、導線架、封裝膠、金屬線材", "設備：打線機、測試機等"],
        "downstream": ["IC 設計公司與 IDM 大廠", "終端：手機、伺服器、車用、穿戴裝置等"],
        "watch": ["先進封裝與測試的營收占比", "產能稼動率", "資本支出規模", "客戶庫存調整狀況", "環旭電子的毛利與訂單", "美元匯率"],
        "risks": ["景氣循環與客戶砍單", "資本密集，折舊與資本支出壓力", "與晶圓代工廠自建先進封裝之間既合作又競爭", "同業競爭（Amkor、長電科技、力成等）"],
        "competitors": ["Amkor", "長電科技（JCET）", "力成", "通富微電"],
        "overview": "封測位在半導體鏈的後段，傳統封裝技術門檻較低、競爭激烈；先進封裝隨著晶片走向「小晶片組合」而重要性提升，成為封測廠提高單價與毛利的方向。",
        "cycle": "封測景氣通常落後於終端需求變化，稼動率是觀察重點；先進封裝比例提高有助降低景氣波動。",
        "trends": ["先進封裝成為性能提升的關鍵環節", "AI 晶片需求帶動測試與封裝需求", "車用與高效能運算提高長期需求"],
    },
    "2603.TW": {
        "tagline": "台灣三大貨櫃航運公司之一：把貨櫃從 A 港運到 B 港，賺運費。",
        "category": "航運｜貨櫃班輪", "founded": "1968",
        "business": "以貨櫃船在固定航線上定期營運（班輪）。營收大致等於「運量 × 運價」，其中運價高度波動，會隨供需與市場事件大幅起落。"
                    "客戶分為簽長約的合約客戶與依市價成交的現貨客戶。透過航運聯盟與同業共享艙位、優化航線與船隊利用率。",
        "chain": SHIP_CHAIN, "me": 1,
        "flow": ["貨主或貨運承攬業者訂艙", "內陸拖運貨櫃至港口", "貨櫃進場、堆放並完成通關文件", "裝上貨櫃船", "海上運送（主要航線：亞洲—北美、亞洲—歐洲等）", "抵達目的港卸船、轉運或清關", "送達收貨人"],
        "upstream": ["造船廠（新船訂單）", "燃油（艙底油）供應", "貨櫃製造與租賃", "港口與碼頭營運商"],
        "downstream": ["貨主：製造商、零售商、電商", "貨運承攬業（貨代）", "終端：消費品、電子、家具、服飾等各類貨物"],
        "watch": ["SCFI、CCFI 等運價指數", "全球貨櫃船運力與新船交付量（供給面）", "各主要航線運量與零售庫存（需求面）", "航道事件（如紅海、蘇伊士運河）", "燃油價格", "貿易政策與關稅變化", "每月營收"],
        "risks": ["運價週期性大幅波動，獲利起伏劇烈", "新船大量交付造成運力過剩", "地緣事件對運價與成本影響方向不一", "貿易政策與關稅變化", "環保法規（減碳）推升成本與造船需求"],
        "competitors": ["Maersk", "MSC", "CMA CGM", "中遠海運（COSCO）", "Hapag-Lloyd", "ONE、陽明、萬海"],
        "overview": "貨櫃航運是典型的資本密集、強週期產業：船隊運力（供給）調整緩慢，而貨運需求（需求）受全球貿易與消費影響快速變化，兩者錯配時運價會劇烈波動。",
        "cycle": "運價由「運力供給 vs 貨運需求」決定。突發事件（疫情、航道受阻）常造成運價急漲，反之新船大量交付、需求轉弱時運價可能大跌。獲利高峰與低谷落差很大，不宜用單一時點的本益比評價。",
        "trends": ["航運聯盟調整航線與運力配置", "低碳燃料與環保規範影響新造船", "供應鏈區域化改變貿易流向"],
    },
}

# ==========================================
# 快速跳轉處理：必須在側邊欄的 app_mode_radio 這個 widget 被實例化「之前」處理，
# 否則會噴 StreamlitWidgetAlreadyInstantiatedError（widget 已實例化後不能直接改它的 session_state）。
# 其他頁面要跳轉時，只設定 _pending_app_mode / _pending_stock_code 這兩個中介旗標再 st.rerun()，
# 真正寫進 app_mode_radio / stock_select_code 的動作統一在這裡做。
# ==========================================
if "_pending_app_mode" in st.session_state:
    st.session_state["app_mode_radio"] = st.session_state.pop("_pending_app_mode")
    pending_code = st.session_state.pop("_pending_stock_code", None)
    if pending_code:
        st.session_state["stock_search_query"] = pending_code
        st.session_state["stock_select_code"] = pending_code

# ==========================================
# 頂部導覽：J喜金融 品牌列 + 分組下拉選單
# 八個功能分成四組下拉（再加獨立的「戰情室」首頁按鈕）。
# 目前頁面存在 session_state["app_mode_radio"]；下拉選單用 on_change 回呼更新它，
# 每次執行最前面再把各下拉的顯示值同步成目前頁面（所在的組顯示頁名，其餘組顯示組名）。
# ==========================================
HOME_MODE = "🏠 戰情室首頁"
NAV_GROUPS = [
    ("search",   "🔍 選股雷達", ["🔥 資金熱力圖", "🐋 大戶籌碼", "⭐ 每日候選股", "🗂 觀察清單掃描"]),
    ("research", "📈 研究室",   ["📰 盤前必讀", "📈 個股分析", "📡 總經雷達", "📊 ETF 專區"]),
    ("desk",     "💼 操盤室",   ["💼 投資組合管理", "🔔 到價通知", "🤖 模擬自動交易"]),
    ("academy",  "🎓 覆盤學院", ["📝 策略日誌", "📚 教學庫"]),
]
ALL_MODES = [HOME_MODE] + [m for _, _, ms in NAV_GROUPS for m in ms]

if st.session_state.get("app_mode_radio") not in ALL_MODES:
    st.session_state["app_mode_radio"] = HOME_MODE

def _topnav_pick(gid):
    chosen = st.session_state.get(f"topnav_{gid}")
    if chosen in ALL_MODES:
        st.session_state["app_mode_radio"] = chosen

def _topnav_home():
    st.session_state["app_mode_radio"] = HOME_MODE

app_mode = st.session_state["app_mode_radio"]
for _gid, _gtitle, _gmodes in NAV_GROUPS:       # 下拉顯示值同步（必須在 widget 建立之前）
    st.session_state[f"topnav_{_gid}"] = app_mode if app_mode in _gmodes else None

def market_status():
    """台北時間的簡易盤勢狀態（只判斷週末與一般交易時段，不含國定假日）。"""
    now = pd.Timestamp.now(tz="Asia/Taipei")
    if now.weekday() >= 5:
        return "週末休市", "gray"
    hhmm = now.hour * 100 + now.minute
    if 900 <= hhmm <= 1330:
        return "盤中", "green"
    return ("盤前" if hhmm < 900 else "已收盤"), "yellow"

_ms_text, _ms_level = market_status()
st.markdown(
    '<div class="jx-header"><div class="jx-brand"><span class="jx-brand-j">J</span><span class="jx-brand-name">喜金融</span>'
    '<span class="jx-brand-sub">量化投資戰情室</span></div>'
    f'<div class="jx-status"><span class="jx-date">📅 {pd.Timestamp.now(tz="Asia/Taipei").strftime("%Y/%m/%d")}</span>'
    f'{pill(_ms_text, _ms_level)}</div></div>', unsafe_allow_html=True)

try:
    _nav_box = st.container(key="jx_topnav")
except TypeError:                                # 舊版 Streamlit 不支援 container(key=)：退回一般卡片框
    _nav_box = st.container(border=True)

def _slot(gid):
    try:
        return st.container(key=f"jx_slot_{gid}")
    except TypeError:
        return st.container()

with _nav_box:
    _nc = st.columns([1, 1.4, 1.4, 1.4, 1.4])
    _nc[0].button("🏠 戰情室", key="topnav_home", on_click=_topnav_home,
                  type="primary" if app_mode == HOME_MODE else "secondary", **STRETCH)
    for _i, (_gid, _gtitle, _gmodes) in enumerate(NAV_GROUPS, start=1):
        with _nc[_i]:
            with _slot(_gid):
                st.selectbox(_gtitle, _gmodes, index=None, placeholder=f"{_gtitle} ▾", key=f"topnav_{_gid}",
                             on_change=_topnav_pick, args=(_gid,), label_visibility="collapsed")

_active_gid = next((g for g, _, ms in NAV_GROUPS if app_mode in ms), None)
if _active_gid:                                   # 目前所在的那一組：與首頁按鈕同款的深藍底白字
    st.markdown(f"<style>.st-key-jx_slot_{_active_gid} div[data-baseweb='select'] > div {{background:#2f4064 !important; border-color:#2f4064 !important;}}"
                f".st-key-jx_slot_{_active_gid} div[data-baseweb='select'] * {{color:#ffffff !important; fill:#ffffff !important;}}</style>",
                unsafe_allow_html=True)

# ==========================================
# 繪圖函數：基礎K線與進階型態 (教學區用)
# ==========================================
def draw_kline_illustration(k_type):
    fig = go.Figure()
    if k_type == "大陽線": o, h, l, c = 10, 20, 10, 20
    elif k_type == "大陰線": o, h, l, c = 20, 20, 10, 10
    elif k_type == "下影線 (錘子)": o, h, l, c = 17, 20, 10, 20
    elif k_type == "上影線 (避雷針)": o, h, l, c = 13, 20, 10, 10
    elif k_type == "十字線": o, h, l, c = 15, 20, 10, 15
    elif k_type == "T字線": o, h, l, c = 20, 20, 10, 20
    # 修復：go.Candlestick 不接受 line=dict(color=...) 這種寫法（該參數是用來設定線框，不是整體填色），
    # 傳入 None 時會直接噴 ValueError。移除後改用 increasing/decreasing_line_color 控制顏色即可。
    fig.add_trace(go.Candlestick(
        x=['K線'], open=[o], high=[h], low=[l], close=[c],
        increasing_line_color='red', decreasing_line_color='green'
    ))
    fig.update_layout(height=150, margin=dict(l=0, r=0, t=0, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=False, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
    return fig

def draw_pattern_illustration(pattern_type):
    fig = go.Figure()
    if pattern_type == "頭肩頂":
        fig.add_trace(go.Scatter(x=[1, 2, 3, 4, 5, 6, 7], y=[2, 6, 4, 9, 4, 6, 2], mode='lines+markers', line=dict(color='red', width=3)))
        fig.add_hline(y=4, line_dash="dash", line_color="white", annotation_text="頸線(跌破)")
    elif pattern_type == "雙重頂":
        fig.add_trace(go.Scatter(x=[1, 2, 3, 4, 5], y=[2, 8, 4, 8, 2], mode='lines+markers', line=dict(color='red', width=3)))
        fig.add_hline(y=4, line_dash="dash", line_color="white", annotation_text="頸線(跌破)")
    elif pattern_type == "圓弧頂":
        x = np.linspace(-3, 3, 20)
        fig.add_trace(go.Scatter(x=x, y=-x**2 + 10, mode='lines+markers', line=dict(color='red', width=3)))
        fig.add_hline(y=2, line_dash="dash", line_color="white", annotation_text="支撐線")
    elif pattern_type == "三角收斂":
        fig.add_trace(go.Scatter(x=[1, 3, 5], y=[8, 6, 5.5], mode='lines', line=dict(color='purple', dash='dash')))
        fig.add_trace(go.Scatter(x=[1, 3, 5], y=[2, 4, 4.5], mode='lines', line=dict(color='cyan', dash='dash')))
        fig.add_trace(go.Scatter(x=[1, 2, 3, 4, 5, 6], y=[2, 8, 4, 6, 4.5, 7], mode='lines+markers', line=dict(color='orange', width=2)))
    elif pattern_type == "箱型":
        fig.add_trace(go.Scatter(x=[1, 6], y=[8, 8], mode='lines', line=dict(color='purple', dash='dash')))
        fig.add_trace(go.Scatter(x=[1, 6], y=[2, 2], mode='lines', line=dict(color='cyan', dash='dash')))
        fig.add_trace(go.Scatter(x=[1.5, 2.5, 3.5, 4.5, 5.5], y=[3, 7, 3, 7, 3], mode='lines+markers', line=dict(color='orange', width=2)))
    fig.update_layout(height=200, margin=dict(l=0, r=0, t=0, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=False, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
    return fig

# ==========================================
# 共用函式（單股分析、多股掃描皆會用到）
# ==========================================
@st.cache_data(ttl=900, show_spinner=False)
def load_stock_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    try:
        info = stock.info
        if not isinstance(info, dict):
            info = {}
    except Exception:
        info = {}
    df = stock.history(period="2y")
    if df is not None and not df.empty:
        df = df.dropna(subset=['Close', 'High', 'Low', 'Open', 'Volume'])
    try:
        q_income = stock.quarterly_income_stmt
    except Exception:
        q_income = pd.DataFrame()
    return info, df, q_income

@cache_if_ok(900, is_ok=lambda r: r[2] == "success")
def get_taiwan_chips(stock_id):
    """回傳 (外資買賣超, 投信買賣超, 狀態)。狀態: success / disabled / failed"""
    if not HAS_SCRAPER:
        return None, None, "disabled"
    try:
        url = f"https://tw.stock.yahoo.com/quote/{stock_id}/institutional-investors"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.find_all('span', class_='Fz(16px) Fw(b)')
        if len(items) >= 2:
            raw_f = items[0].text.replace(',', '')
            raw_t = items[1].text.replace(',', '')
            f_val = int(raw_f) if raw_f.lstrip('-').isdigit() else None
            t_val = int(raw_t) if raw_t.lstrip('-').isdigit() else None
            if f_val is not None and t_val is not None:
                return f_val, t_val, "success"
        return None, None, "failed"
    except Exception:
        return None, None, "failed"

def analyze_today_kline(o, h, l, c):
    if pd.isna(o) or pd.isna(c):
        return "資料不足"
    body, tr, us, ls = abs(c - o), max(h - l, 0.001), h - max(o, c), min(o, c) - l
    if body / tr < 0.05:
        return "十字線/一字線 (盤整或反轉前兆)"
    elif c > o:
        return "陽線錘 (長下影線，支撐強)" if ls > body * 1.5 else ("上影線陽線 (遇壓)" if us > body * 1.5 else "大陽線 (買盤強)")
    else:
        return "陰線錘 (長下影線，易反轉)" if ls > body * 1.5 else ("上影線陰線 (跌勢前兆)" if us > body * 1.5 else "大陰線 (賣盤強)")

def detect_advanced_patterns(df_input):
    """
    偵測箱型 / 雙重頂等型態。
    注意：頭尾各 5 根 K 棒的峰谷判斷需要「未來」資料才能確認（i-5:i+6 為對稱窗），
    因此這裡回傳的是「已確認」型態，天生會落後最新走勢約 5 個交易日。
    另外針對最近 5 根 K 棒，加上「單邊（只看過去）」的醞釀中訊號，並明確標示未經確認。
    """
    msg_list, annotations = [], []
    if len(df_input) < 40:
        return ["資料不足"], []
    highs, lows = df_input['High'].values, df_input['Low'].values
    peak_idx, trough_idx = [], []
    for i in range(5, len(highs) - 5):
        if highs[i] == max(highs[i - 5:i + 6]): peak_idx.append(i)
        if lows[i] == min(lows[i - 5:i + 6]): trough_idx.append(i)

    recent_20 = df_input.iloc[-20:]
    if recent_20['Low'].min() > 0 and recent_20['High'].max() / recent_20['Low'].min() < 1.08:
        msg_list.append("📦 **【箱型整理】**：近期處於狹幅區間震盪，等待突破。")
        annotations.append(dict(x=recent_20.index[-10], y=recent_20['High'].max() * 1.02, text="箱型頂", showarrow=False, font=dict(color="orange")))

    if len(peak_idx) >= 2:
        p1_i, p2_i = peak_idx[-2], peak_idx[-1]
        p1, p2 = highs[p1_i], highs[p2_i]
        if p1 > 0 and abs(p1 - p2) / p1 < 0.03 and (p2_i - p1_i) > 5 and min(lows[p1_i:p2_i]) < p1 * 0.95:
            msg_list.append("⚠️ **【雙重頂 (M頭) 疑慮】(已確認)**：高檔兩次遇壓反彈失敗，注意下跌風險。")
            annotations.append(dict(x=df_input.index[p2_i], y=p2 * 1.02, text="M頭疑慮", showarrow=True, font=dict(color="red")))

    n = len(highs)
    lookback = 5
    if n >= lookback + 1:
        if highs[n - 1] == max(highs[n - 1 - lookback:n]):
            msg_list.append("🕵️ **【近期高點醞釀中，未確認】**：最新K棒創近期新高，是否形成反轉需再觀察 5 個交易日確認。")

    if not msg_list:
        msg_list.append("✅ 目前無明顯的反轉或整理型態。")
    return msg_list, annotations

def compute_indicators(df):
    df = df.copy()
    high14 = df['High'].rolling(14, min_periods=1).max()
    low14 = df['Low'].rolling(14, min_periods=1).min()
    df['WPR'] = np.where((high14 - low14) == 0, 0, (high14 - df['Close']) / (high14 - low14) * -100)

    tp = (df['High'] + df['Low'] + df['Close']) / 3
    sma_tp = tp.rolling(14, min_periods=1).mean()
    mad_tp = tp.rolling(14, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True).replace(0, np.nan)
    df['CCI'] = ((tp - sma_tp) / (0.015 * mad_tp)).fillna(0)

    df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['Resistance'] = df['High'].rolling(60, min_periods=1).max()
    df['Support'] = df['Low'].rolling(60, min_periods=1).min()

    prev_close = df['Close'].shift(1)
    tr = pd.concat([df['High'] - df['Low'], (df['High'] - prev_close).abs(), (df['Low'] - prev_close).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14, min_periods=1).mean()
    return df

# ==========================================
# ★ 核心評分邏輯：即時預測、單日回測、資金曲線回測、多股掃描共用同一套規則 ★
# patterns（型態疑慮）刻意設為可選，且不計入任何回測，
# 因為型態偵測需要用到未來K棒才能確認，直接拿來回測會有前視偏誤。
# ==========================================
def score_components(latest, prev, k_name, patterns=None):
    """回傳每一項加減分的依據，compute_score 與「為什麼是這個分數」共用同一份邏輯。"""
    parts = []
    # MACD 動能深化判定：區分「剛轉向的交叉」（訊號最強）跟「已同方向、動能增強或衰減」兩種情境，
    # 而不是只看柱狀體漲跌這麼粗略。
    if latest['Hist'] > 0:
        if prev['Hist'] <= 0:
            parts.append(("MACD 黃金交叉（柱狀體由負轉正）", 35))
        elif latest['Hist'] > prev['Hist']:
            parts.append(("MACD 柱狀體翻多且持續擴大", 25))
        else:
            parts.append(("MACD 仍偏多但動能開始縮小，留意轉弱", 5))
    elif latest['Hist'] < 0:
        if prev['Hist'] >= 0:
            parts.append(("MACD 死亡交叉（柱狀體由正轉負）", -35))
        elif latest['Hist'] < prev['Hist']:
            parts.append(("MACD 柱狀體翻空且持續擴大", -25))
        else:
            parts.append(("MACD 仍偏空但動能開始縮小，留意止跌", -5))
    if latest['WPR'] < -80: parts.append(("威廉指標進入超賣區（可能反彈）", 20))
    if latest['WPR'] > -20: parts.append(("威廉指標進入超買區（追高風險）", -20))
    if "陽" in k_name: parts.append(("今日收陽線", 15))
    if "陰" in k_name: parts.append(("今日收陰線", -15))
    if "錘" in k_name: parts.append(("出現長下影線（下方有承接）", 10))
    if latest['Close'] > latest['MA20']: parts.append(("股價在月線之上", 10))
    else: parts.append(("股價在月線之下", -10))
    if patterns:
        for p in patterns:
            if "疑慮" in p and "已確認" in p:
                parts.append(("已確認的 M 頭型態", -40))
    return parts

def compute_score(latest, prev, k_name, patterns=None):
    return sum(p for _, p in score_components(latest, prev, k_name, patterns))

def score_to_bucket(score):
    if score >= 40: return "≥40 (強勢偏多)"
    elif score >= 0: return "0~39 (溫和偏多)"
    elif score > -30: return "-29~-1 (中性偏弱)"
    else: return "≤-30 (偏空)"

def predict_next_day(latest_data, prev_data, k_name, patterns, backtest_stats=None):
    score = compute_score(latest_data, prev_data, k_name, patterns)
    bucket = score_to_bucket(score)
    current_p = latest_data['Close']

    stat_line = ""
    if backtest_stats is not None and bucket in backtest_stats.index:
        row = backtest_stats.loc[bucket]
        if row['樣本數'] >= 10:
            stat_line = f"（此分數區間歷史樣本 {int(row['樣本數'])} 次，隔日上漲機率 {row['上漲機率(%)']:.1f}%，平均報酬 {row['平均隔日報酬(%)']:.2f}%）"
        else:
            stat_line = "（此分數區間歷史樣本數過少，回測參考價值有限）"

    if score >= 40:
        direction = "技術面偏多"
        action = "趨勢偏多，可考慮分批進場，但仍需搭配停損"
        buy_price = current_p * 0.99
        color = "success"
    elif score >= 0:
        direction = "技術面溫和偏多"
        action = "逢低佈局，等待動能發動"
        buy_price = latest_data['MA20']
        color = "info"
    elif score > -30:
        direction = "技術面中性偏弱"
        action = "持續觀望，不追高"
        buy_price = latest_data['Support']
        color = "warning"
    else:
        direction = "技術面偏空"
        action = "空手觀望，避免逆勢進場"
        buy_price = latest_data['Support'] * 0.95
        color = "error"

    reminder = f"🔔 【{direction}】：綜合分數 {score}。{action}。{stat_line}"
    return direction, action, buy_price, reminder, color, score, bucket

# ==========================================
# ★ 回測引擎一：單日勝率統計 ★
# ==========================================
def vector_score(df):
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

def walk_forward_bucket_stats(df):
    """把回測期間切成前後兩半分開統計，檢查分數的鑑別力是否穩定，而非整段時間平均出來的假象。"""
    n = len(df)
    mid = n // 2
    first_half = df.iloc[:mid].reset_index(drop=True)
    second_half = df.iloc[mid:].reset_index(drop=True)
    stats1 = backtest_score_system(first_half) if len(first_half) >= 40 else pd.DataFrame()
    stats2 = backtest_score_system(second_half) if len(second_half) >= 40 else pd.DataFrame()
    period1_label = f"{df.index[0].date()} ~ {df.index[max(mid-1,0)].date()}" if hasattr(df.index[0], 'date') else "前半段"
    period2_label = f"{df.index[mid].date()} ~ {df.index[-1].date()}" if hasattr(df.index[0], 'date') and mid < n else "後半段"
    return stats1, stats2, period1_label, period2_label

# ==========================================
# ★ 回測引擎二：模擬進出場的資金曲線回測（含成本、停損、持有天數上限） ★
# 簡化假設：以收盤價成交、無滑價衝擊、不分批建倉。
# 僅用於評估評分規則的相對優劣，非真實下單環境下的績效保證。
# ==========================================
@st.cache_data(ttl=900, show_spinner=False)
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

def compute_backtest_metrics(equity_series, trades_df):
    if equity_series is None or equity_series.empty:
        return {}
    daily_ret = equity_series.pct_change().dropna()
    total_return = (equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100
    n_days = len(equity_series)
    years = n_days / 252
    cagr = ((equity_series.iloc[-1] / equity_series.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else np.nan
    running_max = equity_series.cummax()
    drawdown = equity_series / running_max - 1
    max_dd = drawdown.min() * 100
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else np.nan
    n_trades = len(trades_df)
    if n_trades > 0:
        win_rate = (trades_df['報酬率(%)'] > 0).mean() * 100
        gains = trades_df.loc[trades_df['報酬率(%)'] > 0, '報酬率(%)'].sum()
        losses = trades_df.loc[trades_df['報酬率(%)'] < 0, '報酬率(%)'].sum()
        profit_factor = (gains / abs(losses)) if losses < 0 else np.nan
    else:
        win_rate, profit_factor = np.nan, np.nan

    return {
        "總報酬率(%)": total_return, "年化報酬率(%)": cagr, "最大回撤(%)": max_dd,
        "年化Sharpe": sharpe, "交易次數": n_trades, "勝率(%)": win_rate, "獲利因子": profit_factor
    }

def fmt_pct(val): return f"{val*100:.2f}%" if pd.notnull(val) and isinstance(val, (int, float)) else "無資料"
def fmt_num(val): return f"{val:.2f}" if pd.notnull(val) and isinstance(val, (int, float)) else "無資料"
def fmt_cash(val): return f"{val / 100000000:.2f} 億" if pd.notnull(val) and isinstance(val, (int, float)) else "無資料"

# ==========================================
# ★ 功能1：大盤基準對比（Benchmark） ★
# ==========================================
BENCHMARKS = {"0050.TW（元大台灣50）": "0050.TW", "^TWII（加權指數）": "^TWII"}

@st.cache_data(ttl=900, show_spinner=False)
def get_benchmark_close(symbol):
    try:
        h = yf.Ticker(symbol).history(period="2y")
        if h is None or h.empty:
            return None
        return _norm_series(h["Close"])
    except Exception:
        return None

def align_benchmark_equity(strategy_equity, symbol):
    """把大盤收盤價對齊到策略資金曲線的日期範圍，換算成『從同一天開始、買進持有』的權益曲線。"""
    bench = get_benchmark_close(symbol)
    if bench is None or bench.empty:
        return None
    idx = pd.to_datetime(strategy_equity.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    strat = strategy_equity.copy()
    strat.index = idx.normalize()
    bench = bench.reindex(bench.index.union(strat.index)).sort_index().ffill()
    bench = bench.reindex(strat.index)
    bench = bench.dropna()
    if bench.empty:
        return None
    return bench / bench.iloc[0]


# ==========================================
# ★ 功能3：股利與殖利率估值 ★
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_dividend_summary(ticker_symbol, current_price):
    """回傳近5年年度現金股利與估算殖利率；抓不到或該股沒發股利時回傳 None。"""
    try:
        div = yf.Ticker(ticker_symbol).dividends
    except Exception:
        return None
    if div is None or div.empty:
        return None
    idx = pd.to_datetime(div.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(div.values, index=idx)
    this_year = pd.Timestamp.now().year
    by_year = s.groupby(s.index.year).sum()
    by_year = by_year[by_year.index < this_year].tail(5)  # 排除還沒發完的今年，避免低估
    if by_year.empty:
        return None
    avg_dividend = by_year.mean()
    yield_pct = (avg_dividend / current_price * 100) if current_price > 0 else np.nan
    return dict(by_year=by_year, avg_dividend=avg_dividend, yield_pct=yield_pct, years=len(by_year))


# ==========================================
# ★ 功能1：明日多空機率與相似情境分析 ★
# 完全複用既有的 score_components / backtest_score_system，只是換一種更完整的方式呈現，
# 不改動分數計算本身，所以「回測驗證」分頁的數字仍然對得上。
# ==========================================
def confidence_label(n):
    if n is None:
        return "無歷史資料可比對"
    if n >= 60:
        return f"樣本 {n} 次，統計基礎相對充分"
    if n >= 10:
        return f"樣本僅 {n} 次，數字僅供參考"
    return f"樣本僅 {n} 次，統計上不具意義"

def build_scenario_view(score, bucket, backtest_stats, comps, pattern_msgs, bias_pct):
    wr = n = None
    if backtest_stats is not None and not backtest_stats.empty and bucket in backtest_stats.index:
        wr = backtest_stats.loc[bucket, '上漲機率(%)']
        n = int(backtest_stats.loc[bucket, '樣本數'])
    bullish = [(t, p) for t, p in comps if p > 0]
    bearish = [(t, p) for t, p in comps if p < 0]
    extra_risks = []
    if pd.notna(bias_pct) and abs(bias_pct) >= 10:
        direction = "正乖離（可能過熱）" if bias_pct > 0 else "負乖離（可能過度悲觀）"
        extra_risks.append(f"股價乖離月線 {bias_pct:+.1f}%，{direction}，短線有均值回歸風險")
    for m in pattern_msgs:
        if "疑慮" in m:
            extra_risks.append(re.sub(r"[*#]", "", m).strip())
    caution = [re.sub(r"[*#]", "", m).strip() for m in pattern_msgs if "醞釀中" in m]
    return dict(wr=wr, n=n, bullish=bullish, bearish=bearish, extra_risks=extra_risks, caution=caution)


# ==========================================
# 介面共用函式（個股分析頁使用）
# ==========================================
def _fragment(func):
    """有 st.fragment（Streamlit 1.37+）就用，讓拉桿/輸入框只更新自己這一塊；舊版則退回一般函式。"""
    frag = getattr(st, "fragment", None)
    return frag(func) if frag else func

def normalize_ticker(raw):
    """只打數字就自動補 .TW，例如 2330 -> 2330.TW。"""
    t = (raw or "").strip().upper()
    if not t:
        return ""
    if "." not in t and t[:4].isdigit():
        return t + ".TW"
    return t

def load_with_fallback(ticker):
    """上市 .TW 抓不到資料時，自動改試上櫃 .TWO。"""
    info, df, q = load_stock_data(ticker)
    if (df is None or df.empty) and ticker.endswith(".TW"):
        alt = ticker[:-3] + ".TWO"
        info2, df2, q2 = load_stock_data(alt)
        if df2 is not None and not df2.empty:
            return alt, info2, df2, q2
    return ticker, info, df, q

def compute_levels(df, latest, current_price, score):
    """
    統一計算加碼／停損／停利價位，總覽、持股頁、候選股、策略日誌全部共用同一組數字。
    近端停損採「月線結構停損」與「ATR 波動度停損（現價 - 2×ATR）」兩者中較貼近現價的一個：
    兩者都是合理的停損依據，取較近的一個等於採取較保守、風險較小的停損設定。
    """
    ma20, support = latest['MA20'], latest['Support']
    ma20_stop = ma20 if ma20 < current_price else current_price * 0.95
    atr = latest.get('ATR') if hasattr(latest, 'get') else latest['ATR']
    atr_stop = (current_price - 2 * atr) if pd.notna(atr) and atr > 0 else None
    if atr_stop is not None and 0 < atr_stop < current_price:
        near_stop = max(ma20_stop, atr_stop)
    else:
        near_stop = ma20_stop
    far_stop = support if support < near_stop else near_stop * 0.9
    resistance_ref = df['High'].iloc[-61:-1].max() if len(df) > 61 else latest['Resistance']
    target1 = resistance_ref if resistance_ref > current_price else current_price * 1.05
    risk_unit = current_price - near_stop
    # 第二停利明確以 1:2 風險報酬比推算（風險單位＝現價到近端停損的距離），並確保不會比第一停利還低
    target2 = max(current_price + 2 * risk_unit, target1 * 1.05) if risk_unit > 0 else target1 * 1.08
    can_add = score >= 0 and ma20 < current_price
    rr = (target1 - current_price) / risk_unit if risk_unit > 0 else None
    return dict(ma20=ma20, near_stop=near_stop, far_stop=far_stop, target1=target1,
                target2=target2, can_add=can_add, rr=rr,
                ma20_stop=ma20_stop, atr_stop=atr_stop, atr=atr if pd.notna(atr) else None)

def signal_reading(win_rate, sample_n):
    """把「歷史勝率」翻成一句白話。"""
    if sample_n is None or sample_n < 10:
        return "樣本不足，無法判斷"
    if win_rate is None:
        return "無歷史資料"
    edge = win_rate - 50
    if abs(edge) < 5:
        return f"⚪ 過去隔天上漲機率約 {win_rate:.0f}%，接近五五波，這個分數沒有明顯優勢"
    if edge >= 15:
        return f"🟢 過去隔天上漲機率 {win_rate:.0f}%，歷史明顯偏多，仍需搭配停損"
    if edge >= 5:
        return f"🟡 過去隔天上漲機率 {win_rate:.0f}%，略偏多，優勢不大"
    if edge <= -15:
        return f"🔴 過去隔天上漲機率僅 {win_rate:.0f}%，歷史明顯偏空"
    return f"🟠 過去隔天上漲機率 {win_rate:.0f}%，略偏空"

# ==========================================
# 股票名錄（搜尋用）：內建常用名單 + 嘗試從證交所／櫃買中心抓完整名單
# 格式：代號 公司簡稱 產業別
# ==========================================
BUILTIN_STOCK_TEXT = """
1101 台泥 水泥
1102 亞泥 水泥
1216 統一 食品
1301 台塑 塑膠
1303 南亞 塑膠
1326 台化 塑膠
1402 遠東新 紡織
1476 儒鴻 紡織
1560 中砂 半導體
1590 亞德客-KY 電機機械
2002 中鋼 鋼鐵
2105 正新 橡膠
2201 裕隆 汽車
2207 和泰車 汽車
2208 台船 電機機械
2301 光寶科 電腦週邊
2303 聯電 半導體
2308 台達電 電子零組件
2317 鴻海 電腦週邊
2324 仁寶 電腦週邊
2327 國巨 電子零組件
2329 華泰 半導體
2330 台積電 半導體
2337 旺宏 半導體
2344 華邦電 半導體
2345 智邦 通信網路
2352 佳世達 電腦週邊
2353 宏碁 電腦週邊
2356 英業達 電腦週邊
2357 華碩 電腦週邊
2360 致茂 電子零組件
2376 技嘉 電腦週邊
2377 微星 電腦週邊
2379 瑞昱 半導體
2382 廣達 電腦週邊
2383 台光電 電子零組件
2395 研華 電腦週邊
2404 漢唐 電機機械
2408 南亞科 半導體
2409 友達 光電
2412 中華電 通信網路
2449 京元電子 半導體
2454 聯發科 半導體
2458 義隆 半導體
2474 可成 其他電子
2492 華新科 電子零組件
2603 長榮 航運
2606 裕民 航運
2609 陽明 航運
2615 萬海 航運
2618 長榮航 航運
2636 台驊投控 航運
2801 彰銀 金融保險
2880 華南金 金融保險
2881 富邦金 金融保險
2882 國泰金 金融保險
2883 凱基金 金融保險
2884 玉山金 金融保險
2885 元大金 金融保險
2886 兆豐金 金融保險
2887 台新新光金 金融保險
2890 永豐金 金融保險
2891 中信金 金融保險
2892 第一金 金融保險
2912 統一超 貿易百貨
3008 大立光 光電
3017 奇鋐 電腦週邊
3034 聯詠 半導體
3035 智原 半導體
3037 欣興 電子零組件
3045 台灣大 通信網路
3189 景碩 電子零組件
3231 緯創 電腦週邊
3413 京鼎 半導體
3443 創意 半導體
3481 群創 光電
3661 世芯-KY 半導體
3711 日月光投控 半導體
4904 遠傳 通信網路
4938 和碩 電腦週邊
5607 遠雄港 航運
5871 中租-KY 金融保險
5876 上海商銀 金融保險
5880 合庫金 金融保險
6196 帆宣 電機機械
6239 力成 半導體
6415 矽力*-KY 半導體
6505 台塑化 塑膠
6669 緯穎 電腦週邊
6770 力積電 半導體
8046 南電 電子零組件
8150 南茂 半導體
9904 寶成 其他
9910 豐泰 其他
6488 環球晶 半導體 OTC
5347 世界先進 半導體 OTC
3131 弘塑 半導體 OTC
3264 欣銓 半導體 OTC
5274 信驊 半導體 OTC
3680 家登 半導體 OTC
4966 譜瑞-KY 半導體 OTC
3105 穩懋 半導體 OTC
8299 群聯 半導體 OTC
5483 中美晶 半導體 OTC
0050 元大台灣50 ETF
0056 元大高股息 ETF
00878 國泰永續高股息 ETF
00919 群益台灣精選高息 ETF
00929 復華台灣科技優息 ETF
00713 元大台灣高息低波 ETF
006208 富邦台50 ETF
"""

def _parse_builtin_stocks():
    out = {}
    for line in BUILTIN_STOCK_TEXT.strip().splitlines():
        p = line.split()
        if len(p) >= 3:
            out[p[0]] = dict(name=p[1], ind=p[2], suffix=".TWO" if (len(p) > 3 and p[3] == "OTC") else ".TW")
    return out

BUILTIN_STOCKS = _parse_builtin_stocks()

# 證交所產業別代號 -> 產業簡稱
TW_INDUSTRY_CODE = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織", "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷",
    "09": "造紙", "10": "鋼鐵", "11": "橡膠", "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅",
    "17": "金融保險", "18": "貿易百貨", "20": "其他", "21": "化學", "22": "生技醫療", "23": "油電燃氣",
    "24": "半導體", "25": "電腦週邊", "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路",
    "30": "資訊服務", "31": "其他電子", "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
}

def _pick(rec, exact_keys, fuzzy_needles):
    for k in exact_keys:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k, v in rec.items():
        if any(n in k for n in fuzzy_needles) and isinstance(v, str) and v.strip():
            return v.strip()
    return None

@st.cache_data(ttl=43200, show_spinner=False)
def _fetch_live_directory():
    """從證交所／櫃買中心公開資料抓完整上市櫃名單。失敗會丟例外（不會被快取），由呼叫端退回內建名單。"""
    if not HAS_SCRAPER:
        raise RuntimeError("requests 未安裝")
    out = {}
    sources = (("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", ".TW"),
               ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", ".TWO"))
    for url, suffix in sources:
        try:
            data = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"}).json()
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for rec in data:
            if not isinstance(rec, dict):
                continue
            code = _pick(rec, ["公司代號", "SecuritiesCompanyCode", "Code"], ["代號"])
            name = _pick(rec, ["公司簡稱", "CompanyAbbreviation", "Name"], ["簡稱", "Abbreviation"])
            ind = _pick(rec, ["產業別", "SecuritiesIndustryCode"], ["產業"])
            if code and name and re.match(r"^\d{4,6}[A-Z]?$", code):
                out[code] = dict(name=name, suffix=suffix, ind=TW_INDUSTRY_CODE.get((ind or "").zfill(2), "其他"))
    if len(out) < 500:
        raise RuntimeError("取得的名單筆數過少")
    return out

def get_directory():
    """回傳 (名錄, 是否為完整即時名單)。連不上時 10 分鐘內不重試，避免每次操作都卡在連線逾時。"""
    d = {c: dict(v) for c, v in BUILTIN_STOCKS.items()}
    if time.time() - st.session_state.get("_dir_failed_at", 0) > 600:
        try:
            live = _fetch_live_directory()
            for c, v in live.items():
                if v["ind"] == "其他" and c in d:
                    v["ind"] = d[c]["ind"]
                d[c] = v
            _add_official_names(d)
            return d, True
        except Exception:
            st.session_state["_dir_failed_at"] = time.time()
    _add_official_names(d)
    return d, False

def search_stocks(query, directory, limit=100):
    """打數字 → 列出『代號開頭相同』的股票；打中文 → 公司名包含該字。"""
    q = (query or "").strip()
    codes = sorted(directory.keys())
    if not q:
        pinned = [t.split(".")[0] for t in INDUSTRY_MAP if t.split(".")[0] in directory]
        return pinned + [c for c in codes if c not in pinned], len(codes)
    if q[0].isdigit():
        hits = [c for c in codes if c.startswith(q)]
    else:
        ql = q.lower()
        hits = [c for c in codes if ql in directory[c]["name"].lower()]
    return hits[:limit], len(hits)

# ==========================================
# 各家公司的「相關個股」：(代號, 名稱, 關係)
# 關係文字「（」前面的字是分組：同業／上游／下游／同集團
# ==========================================
PROFILE_PEERS = {
    "2330.TW": [("2303", "聯電", "同業（晶圓代工）"), ("6770", "力積電", "同業（晶圓代工）"), ("5347", "世界先進", "同業（晶圓代工）"),
                ("6488", "環球晶", "上游（矽晶圓）"), ("1560", "中砂", "上游（材料耗材）"), ("6196", "帆宣", "上游（廠務工程）"),
                ("3711", "日月光投控", "下游（封裝測試）"), ("2454", "聯發科", "下游（IC 設計客戶）"),
                ("3443", "創意", "下游（IC 設計客戶）"), ("2379", "瑞昱", "下游（IC 設計客戶）")],
    "2303.TW": [("2330", "台積電", "同業（晶圓代工龍頭）"), ("6770", "力積電", "同業（晶圓代工）"), ("5347", "世界先進", "同業（晶圓代工）"),
                ("6488", "環球晶", "上游（矽晶圓）"), ("1560", "中砂", "上游（材料耗材）"),
                ("3711", "日月光投控", "下游（封裝測試）"), ("3034", "聯詠", "下游（IC 設計客戶）"),
                ("2379", "瑞昱", "下游（IC 設計客戶）"), ("2454", "聯發科", "下游（IC 設計客戶）")],
    "2454.TW": [("2379", "瑞昱", "同業（IC 設計）"), ("3034", "聯詠", "同業（IC 設計）"), ("6415", "矽力*-KY", "同業（IC 設計）"),
                ("3035", "智原", "同業（IC 設計）"), ("3443", "創意", "同業（客製化晶片）"), ("3661", "世芯-KY", "同業（客製化晶片）"),
                ("2330", "台積電", "上游（晶圓代工）"), ("2303", "聯電", "上游（晶圓代工）"),
                ("3711", "日月光投控", "上游（封裝測試）"), ("6239", "力成", "上游（封裝測試）")],
    "3711.TW": [("6239", "力成", "同業（封測）"), ("2449", "京元電子", "同業（封測）"), ("8150", "南茂", "同業（封測）"), ("3264", "欣銓", "同業（封測）"),
                ("2330", "台積電", "上游（晶圓來源）"), ("2303", "聯電", "上游（晶圓來源）"),
                ("3037", "欣興", "上游（IC 載板）"), ("3189", "景碩", "上游（IC 載板）"),
                ("2454", "聯發科", "下游（IC 設計客戶）"), ("2379", "瑞昱", "下游（IC 設計客戶）")],
    "2603.TW": [("2609", "陽明", "同業（貨櫃航運）"), ("2615", "萬海", "同業（貨櫃航運）"), ("2606", "裕民", "同業（散裝航運）"),
                ("2208", "台船", "上游（造船）"), ("5607", "遠雄港", "上游（港口碼頭）"),
                ("2636", "台驊投控", "下游（貨運承攬）"), ("2618", "長榮航", "同集團（航空）")],
}

# ==========================================
# 沒有個別公司報告時，依「產業別」提供的通用中文說明
# ==========================================
INDUSTRY_TEMPLATES = {
    "半導體": dict(desc="半導體產業分工細緻：IC 設計 → 晶圓製造 → 封裝測試，另有材料、設備與 EDA 支援。設計端偏輕資產，製造與封測端資本密集。",
                 upstream=["半導體設備與材料", "矽晶圓、化學品與氣體", "EDA 軟體與 IP 授權"], downstream=["IC 設計公司與 IDM", "系統廠與品牌廠", "手機、伺服器、車用、消費電子"],
                 cycle="受終端需求與庫存週期影響明顯：需求轉弱時客戶砍單、稼動率下滑；回溫時訂單快速回補。AI 與高效能運算是近年的長期成長主軸，但短期仍有波動。",
                 watch=["月營收", "產能稼動率", "毛利率與資本支出指引", "庫存週期", "美元匯率"]),
    "電腦週邊": dict(desc="涵蓋 PC、伺服器、品牌與代工組裝。品牌廠貼近消費者；代工廠（ODM／EMS）規模大、毛利較薄。",
                 upstream=["晶片：CPU、GPU、記憶體", "零組件：面板、電源、散熱、機殼", "作業系統與軟體"], downstream=["品牌廠與雲端服務業者", "企業與一般消費者"],
                 cycle="PC 有換機週期；伺服器受雲端與 AI 資本支出帶動；代工廠毛利薄，重視出貨量與產品組合。",
                 watch=["出貨量與月營收", "AI 伺服器占比", "零組件成本與匯率", "雲端業者資本支出"]),
    "光電": dict(desc="面板、LED、光學鏡頭與相關材料。供給過剩時價格下滑，屬強週期產業。",
               upstream=["玻璃基板、偏光片、背光模組材料", "驅動 IC", "設備"], downstream=["電視、手機、車用顯示與消費電子品牌"],
               cycle="面板價格由供需決定，產能擴張快、需求成長慢，容易出現循環性供過於求。", watch=["面板報價", "稼動率", "庫存天數", "月營收"]),
    "通信網路": dict(desc="網通設備、電信服務與通訊零組件。電信服務營運穩定；設備商受客戶資本支出與規格升級週期影響。",
                 upstream=["網通晶片", "光通訊與射頻元件", "電子零組件"], downstream=["電信業者與資料中心", "企業與家庭用戶"],
                 cycle="電信服務防禦性強；網通設備隨電信與資料中心的投資週期起伏。", watch=["月營收", "客戶資本支出", "規格升級（Wi-Fi、5G、高速交換器）", "毛利率"]),
    "電子零組件": dict(desc="被動元件、PCB、連接器、散熱等，賣給各類電子產品製造商，景氣連動終端需求與庫存。",
                  upstream=["原物料：銅、陶瓷、樹脂", "生產設備"], downstream=["電子品牌與代工廠", "車用與工控客戶"],
                  cycle="庫存調整期營收下滑快，缺貨期報價上揚；車用與 AI 伺服器提供結構性需求。", watch=["接單出貨比", "稼動率", "原物料價格", "客戶庫存"]),
    "航運": dict(desc="運送貨櫃、散裝或油輪貨物，運價受供需影響大，資本密集、強週期。",
               upstream=["造船廠", "燃油", "港口與碼頭"], downstream=["貨主與貨運承攬業"],
               cycle="運力（新船交付）調整慢、需求變化快，運價容易劇烈波動。", watch=["運價指數（SCFI、BDI 等）", "新船交付量", "貿易量", "燃油價格"]),
    "金融保險": dict(desc="銀行靠存放款利差與手續費，壽險靠保費與投資收益，證券靠經紀與自營。獲利與利率、資本市場和景氣連動。",
                 upstream=["資金來源：存款、保費、股東資金"], downstream=["個人與企業客戶"],
                 cycle="利率上升通常有利銀行利差，但也可能推升壞帳、壓抑債券評價；資本市場熱絡有利證券與壽險投資收益。", watch=["利差與淨值比", "逾放比", "股利政策", "股債市場表現"]),
    "鋼鐵": dict(desc="上游鐵礦與煤，中游煉鋼，下游營建、製造與汽車。價格受供需與原料成本影響。",
               upstream=["鐵礦砂、煤炭、廢鋼"], downstream=["營建、機械、汽車、家電製造"],
               cycle="與營建與製造業景氣連動，全球產能過剩與貿易政策常造成價格波動。", watch=["鋼價與原料價差", "稼動率", "營建與製造業景氣", "進口與貿易政策"]),
    "塑膠": dict(desc="由石化原料延伸為塑膠、纖維與化學品，「產品價格減原料價格」的價差決定獲利。",
               upstream=["原油與石腦油"], downstream=["塑膠加工、紡織、電子材料、包裝"],
               cycle="油價與供需影響價差，產能擴張與需求低迷時利潤被壓縮。", watch=["產品價差", "油價", "產能利用率", "中國需求"]),
    "汽車": dict(desc="整車廠與零組件供應鏈，受新車銷售、油電轉換與庫存影響。",
               upstream=["零組件：引擎／電池、電子、鋼材"], downstream=["經銷商與消費者", "租賃與車隊"],
               cycle="銷售受景氣、利率與換車週期影響；電動化正在改變供應鏈。", watch=["月銷量", "毛利率", "庫存與促銷", "電動車滲透率"]),
    "食品": dict(desc="民生消費，需求穩定，獲利受原物料價格與通路成本影響。",
               upstream=["農產品與原物料"], downstream=["通路與消費者"],
               cycle="防禦性強、景氣波動小，但需注意原物料漲價與成本轉嫁能力。", watch=["原物料價格", "毛利率", "通路動態", "同店成長"]),
    "電機機械": dict(desc="設備與機械製造，景氣連動製造業資本支出。",
                 upstream=["鋼材與零組件", "控制與驅動元件"], downstream=["製造業、半導體與電子廠、基礎建設"],
                 cycle="受客戶資本支出週期影響，訂單能見度是重點。", watch=["接單與交期", "客戶資本支出", "原物料價格"]),
    "建材營造": dict(desc="建商靠推案與交屋認列收入，景氣連動利率與房市。",
                 upstream=["土地、營建材料"], downstream=["購屋與租賃需求者"],
                 cycle="房市受利率、政策與信用管制影響，收入認列有時間落差。", watch=["預售與待交屋金額", "利率", "房市成交量"]),
    "生技醫療": dict(desc="新藥、醫材與醫療服務，研發時間長、成敗影響大。",
                 upstream=["研發、臨床試驗、原料藥"], downstream=["醫院、通路、病患"],
                 cycle="受法規與研發進度影響，較不受景氣循環影響，但事件驅動明顯。", watch=["臨床進度", "授權與里程碑", "法規審核", "現金水位"]),
    "貿易百貨": dict(desc="零售與通路，貼近民生消費，重視展店與同店成長。",
                 upstream=["品牌與供應商"], downstream=["消費者"],
                 cycle="與消費力及觀光客流量連動，具防禦性但競爭激烈。", watch=["同店銷售", "毛利率", "展店與通路成本"]),
    "ETF": dict(desc="追蹤特定指數或主題的一籃子股票，本身不是單一公司，沒有「產業鏈」可言。",
              upstream=[], downstream=[], cycle="表現取決於所追蹤的成分股與整體市場。", watch=["追蹤指數與成分股", "費用率", "配息政策", "折溢價"]),
}
INDUSTRY_TEMPLATES["化學"] = INDUSTRY_TEMPLATES["塑膠"]
DEFAULT_TEMPLATE = dict(desc="這個產業別目前沒有內建的通用說明。", upstream=[], downstream=[],
                        cycle="請參考公司法說會與年報中的產業說明。", watch=["月營收", "毛利率", "同業表現"])

# ==========================================
# 相關個股：股價抓取與統計
# ==========================================
REL_ORDER = ["本股", "同業", "同產業", "上游", "下游", "同集團"]

def _norm_series(s):
    s = s.dropna().copy()
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")]

@st.cache_data(ttl=900, show_spinner=False)
def get_peer_closes(codes):
    """同時抓多檔近一年收盤價（多執行緒，約 1～3 秒）。上市抓不到會自動改試上櫃。"""
    def fetch(code):
        for suf in (".TW", ".TWO"):
            try:
                h = yf.Ticker(code + suf).history(period="1y")
                if h is not None and len(h) >= 25:
                    return code, _norm_series(h["Close"])
            except Exception:
                pass
        return code, None
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(fetch, codes))
    return pd.DataFrame({c: s for c, s in results if s is not None})

def _ret(s, n):
    return s.iloc[-1] / s.iloc[-1 - n] - 1 if len(s) > n else np.nan

def peers_for(code, industry_name, directory):
    """
    沒有專屬清單時，找『同產業別』的股票當同類股比較。
    directory 在拿到即時名單時涵蓋全部上市櫃（約 2,000 檔），涵蓋範圍遠大於內建的 140 檔知名股，
    所以優先從 directory 找，內建名單只當作「知名股優先排序」的依據，抓不到即時名單時退回內建名單。
    """
    if not industry_name or industry_name in ("其他", "ETF"):
        return []
    same_industry = [c for c, v in directory.items() if v.get("ind") == industry_name and c != code]
    if not same_industry:
        return []
    known_first = sorted(same_industry, key=lambda c: (c not in BUILTIN_STOCKS, c))
    return [(c, directory[c]["name"], "同產業") for c in known_first[:8]]

def load_peer_context(code, stock_name, subject_close, peers):
    codes = tuple(dict.fromkeys(p[0] for p in peers if p[0] != code))
    if not codes:
        return None
    closes = get_peer_closes(codes)
    if closes is None or closes.empty:
        return None
    subj = _norm_series(subject_close.tail(300))
    allc = pd.concat([closes, subj.rename(code)], axis=1).sort_index()
    meta = {code: (stock_name, "本股", "本股")}
    for c, nm, rel in peers:
        if c != code and c not in meta:
            meta[c] = (nm, rel.split("（")[0], rel)
    rets = allc.pct_change()
    rows = []
    for c in allc.columns:
        s = allc[c].dropna()
        if len(s) < 25 or c not in meta:
            continue
        yr = s.tail(250)
        hi, lo = yr.max(), yr.min()
        corr = rets[c].tail(120).corr(rets[code].tail(120)) if c != code else np.nan
        above_ma20 = bool(s.iloc[-1] > s.tail(20).mean())
        d5, d20 = _ret(s, 5), _ret(s, 20)
        momentum_hits = sum([above_ma20, pd.notna(d5) and d5 > 0, pd.notna(d20) and d20 > 0])
        momentum_badge = "🟢 動能一致偏多" if momentum_hits == 3 else ("🔴 動能一致偏空" if momentum_hits == 0 else "🟡 動能分歧")
        rows.append(dict(code=c, name=meta[c][0], group=meta[c][1], detail=meta[c][2], close=s.iloc[-1],
                         d1=_ret(s, 1), d5=d5, d20=d20, d60=_ret(s, 60),
                         pos52=(s.iloc[-1] - lo) / (hi - lo) if hi > lo else np.nan,
                         above_ma20=above_ma20, corr=corr, momentum_badge=momentum_badge))
    if len(rows) < 2:
        return None
    tbl = pd.DataFrame(rows)
    order = {g: i for i, g in enumerate(REL_ORDER)}
    tbl["_o"] = tbl["group"].map(order).fillna(99)
    tbl = tbl.sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
    return dict(table=tbl, allc=allc, code=code)

def _summ(t):
    return dict(n=len(t), d1=t["d1"].mean(), d5=t["d5"].mean(), d20=t["d20"].mean(), d60=t["d60"].mean(),
                breadth=t["above_ma20"].mean(), up20=(t["d20"] > 0).mean(), pos=t["pos52"].mean())

def _call(d20, breadth):
    if pd.isna(d20) or pd.isna(breadth):
        return "資料不足"
    if breadth >= 0.7 and d20 > 0:
        return "🟢 偏多"
    if breadth <= 0.3 and d20 < 0:
        return "🔴 偏空"
    return "🟡 多空分歧"

def _pp(v):
    return f"{v * 100:+.2f}%" if pd.notna(v) else "—"

def _show_peer_table(t):
    view = pd.DataFrame({
        "股票": [("⭐ " if g == "本股" else "") + f"{n}（{c}）" for n, c, g in zip(t["name"], t["code"], t["group"])],
        "關係": t["detail"], "收盤": t["close"],
        "較前一交易日": t["d1"] * 100, "近5日": t["d5"] * 100, "近20日": t["d20"] * 100, "近60日": t["d60"] * 100,
        "站上月線": ["是" if a else "否" for a in t["above_ma20"]], "動能燈號": t["momentum_badge"], "與本股連動": t["corr"]})
    pct_cols = ["較前一交易日", "近5日", "近20日", "近60日"]
    try:
        sty = view.style.format({"收盤": "{:.2f}", **{c: "{:+.2f}%" for c in pct_cols}, "與本股連動": "{:.2f}"}, na_rep="—")
        color = lambda v: ("color:#e5484d" if v > 0 else "color:#30a46c" if v < 0 else "") if pd.notna(v) else ""
        mapper = getattr(sty, "map", None) or sty.applymap
        st.dataframe(mapper(color, subset=pct_cols), hide_index=True, **STRETCH)
    except Exception:
        st.dataframe(view.round(2), hide_index=True, **STRETCH)
    st.caption(
        "紅漲綠跌（台股慣例）。「較前一交易日」＝最近一個交易日收盤相較前一交易日；「與本股連動」＝近 120 日日報酬的相關係數（1＝完全同步）。"
        "「動能燈號」＝站上月線、近5日上漲、近20日上漲三項同時成立才是 🟢；三項都不成立是 🔴；介於中間是 🟡——用來快速看出同業是不是跟你的持股同步轉強或轉弱，"
        "只用收盤價計算，比個股分析頁的完整技術評分（含MACD/威廉指標）簡化許多，僅供同業橫向比較參考。"
    )

def _peer_headline(ctx):
    t = ctx["table"]
    grp = t[t["group"].isin(["本股", "同業", "同產業"])]
    sg, sa = _summ(grp), _summ(t)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("同類股多空", _call(sg["d20"], sg["breadth"]), help="站上月線比例 ≥70% 且近 20 日平均上漲＝偏多；≤30% 且下跌＝偏空；其餘為分歧")
    m2.metric("同類股較前一交易日", _pp(sg["d1"]), help="本股與同業的平均漲跌")
    m3.metric("同類股站上月線", f"{int(round(sg['breadth'] * sg['n']))} / {sg['n']} 檔")
    m4.metric("整條產業鏈多空", _call(sa["d20"], sa["breadth"]), help="含上、下游與集團相關個股")

def _norm_chart(ctx, n=60):
    allc = ctx["allc"].tail(n)
    names = dict(zip(ctx["table"]["code"], ctx["table"]["name"]))
    fig = go.Figure()
    for c in allc.columns:
        s = allc[c].dropna()
        if len(s) < 5 or c not in names:
            continue
        fig.add_trace(go.Scatter(x=s.index, y=s / s.iloc[0] * 100, mode="lines", name=f"{names[c]} {c}",
                                 line=dict(width=4 if c == ctx["code"] else 1.5)))
    fig.update_layout(height=380, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="起點 = 100",
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, **STRETCH, key=f"peer_norm_chart_{ctx['code']}")

def _render_cycle(ctx, prof, tpl, stock_name):
    if ctx is None:
        st.info("目前沒有可比較的相關個股資料，以下僅提供文字說明。")
    else:
        t = ctx["table"]
        grp = t[t["group"].isin(["本股", "同業", "同產業"])]
        sg = _summ(grp)
        me = t[t["group"] == "本股"].iloc[0]
        st.markdown("#### 一、目前多空與相對強弱")
        st.write(f"同類股共 {sg['n']} 檔，{int(round(sg['breadth'] * sg['n']))} 檔站上月線，近 20 日平均 {_pp(sg['d20'])}，"
                 f"判斷為 **{_call(sg['d20'], sg['breadth'])}**。{stock_name} 近 20 日 {_pp(me['d20'])}，"
                 f"{'強於' if me['d20'] > sg['d20'] else '弱於'}同類股平均（{_pp(sg['d20'])}）。")

        rows = []
        for g in [x for x in REL_ORDER if x in set(t["group"])]:
            s = _summ(t[t["group"] == g])
            rows.append({"關係": g, "檔數": s["n"], "較前一交易日": _pp(s["d1"]), "近20日": _pp(s["d20"]),
                         "站上月線": f"{s['breadth'] * 100:.0f}%", "52週區間位置": f"{s['pos'] * 100:.0f}%"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, **STRETCH)
        st.caption("52 週區間位置：0% 代表在一年最低點、100% 代表在一年最高點。")

        st.markdown("#### 二、會一起漲跌嗎？（產業鏈連動）")
        peers_only = t[t["group"] != "本股"]["corr"].dropna()
        if len(peers_only):
            ac = peers_only.mean()
            level = "高度連動" if ac >= 0.6 else "中度連動" if ac >= 0.3 else "連動度低"
            st.write(f"與相關個股的平均連動度（近 120 日日報酬相關係數）為 **{ac:.2f}**，屬於**{level}**。")
        by = {g: _summ(t[t["group"] == g])["d20"] for g in ["上游", "同業", "下游"] if g in set(t["group"])}
        if len(by) >= 2:
            st.write("近 20 日平均漲跌：" + "　".join(f"{g} {_pp(v)}" for g, v in by.items()) +
                     "。若上、中、下游同步走強，代表整條產業鏈景氣一致；若只有單一環節強勢，可能是個別題材而非整體景氣。")
        _norm_chart(ctx)

        st.markdown("#### 三、週期位置（股價角度）")
        pos = sg["pos"]
        if pd.notna(pos):
            stage = ("相對高檔：市場預期偏樂觀，留意追高與利多出盡風險" if pos >= 0.8 else
                     "相對低檔：市場預期偏悲觀，需確認基本面是否落底再判斷" if pos <= 0.25 else "區間中段：多空力道相對均衡")
            st.write(f"同類股平均位於 52 週區間的 **{pos * 100:.0f}%** → {stage}。")
        st.caption("股價通常領先實際景氣，反映的是市場預期而非當下基本面，僅能作為輔助判斷。")

    st.markdown("#### 四、產業循環特性")
    if prof:
        st.write(prof["overview"])
        st.write(prof["cycle"])
        st.markdown("**長期趨勢**")
        for x in prof["trends"]:
            st.markdown(f"- {x}")
    else:
        st.write(tpl["desc"])
        st.write(tpl["cycle"])

# ------------------------------------------
# 🏢 公司與產業分頁（全中文）
# ------------------------------------------
def render_company_tab(ticker, code, info, zh_name, en_name, df, industry_name, directory):
    prof = COMPANY_PROFILES.get(ticker)
    stock_name = zh_name or en_name or ticker
    tpl = INDUSTRY_TEMPLATES.get(industry_name, DEFAULT_TEMPLATE)

    if prof:
        st.info(f"💡 {prof['tagline']}")
        st.caption(f"{prof['category']}　·　成立 {prof['founded']}" + (f"　·　{en_name}" if en_name else ""))
        peers = PROFILE_PEERS.get(ticker, [])
    else:
        st.info(f"這檔沒有內建的個別公司報告，以下依「{industry_name or '產業別未知'}」整理通用的產業說明與同類股比較。個別公司的業務細節請參考下方英文簡介或公司法說會。")
        st.caption(f"{stock_name}　·　{en_name or '（無英文名稱資料）'}　·　產業別：{industry_name or info.get('industry') or '未知'}")
        peers = peers_for(code, industry_name, directory)

    ctx = None
    if peers:
        with st.spinner("載入相關個股股價中…"):
            ctx = load_peer_context(code, stock_name, df["Close"], peers)
    if ctx is not None:
        _peer_headline(ctx)

    t1, t2, t3, t4, t5 = st.tabs(["公司概況", "產業鏈與相關個股", "製作／營運流程", "產業週期與多空", "觀察指標與風險"])

    with t1:
        if prof:
            st.write(prof["business"])
            st.markdown("**主要競爭對手**")
            st.write("、".join(prof["competitors"]))
        else:
            st.write(tpl["desc"])
            emp = info.get("fullTimeEmployees")
            c1, c2 = st.columns(2)
            c1.metric("英文名稱", en_name or "無資料")
            c2.metric("員工人數", f"{emp:,}" if isinstance(emp, int) else "無資料")
            summary = info.get("longBusinessSummary")
            if summary:
                with st.expander("英文原文簡介（Yahoo Finance 提供）"):
                    st.write(summary)
            if info.get("website"):
                st.caption(f"官網：{info['website']}")
            st.caption("想加入這家公司的完整中文報告，可在程式的 COMPANY_PROFILES 與 PROFILE_PEERS 依現有格式新增，或直接告訴我要加哪一檔。")

    with t2:
        if prof:
            chain, me = prof["chain"], prof["me"]
            st.caption("⭐ 標示的是這家公司在整條產業鏈中的位置")
            widths = []
            for i in range(len(chain)):
                widths.append(3)
                if i < len(chain) - 1:
                    widths.append(0.6)
            cols = st.columns(widths)
            for i, name in enumerate(chain):
                with cols[i * 2]:
                    if i == me:
                        st.success(f"⭐ **{name}**\n\n{stock_name}")
                    else:
                        with st.container(border=True):
                            st.write(name)
                if i < len(chain) - 1:
                    cols[i * 2 + 1].markdown("<div style='text-align:center;padding-top:1.2rem'>➜</div>", unsafe_allow_html=True)
            up, down = prof["upstream"], prof["downstream"]
        else:
            up, down = tpl["upstream"], tpl["downstream"]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ⬆️ 上游（誰供貨給它）")
            for x in up or ["—"]:
                st.markdown(f"- {x}")
        with c2:
            st.markdown("#### ⬇️ 下游（它賣給誰）")
            for x in down or ["—"]:
                st.markdown(f"- {x}")
        st.markdown("#### 📈 相關個股即時比較")
        if ctx is not None:
            _show_peer_table(ctx["table"])
        else:
            st.info("目前沒有相關個股的股價資料可比較。")

    with t3:
        if prof:
            st.caption("由上到下，就是一筆訂單從接單到交貨的大致過程")
            for i, step in enumerate(prof["flow"], 1):
                st.markdown(f"**{i}.** {step}")
        else:
            st.info("通用產業說明沒有逐步的製作流程；需要的話可為這家公司新增專屬報告。")

    with t4:
        _render_cycle(ctx, prof, tpl, stock_name)

    with t5:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 👀 追蹤時要看這些")
            for x in (prof["watch"] if prof else tpl["watch"]):
                st.markdown(f"- {x}")
        with c2:
            st.markdown("#### ⚠️ 主要風險")
            if prof:
                for x in prof["risks"]:
                    st.markdown(f"- {x}")
            else:
                st.markdown("- 景氣循環與需求變化\n- 同業競爭與價格壓力\n- 原物料與匯率波動\n- 個別公司的財務與營運狀況（請看「財務體質」分頁）")

    st.caption("內容為結構性整理，不含即時財務數字；相關個股的選擇是依產業鏈關係人工整理，不代表完整名單。股價資料來自 Yahoo Finance，可能有延遲。")


# ------------------------------------------
# 📑 財務體質分頁
# ------------------------------------------
def render_fundamentals(info, q_income, current_price, target_pe, ticker):
    eps = info.get('trailingEps')
    fair_price = eps * target_pe if isinstance(eps, (int, float)) else None
    gross_margin, op_margin = info.get('grossMargins'), info.get('operatingMargins')

    if fair_price and fair_price > 0:
        d = (current_price - fair_price) / fair_price * 100
        fp_status = f"便宜 {-d:.1f}%" if current_price < fair_price else f"偏貴 {d:.1f}%"
    else:
        fp_status = None
    eps_status = "獲利" if isinstance(eps, (int, float)) and eps > 0 else ("虧損" if isinstance(eps, (int, float)) else None)
    gm_status = ("優秀" if gross_margin > 0.3 else "普通" if gross_margin > 0.15 else "偏低") if isinstance(gross_margin, float) else None
    opm_status = ("本業獲利佳" if op_margin > 0.1 else "本業虧損" if op_margin < 0 else "普通") if isinstance(op_margin, float) else None

    st.markdown("#### 獲利能力與估值")
    a, b, c, d_ = st.columns(4)
    a.metric("近四季 EPS", f"${eps:.2f}" if isinstance(eps, (int, float)) else "無資料", eps_status, delta_color="normal" if eps_status == "獲利" else "inverse")
    b.metric("合理股價估值", f"${fair_price:.2f}" if fair_price else "無資料", fp_status, delta_color="normal" if fp_status and "便宜" in fp_status else "inverse", help=f"以近四季 EPS × 參考本益比 {target_pe} 倍推算，僅為粗估")
    c.metric("毛利率", fmt_pct(gross_margin), gm_status, delta_color="normal" if gm_status == "優秀" else "off")
    d_.metric("營益率", fmt_pct(op_margin), opm_status, delta_color="normal" if opm_status == "本業獲利佳" else "inverse")

    rev_growth, current_ratio = info.get('revenueGrowth'), info.get('currentRatio')
    debt_to_equity, free_cashflow = info.get('debtToEquity'), info.get('freeCashflow')
    rev_status = "成長" if isinstance(rev_growth, (int, float)) and rev_growth > 0 else ("衰退" if isinstance(rev_growth, (int, float)) else None)
    cr_status = "尚可" if isinstance(current_ratio, (int, float)) and current_ratio >= 1 else ("偏低" if isinstance(current_ratio, (int, float)) else None)
    dte_status = "警戒" if isinstance(debt_to_equity, (int, float)) and debt_to_equity > 100 else ("安全" if isinstance(debt_to_equity, (int, float)) else None)
    fcf_status = "資金流出" if isinstance(free_cashflow, (int, float)) and free_cashflow < 0 else ("資金流入" if isinstance(free_cashflow, (int, float)) else None)

    st.markdown("#### 成長與財務安全")
    a, b, c, d_ = st.columns(4)
    a.metric("營收 YOY", fmt_pct(rev_growth), rev_status, delta_color="normal" if rev_status == "成長" else "inverse")
    b.metric("流動比率", fmt_num(current_ratio), cr_status, delta_color="normal" if cr_status == "尚可" else "inverse")
    c.metric("負債權益比", fmt_num(debt_to_equity), dte_status, delta_color="inverse" if dte_status == "警戒" else "normal")
    d_.metric("自由現金流", fmt_cash(free_cashflow), fcf_status, delta_color="inverse" if fcf_status == "資金流出" else "normal")
    note = "資金流出不一定是壞事，可能是擴廠投資中；判斷標準因產業而異，僅供參考。"
    if fcf_status == "資金流出" and ticker in COMPANY_PROFILES:
        note += "　這家公司的風險說明請見「公司與產業」分頁。"
    st.caption(note)

    # ------------------------------------
    # ★ 功能3：股利與殖利率估值（台股「存股」常用的另一套估價法） ★
    # ------------------------------------
    st.markdown("#### 💵 股利與殖利率（存股估價法）")
    div_info = get_dividend_summary(ticker, current_price)
    if div_info:
        d1, d2, d3 = st.columns(3)
        d1.metric(f"近{div_info['years']}年平均現金股利", f"${div_info['avg_dividend']:.2f}")
        d2.metric("以現價估算殖利率", f"{div_info['yield_pct']:.2f}%",
                  "偏高" if div_info['yield_pct'] >= 5 else ("尚可" if div_info['yield_pct'] >= 3 else "偏低"),
                  delta_color="normal" if div_info['yield_pct'] >= 3 else "off")
        d3.metric("現價", f"${current_price:.2f}")
        by_year_df = div_info['by_year'].rename("現金股利")
        by_year_df.index = by_year_df.index.astype(str)
        st.caption(f"近{div_info['years']}年各年度合計現金股利")
        st.bar_chart(by_year_df, color="#2f9e44")
        st.caption("殖利率 = 近幾年平均現金股利 ÷ 目前股價，是「本益比估值法」之外常用於存股評估的角度；股利會隨獲利與配息政策變動，過去配息不代表未來會持續配發同樣金額。")
    else:
        st.info("這檔股票近期沒有可用的現金股利紀錄（可能是不配息、剛上市，或資料來源暫時抓不到），此估值角度暫不適用，可參考上方本益比估值。")

    if q_income is not None and not q_income.empty:
        try:
            q_trend = q_income.T.head(5).iloc[::-1]
            rev_col = 'Total Revenue' if 'Total Revenue' in q_trend.columns else ('Operating Revenue' if 'Operating Revenue' in q_trend.columns else None)
            gp_col = 'Gross Profit' if 'Gross Profit' in q_trend.columns else None
            op_col = 'Operating Income' if 'Operating Income' in q_trend.columns else None
            if rev_col and gp_col and op_col:
                trend_df = pd.DataFrame(index=q_trend.index)
                trend_df['營收(十億)'] = q_trend[rev_col] / 1e9
                trend_df['毛利率(%)'] = q_trend[gp_col] / q_trend[rev_col] * 100
                trend_df['營業利益率(%)'] = q_trend[op_col] / q_trend[rev_col] * 100
                trend_df.index = trend_df.index.strftime('%Y-%m')
                st.markdown("#### 近五季趨勢")
                l, r = st.columns(2)
                with l:
                    st.caption("營收（十億）")
                    st.bar_chart(trend_df['營收(十億)'], color="#1f77b4")
                with r:
                    st.caption("毛利率與營業利益率（%）")
                    st.line_chart(trend_df[['毛利率(%)', '營業利益率(%)']])
            else:
                st.caption("此標的的季報欄位與預期不同，暫無法繪製趨勢圖。")
        except Exception:
            st.caption("歷史財報處理發生錯誤，暫無法繪製趨勢圖。")
    else:
        st.caption("目前無歷季財報數據可供繪圖。")

# ------------------------------------------
# 💼 我的持股（fragment：輸入股數/均價只更新這一塊）
# ------------------------------------------
@_fragment
def holding_panel(ticker, current_price, score, lv):
    st.caption("輸入你目前的持股，取得專屬的操作建議與價位。資料只在這個畫面使用，不會儲存。")
    c1, c2 = st.columns(2)
    shares = c1.number_input("持有股數", min_value=0, value=0, step=100, key=f"sh_{ticker}", help="台股 1 張 = 1000 股，零股也可以直接輸入")
    cost = c2.number_input("平均成本（每股）", min_value=0.0, value=0.0, step=0.5, key=f"co_{ticker}")

    if not (shares > 0 and cost > 0):
        st.info("👆 輸入股數與均價，這裡就會顯示未實現損益、續抱／減碼建議，以及加碼、停損、停利的具體價位。")
        return

    pnl_pct = (current_price - cost) / cost * 100
    pnl_amt = (current_price - cost) * shares
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("未實現損益", f"${pnl_amt:,.0f}", f"{pnl_pct:+.1f}%", delta_color="normal" if pnl_pct >= 0 else "inverse")
    m2.metric("持股市值", f"${current_price * shares:,.0f}")
    m3.metric("目前股價", f"${current_price:.2f}")
    m4.metric("你的均價", f"${cost:.2f}")

    if score >= 40:
        st.success("🔔 技術面偏多：可續抱，回檔到加碼價附近可分批加碼。")
    elif score >= 0:
        st.info("🔔 技術面溫和偏多：可續抱觀察，不建議大幅加碼。")
    elif score > -30:
        st.warning("🔔 技術面轉弱：已有獲利可分批減碼保護獲利；若已虧損，請嚴守停損。")
    else:
        st.error("🔔 技術面偏空：建議減碼或出場，避免虧損擴大。")

    if pnl_pct <= -8:
        st.error(f"🚨 目前虧損已達 {pnl_pct:.1f}%，若你原本的停損線已被觸及，請依紀律處理。")

    def pct(p): return f"{(p / current_price - 1) * 100:+.1f}%"
    rows = [
        {"項目": "🎯 加碼參考價", "價位": f"${lv['ma20']:.2f}" if lv['can_add'] else "暫不建議", "距現價": pct(lv['ma20']) if lv['can_add'] else "—", "怎麼用": "拉回月線且分數仍非偏空，可分批加碼" if lv['can_add'] else "分數偏弱或已跌破月線，先不加碼"},
        {"項目": "🛡️ 近端停損", "價位": f"${lv['near_stop']:.2f}", "距現價": pct(lv['near_stop']),
         "怎麼用": f"跌破且收盤確認，先減碼一半（取月線${lv['ma20_stop']:.2f}與ATR波動度停損" + (f"${lv['atr_stop']:.2f}" if lv['atr_stop'] else "N/A") + "中較近者）"},
        {"項目": "🛡️ 最終停損", "價位": f"${lv['far_stop']:.2f}", "距現價": pct(lv['far_stop']), "怎麼用": "跌破代表判斷失效，全數出場"},
        {"項目": "💰 第一停利", "價位": f"${lv['target1']:.2f}", "距現價": pct(lv['target1']), "怎麼用": "觸及先賣 1/3～1/2 鎖住利潤"},
        {"項目": "💰 第二停利", "價位": f"${lv['target2']:.2f}", "距現價": pct(lv['target2']), "怎麼用": "延伸目標，觸及可全數出場或改用移動停利"},
    ]
    st.dataframe(pd.DataFrame(rows), **STRETCH, hide_index=True)

    out_pct = (lv['near_stop'] - cost) / cost * 100
    out_amt = (lv['near_stop'] - cost) * shares
    hit_pct = (lv['target1'] - cost) / cost * 100
    hit_amt = (lv['target1'] - cost) * shares
    st.markdown(
        f"**如果…就…（依你的成本換算）**\n"
        f"- 跌到近端停損 ${lv['near_stop']:.2f} 出場 → 相對你的均價 **{out_pct:+.1f}%**（約 ${out_amt:,.0f}）\n"
        f"- 漲到第一停利 ${lv['target1']:.2f} 出場 → 相對你的均價 **{hit_pct:+.1f}%**（約 ${hit_amt:,.0f}）"
    )
    if lv['rr'] is not None:
        st.caption(f"現價到第一停利 ÷ 現價到近端停損 ≈ 1 : {lv['rr']:.1f}（風險報酬比）。價位由月線與近 60 日高低點機械式推算，並非依你的資金與風險承受度客製化，也未計手續費與稅。")

# ------------------------------------------
# 📊 技術圖表（fragment：切換區間只更新圖）
# ------------------------------------------
@_fragment
def chart_panel(df, annotations):
    span = st.radio("顯示區間", ["60 日", "150 日", "全部（約 2 年）"], index=1, horizontal=True, key="chart_span")
    n = {"60 日": 60, "150 日": 150}.get(span, len(df))
    d = df.tail(n)
    ann = [a for a in annotations if a.get('x') is not None and a['x'] >= d.index[0]]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])
    fig.add_trace(go.Candlestick(x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], increasing_line_color='red', decreasing_line_color='green', name='K線'), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d['MA20'], line=dict(color='royalblue', width=1.5), name='月線'), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d['Resistance'], line=dict(color='purple', width=1.5, dash='dash', shape='hv'), name='60日高'), row=1, col=1)
    fig.add_trace(go.Scatter(x=d.index, y=d['Support'], line=dict(color='darkcyan', width=1.5, dash='dash', shape='hv'), name='60日低'), row=1, col=1)
    vol_colors = ['red' if c >= o else 'green' for c, o in zip(d['Close'], d['Open'])]
    fig.add_trace(go.Bar(x=d.index, y=d['Volume'], marker_color=vol_colors, name='成交量'), row=2, col=1)
    macd_colors = ['red' if v >= 0 else 'green' for v in d['Hist']]
    fig.add_trace(go.Bar(x=d.index, y=d['Hist'], marker_color=macd_colors, name='MACD'), row=3, col=1)
    fig.update_layout(annotations=ann, height=650, xaxis_rangeslider_visible=False, template="plotly_white", showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, **STRETCH, key="main_kline_chart")
    st.caption("紅漲綠跌（台股慣例）。藍線＝月線，紫虛線＝近 60 日高點，青虛線＝近 60 日低點。")

# ------------------------------------------
# 🧪 回測驗證（fragment：拉桿只更新這一塊）
# ------------------------------------------
def discrimination_verdict(stats):
    """自動判讀：分數高的區間，勝率真的比分數低的區間高嗎？"""
    if stats is None or stats.empty:
        return None
    valid = stats[stats['樣本數'] >= 10]
    if len(valid) < 2:
        return None
    diff = valid.iloc[0]['上漲機率(%)'] - valid.iloc[-1]['上漲機率(%)']
    if diff < 5:
        return "warning", f"⚠️ 分數最高與最低區間的隔日上漲機率只差 {diff:.1f} 個百分點，這套分數在這檔股票上**幾乎無法分辨多空**，不宜單靠它下單。"
    if diff < 10:
        return "info", f"🟡 高低分區間的上漲機率差 {diff:.1f} 個百分點，鑑別力偏弱，僅能當參考。"
    return "success", f"✅ 高低分區間的上漲機率差 {diff:.1f} 個百分點，過去有一定鑑別力；但這是歷史統計，不保證未來。"

@_fragment
def backtest_panel(df, stats):
    verdict = discrimination_verdict(stats)
    if verdict:
        {"warning": st.warning, "info": st.info, "success": st.success}[verdict[0]](verdict[1])
    else:
        st.info("歷史樣本不足，暫時無法判斷分數是否有鑑別力。")

    if stats is not None and not stats.empty:
        s = stats.copy()
        s['平均隔日報酬(%)'] = s['平均隔日報酬(%)'].round(2)
        s['上漲機率(%)'] = s['上漲機率(%)'].round(1)
        st.markdown("#### 各分數區間，隔天真的漲了嗎？")
        st.dataframe(s, **STRETCH)
        st.caption("回測只用「指標＋當日 K 棒」計分；型態偵測需要未來 K 棒才能確認，直接納入會有前視偏誤，所以不計入。樣本數少於 10 的區間請忽略。")

    with st.expander("🧭 分期檢驗：前半段與後半段結果一致嗎？"):
        st.caption("把兩年資料切成前後兩半。若兩邊差很多，代表規則可能只是剛好套中某段歷史。")
        s1, s2, l1, l2 = walk_forward_bucket_stats(df)
        c1, c2 = st.columns(2)
        for col, s_, lab in ((c1, s1, l1), (c2, s2, l2)):
            with col:
                st.markdown(f"**{lab}**")
                if s_ is not None and not s_.empty:
                    x = s_.copy()
                    x['平均隔日報酬(%)'] = x['平均隔日報酬(%)'].round(2)
                    x['上漲機率(%)'] = x['上漲機率(%)'].round(1)
                    st.dataframe(x, **STRETCH)
                else:
                    st.caption("樣本不足")

    with st.expander("💹 進階：模擬照分數進出場的資金曲線"):
        st.caption("分數 ≥ 進場門檻時收盤買進；分數低於出場門檻、觸及停損或持有滿天數時收盤賣出。已扣單邊 0.15% 成本，未模擬滑價，僅供比較規則優劣。")
        a, b, c, d_ = st.columns(4)
        entry_th = a.slider("進場分數 ≥", 0, 60, 40, 5, key="bt_entry")
        exit_th = b.slider("出場分數 <", -40, 40, 0, 5, key="bt_exit")
        max_hold = c.slider("最長持有（日）", 3, 30, 10, 1, key="bt_hold")
        stop_pct = d_.slider("停損 %", 1.0, 20.0, 7.0, 0.5, key="bt_stop") / 100.0
        trades_df, equity = simulate_strategy(df, entry_score=entry_th, exit_score=exit_th, max_hold_days=max_hold, stop_loss_pct=stop_pct, cost_bps=15)
        m = compute_backtest_metrics(equity, trades_df)
        if not m:
            st.info("資料不足，無法回測。")
            return

        bench_label = st.radio("大盤基準", list(BENCHMARKS.keys()), horizontal=True, key="bt_bench")
        bench_equity = align_benchmark_equity(equity, BENCHMARKS[bench_label])
        bench_return = (bench_equity.iloc[-1] - 1) * 100 if bench_equity is not None and not bench_equity.empty else None
        alpha = (m['總報酬率(%)'] - bench_return) if bench_return is not None else None

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("策略總報酬", f"{m['總報酬率(%)']:.1f}%")
        k2.metric(f"{bench_label.split('（')[0]} 買進持有", f"{bench_return:.1f}%" if bench_return is not None else "無資料")
        k3.metric("超額報酬 Alpha", f"{alpha:+.1f}%" if alpha is not None else "無資料",
                  "跑贏大盤" if (alpha is not None and alpha > 0) else ("落後大盤" if alpha is not None else None),
                  delta_color="normal" if (alpha is not None and alpha > 0) else "inverse")
        k4.metric("最大回撤", f"{m['最大回撤(%)']:.1f}%")
        k5, k6 = st.columns(2)
        k5.metric("年化 Sharpe", f"{m['年化Sharpe']:.2f}" if pd.notnull(m['年化Sharpe']) else "無資料")
        k6.metric("交易次數 / 勝率", f"{m['交易次數']} 次 / {m['勝率(%)']:.0f}%" if pd.notnull(m['勝率(%)']) else f"{m['交易次數']} 次")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity.index, y=equity.values, mode='lines', line=dict(color='#1f77b4', width=2), name='策略'))
        if bench_equity is not None and not bench_equity.empty:
            fig.add_trace(go.Scatter(x=bench_equity.index, y=bench_equity.values, mode='lines', line=dict(color='gray', width=2, dash='dot'), name=bench_label.split('（')[0] + ' 買進持有'))
        else:
            st.caption("⚠️ 大盤基準資料暫時抓不到，僅顯示策略本身的資金曲線。")
        fig.add_hline(y=1.0, line_dash="dash", line_color="lightgray")
        fig.update_layout(height=320, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="資金（起始=1）", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, **STRETCH, key="equity_curve_chart")
        st.caption(f"「超額報酬 Alpha」＝策略總報酬 − {bench_label.split('（')[0]} 買進持有總報酬。Alpha 為負代表這套規則不如單純買進並抱著大盤，需要重新檢視進出場邏輯。")

        if trades_df is not None and not trades_df.empty:
            st.dataframe(trades_df, **STRETCH, hide_index=True)

    with st.expander("🔬 參數敏感度分析（找靈敏度，但小心過度擬合）"):
        st.warning(
            "⚠️ **過度擬合警語**：調整參數找出「歷史上表現最好」的那組數字很容易只是巧合地套中這兩年的走勢，"
            "未來不見得繼續有效。這裡的用途是幫你理解「規則對參數變動有多敏感」，**不是**要你直接拿最佳值去下單。"
            "比較穩健的做法：挑一個在附近一段範圍內報酬都還算平穩的參數，而不是唯一的最高點。"
        )
        scan_target = st.selectbox("要掃描哪個參數？", ["進場分數", "出場分數", "停損 %", "最長持有天數"], key="sens_target")
        fixed = dict(entry_score=entry_th, exit_score=exit_th, max_hold_days=max_hold, stop_loss_pct=stop_pct, cost_bps=15)
        grids = {
            "進場分數": ("entry_score", list(range(10, 61, 5))),
            "出場分數": ("exit_score", list(range(-30, 31, 5))),
            "停損 %": ("stop_loss_pct", [x / 100 for x in range(2, 17, 2)]),
            "最長持有天數": ("max_hold_days", list(range(3, 25, 3))),
        }
        key_name, grid_values = grids[scan_target]
        rows = []
        for v in grid_values:
            params = dict(fixed)
            params[key_name] = v
            t_df, eq = simulate_strategy(df, **params)
            mm = compute_backtest_metrics(eq, t_df)
            if mm:
                label = f"{v*100:.1f}%" if key_name == "stop_loss_pct" else v
                rows.append({scan_target: label, "總報酬(%)": round(mm['總報酬率(%)'], 1),
                            "最大回撤(%)": round(mm['最大回撤(%)'], 1), "勝率(%)": round(mm['勝率(%)'], 0) if pd.notnull(mm['勝率(%)']) else None,
                            "交易次數": mm['交易次數']})
        if rows:
            sens_df = pd.DataFrame(rows)
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=sens_df[scan_target].astype(str), y=sens_df["總報酬(%)"], mode='lines+markers', name='總報酬(%)', line=dict(color='#1f77b4')))
            fig2.update_layout(height=280, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), xaxis_title=scan_target, yaxis_title="總報酬(%)")
            st.plotly_chart(fig2, **STRETCH, key="sensitivity_chart")
            st.dataframe(sens_df, **STRETCH, hide_index=True)
            best = sens_df.loc[sens_df["總報酬(%)"].idxmax()]
            st.caption(f"這段歷史裡，{scan_target}＝{best[scan_target]} 的總報酬最高（{best['總報酬(%)']}%），"
                      "但這只是事後回顧、不是預測。若曲線忽高忽低、只有單一個尖峰，通常代表結果不穩定，過擬合風險更高。")
        else:
            st.info("資料不足，無法進行參數掃描。")



# ==========================================
# ★ 功能2：台股宏觀總經與籌碼雷達 ★
# ==========================================
@cache_if_ok(900)
def get_macro_series(symbol, period="1mo"):
    try:
        h = yf.Ticker(symbol).history(period=period)
        if h is None or len(h) < 2:
            return None
        s = h['Close'].dropna()
        cur, prev = s.iloc[-1], s.iloc[-2]
        return dict(value=cur, chg_pct=(cur / prev - 1) * 100, series=s)
    except Exception:
        return None

@cache_if_ok(1800)
def get_taifex_foreign_tx():
    """
    嘗試抓取台指期（臺股期貨）外資淨未平倉口數。
    這是全站最容易失效的資料來源：期交所頁面的表格格式偶爾會調整，
    抓不到時一律回傳 None，畫面上會清楚顯示「暫時抓不到」而不是猜測數字。
    """
    if not HAS_SCRAPER:
        return None
    try:
        url = "https://www.taifex.com.tw/cht/3/futContractsDate"
        res = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        res.encoding = "utf-8"
        tables = pd.read_html(res.text)
        for t in tables:
            t = t.astype(str)
            flat = t.apply(lambda col: col.str.cat(sep=" "))
            all_text = " ".join(flat.values)
            has_contract = ("臺股期貨" in all_text) or ("台股期貨" in all_text)
            if not has_contract or "外資" not in all_text:
                continue
            mask = t.apply(lambda r: (r.str.contains("臺股期貨").any() or r.str.contains("台股期貨").any()) and r.str.contains("外資").any(), axis=1)
            sub = t[mask]
            if sub.empty:
                continue
            row = sub.iloc[0]
            nums = [c.strip().replace(",", "") for c in row if re.fullmatch(r"-?[\d,]+", c.strip())]
            candidates = [int(x) for x in nums if x.lstrip("-").isdigit()]
            if candidates:
                return dict(net=candidates[-1])
        return None
    except Exception:
        return None

# ==========================================
# ★ 功能2：每日量化候選股 —— 籌碼連買偵測、基本面評分、綜合排序 ★
# ==========================================
@cache_if_ok(21600)
def get_t86_by_date(date_str):
    """
    抓證交所「三大法人買賣超日報」（T86）單日全市場資料，回傳 {代號: (外資淨額, 投信淨額)}。
    這個端點只涵蓋上市（.TW），不含上櫃（.TWO）。欄位名稱以「模糊比對」尋找，
    是全站對外部資料格式最敏感的一段，抓不到就回傳 None，由呼叫端判定「資料不足」。
    """
    if not HAS_SCRAPER:
        return None
    try:
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
        res = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        if not isinstance(data, dict) or data.get("stat") != "OK" or not data.get("data") or not data.get("fields"):
            return None
        fields = data["fields"]
        df = pd.DataFrame(data["data"], columns=fields)
        code_col = next((c for c in fields if "代號" in c), None)
        foreign_col = next((c for c in fields if "外資" in c and "買賣超" in c and "自營" not in c and "三大法人" not in c), None)
        trust_col = next((c for c in fields if "投信" in c and "買賣超" in c), None)
        if not (code_col and foreign_col and trust_col):
            return None
        df[code_col] = df[code_col].astype(str).str.strip()
        for c in (foreign_col, trust_col):
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
        df = df.set_index(code_col)[[foreign_col, trust_col]]
        df.columns = ["外資", "投信"]
        return df
    except Exception:
        return None

def _recent_weekdays(n=10):
    d = pd.Timestamp.now().normalize()
    out = []
    while len(out) < n:
        d -= pd.Timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
    return out

def _signed_streak(values_recent_first):
    """values 由近到遠排列；回傳有號連續天數（正=連買，負=連賣）。中間出現缺值就停止累計。"""
    vals = [v for v in values_recent_first]
    if not vals or pd.isna(vals[0]) or vals[0] == 0:
        return 0
    sign = 1 if vals[0] > 0 else -1
    count = 0
    for v in vals:
        if pd.isna(v) or (1 if v > 0 else -1 if v < 0 else 0) != sign:
            break
        count += 1
    return count * sign

@cache_if_ok(21600, is_ok=lambda r: bool(r))
def get_institutional_streaks(codes, days=5):
    """
    回傳 {代號: {"foreign": 有號連續天數 or None, "trust": 同上}}。
    抓不到任何一天的資料就整批回傳空字典，UI 會顯示「籌碼資料暫時不足」，不會用假數字充數。
    """
    frames = []
    for ds in _recent_weekdays(12):
        df = get_t86_by_date(ds)
        if df is not None and not df.empty:
            frames.append(df)
        if len(frames) >= days:
            break
    if not frames:
        return {}
    result = {}
    for code in codes:
        f_vals = [df.loc[code, "外資"] if code in df.index else np.nan for df in frames]
        t_vals = [df.loc[code, "投信"] if code in df.index else np.nan for df in frames]
        result[code] = dict(foreign=_signed_streak(f_vals), trust=_signed_streak(t_vals))
    return result

def fundamental_score_components(info):
    parts = []
    eps = info.get('trailingEps')
    if isinstance(eps, (int, float)):
        parts.append(("EPS 為正（獲利中）" if eps > 0 else "EPS 為負（虧損中）", 10 if eps > 0 else -15))
    roe = info.get('returnOnEquity')
    if isinstance(roe, (int, float)):
        parts.append(("ROE 優於 15%" if roe > 0.15 else ("ROE 尚可" if roe > 0.08 else "ROE 偏低"),
                      10 if roe > 0.15 else (0 if roe > 0.08 else -10)))
    rg = info.get('revenueGrowth')
    if isinstance(rg, (int, float)):
        parts.append(("營收年增為正" if rg > 0 else "營收年增為負", 10 if rg > 0 else -10))
    gm = info.get('grossMargins')
    if isinstance(gm, (int, float)):
        parts.append(("毛利率優於 30%" if gm > 0.3 else ("毛利率尚可" if gm > 0.15 else "毛利率偏低"),
                      5 if gm > 0.3 else (0 if gm > 0.15 else -5)))
    om = info.get('operatingMargins')
    if isinstance(om, (int, float)):
        parts.append(("本業獲利穩健" if om > 0.1 else ("本業處於虧損" if om < 0 else "本業獲利普通"),
                      5 if om > 0.1 else (-15 if om < 0 else 0)))
    ocf = info.get('operatingCashflow')
    if isinstance(ocf, (int, float)):
        parts.append(("營業現金流為正" if ocf > 0 else "營業現金流為負（帳上有賺但沒進現金，需留意）", 10 if ocf > 0 else -15))
    fcf = info.get('freeCashflow')
    if isinstance(fcf, (int, float)):
        parts.append(("自由現金流為正" if fcf > 0 else "自由現金流為負（可能是擴張期，需搭配產業判斷）", 5 if fcf > 0 else 0))
    dte = info.get('debtToEquity')
    if isinstance(dte, (int, float)):
        parts.append(("財務槓桿在安全範圍" if dte <= 100 else "負債權益比偏高", 5 if dte <= 100 else -5))
    return parts

def gross_margin_trend(q_income):
    """比較近幾季毛利率，回傳 ('rising'/'stable'/'falling', 說明文字) 或 None（資料不足時）。"""
    if q_income is None or q_income.empty:
        return None
    try:
        q = q_income.T.head(4).iloc[::-1]
        rev_col = 'Total Revenue' if 'Total Revenue' in q.columns else ('Operating Revenue' if 'Operating Revenue' in q.columns else None)
        gp_col = 'Gross Profit' if 'Gross Profit' in q.columns else None
        if not (rev_col and gp_col) or len(q) < 2:
            return None
        gm_series = (q[gp_col] / q[rev_col]).dropna()
        if len(gm_series) < 2:
            return None
        diff = gm_series.iloc[-1] - gm_series.iloc[0]
        if diff > 0.02:
            return ("rising", f"近{len(gm_series)}季毛利率上升 {diff*100:.1f} 個百分點")
        if diff < -0.02:
            return ("falling", f"近{len(gm_series)}季毛利率下滑 {abs(diff)*100:.1f} 個百分點")
        return ("stable", f"近{len(gm_series)}季毛利率大致持平")
    except Exception:
        return None

def passes_fundamental_filter(info, q_income, min_roe=None, max_dte=None, require_positive_ocf=False, require_positive_fcf=False, require_positive_eps=False):
    """
    基本面硬性初篩（用於全市場掃描前先縮小範圍）：ROE、EPS、現金流、負債比。
    任何一項資料缺失，預設「不因缺資料而刷掉」，避免因為 Yahoo 沒填某欄位就整檔被誤刪；
    缺資料的項目會在候選卡片的風險欄提醒使用者自行確認。
    """
    if min_roe is not None:
        roe = info.get('returnOnEquity')
        if isinstance(roe, (int, float)) and roe < min_roe:
            return False
    if max_dte is not None:
        dte = info.get('debtToEquity')
        if isinstance(dte, (int, float)) and dte > max_dte:
            return False
    if require_positive_ocf:
        ocf = info.get('operatingCashflow')
        if isinstance(ocf, (int, float)) and ocf <= 0:
            return False
    if require_positive_fcf:
        fcf = info.get('freeCashflow')
        if isinstance(fcf, (int, float)) and fcf <= 0:
            return False
    if require_positive_eps:
        eps = info.get('trailingEps')
        if isinstance(eps, (int, float)) and eps <= 0:
            return False
    return True

def chip_score_components(streak):
    parts = []
    f, t = streak.get("foreign"), streak.get("trust")
    if f is not None and f != 0:
        if f >= 3: parts.append((f"外資連 {f} 日買超", 15))
        elif f >= 1: parts.append((f"外資近 {f} 日買超", 5))
        elif f <= -3: parts.append((f"外資連 {abs(f)} 日賣超", -15))
        else: parts.append((f"外資近 {abs(f)} 日賣超", -5))
    if t is not None and t != 0:
        if t >= 3: parts.append((f"投信連 {t} 日買超", 10))
        elif t >= 1: parts.append((f"投信近 {t} 日買超", 3))
        elif t <= -3: parts.append((f"投信連 {abs(t)} 日賣超", -10))
        else: parts.append((f"投信近 {abs(t)} 日賣超", -3))
    return parts

BUCKET_RANGE = {"≥40 (強勢偏多)": (40, None), "0~39 (溫和偏多)": (0, 40),
                "-29~-1 (中性偏弱)": (-29, 0), "≤-30 (偏空)": (-999, -29)}

@st.cache_data(ttl=900, show_spinner=False)
def compute_horizon_actuals(entry_time_str, df_j, horizons=(5, 10, 20)):
    """
    用存入時間在歷史K棒中定位，往後數N個交易日算實際報酬；還沒到那一天就回傳 None（而不是硬湊數字）。
    這是「視覺化回測績效快照」的資料來源：累積你自己記錄過的標的，在固定天數後實際表現如何。
    """
    out = {h: None for h in horizons}
    if df_j is None or df_j.empty:
        return out
    try:
        entry_date = pd.to_datetime(entry_time_str).normalize()
        idx_arr = df_j.index.get_indexer([entry_date], method="nearest")
        idx = int(idx_arr[0])
    except Exception:
        return out
    price_then = df_j['Close'].iloc[idx]
    if pd.isna(price_then) or price_then == 0:
        return out
    for h in horizons:
        t = idx + h
        if 0 <= t < len(df_j):
            out[h] = round((df_j['Close'].iloc[t] - price_then) / price_then * 100, 2)
    return out

def historical_horizon_stats(df, bucket, max_hold_days=10, stop_loss_pct=0.08):
    """
    拿這檔股票過去的走勢，模擬『分數落在這個區間就進場』的交易，
    統計真正發生過的平均報酬與平均持有天數（隔日開盤成交版回測引擎的結果）。
    """
    lo, hi = BUCKET_RANGE.get(bucket, (0, None))
    exit_score = 0 if lo >= 0 else -999     # 偏弱區間不套「分數<0就出場」，否則隔天就出場
    trades_df, _ = simulate_strategy(df, entry_score=lo, exit_score=exit_score, entry_max=hi,
                                     max_hold_days=max_hold_days, stop_loss_pct=stop_loss_pct, cost_bps=15)
    if trades_df is None or trades_df.empty:
        return None
    t = trades_df.copy()
    t['持有天數'] = (pd.to_datetime(t['出場日']) - pd.to_datetime(t['進場日'])).dt.days.clip(lower=1)
    return dict(avg_return=t['報酬率(%)'].mean(), avg_days=t['持有天數'].mean(),
               win_rate=(t['報酬率(%)'] > 0).mean() * 100, n=len(t))

# ------------------------------------------
# C：全市場流動性篩選池（避免對近2000檔逐一呼叫API導致掃描超慢）
# ------------------------------------------
@cache_if_ok(3600)
def get_market_volume_snapshot():
    """
    一次性抓上市當日全市場成交量（TWSE 每日收盤行情彙總），用來做流動性排序。
    格式若與猜測不符會回傳 None，由呼叫端顯示清楚的失敗訊息並退回內建清單，不會用假資料頂替。
    """
    if not HAS_SCRAPER:
        return None
    try:
        for i in range(1, 8):
            d = pd.Timestamp.now() - pd.Timedelta(days=i)
            if d.weekday() >= 5:
                continue
            ds = d.strftime("%Y%m%d")
            url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type=ALLBUT0999&response=json"
            res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            data = res.json()
            if not isinstance(data, dict):
                continue
            out = {}
            for t in (data.get("tables") or []):
                fields = t.get("fields", [])
                code_i = next((j for j, f in enumerate(fields) if "代號" in f), None)
                vol_i = next((j for j, f in enumerate(fields) if "成交股數" in f), None)
                if code_i is None or vol_i is None:
                    continue
                for row in t.get("data", []):
                    try:
                        code = str(row[code_i]).strip()
                        vol = float(str(row[vol_i]).replace(",", ""))
                        if code.isdigit():
                            out[code] = vol
                    except Exception:
                        continue
            if out:
                return out
        return None
    except Exception:
        return None

def build_smart_pool(directory, size=150):
    """依成交量排序取流動性前N檔；抓不到就退回內建常用清單（附帶是否成功的旗標）。"""
    vol_map = get_official_liquidity() or get_market_volume_snapshot()
    if not vol_map:
        return list(INDUSTRY_MAP.keys()), False
    ranked = sorted(vol_map.items(), key=lambda x: x[1], reverse=True)
    pool = []
    for code, _ in ranked:
        suffix = directory.get(code, {}).get("suffix", ".TW")
        pool.append(code + suffix)
        if len(pool) >= size:
            break
    return pool, True

# ==========================================
# 🔥 資金流動熱力圖：資料抓取與產業彙總
# 方塊大小＝成交值（收盤價×成交股數，近似值）、顏色＝當日漲跌幅。
# 注意這是「成交熱度＋價格方向」，不是真正的資金淨流入（那需要法人買賣超資料）。
# ==========================================
def _heat_row(t, close_s, vol_s):
    close_s = close_s.dropna()
    if len(close_s) < 2:
        return None
    last, prev = float(close_s.iloc[-1]), float(close_s.iloc[-2])
    vol = float(vol_s.dropna().iloc[-1]) if len(vol_s.dropna()) else 0.0
    if prev <= 0 or last <= 0 or vol <= 0:
        return None
    return dict(ticker=t, close=last, prev=prev, chg=(last / prev - 1) * 100, value=last * vol,
                asof=pd.to_datetime(close_s.index[-1]).strftime("%m/%d"))

@st.cache_data(ttl=600, show_spinner=False)
def fetch_heat_quotes(tickers):
    """批次抓最近幾天的收盤價與成交量；批次下載失敗或漏掉的個股，退回逐檔補抓。"""
    rows, got = [], set()
    _off = get_official_daily()
    if _off:
        _by_code = {r["code"]: r for r in _off.values()}
        for t in tickers:
            r = _by_code.get(str(t).split(".")[0])
            if r:
                rows.append({"ticker": t, "close": r["close"], "prev": r["prev"], "chg": r["chg"], "value": r["value"], "asof": r["asof"]})
                got.add(t)
    try:
        raw = yf.download([t for t in tickers if t not in got], period="5d", group_by="ticker", progress=False, threads=True, auto_adjust=False)
        if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex):
            top = set(raw.columns.get_level_values(0))
            for t in tickers:
                if t in top:
                    r = _heat_row(t, raw[t]["Close"], raw[t]["Volume"])
                    if r:
                        rows.append(r); got.add(t)
    except Exception:
        pass
    missing = [t for t in tickers if t not in got]
    if missing:
        def one(t):
            try:
                h = yf.Ticker(t).history(period="5d")
                return _heat_row(t, h["Close"], h["Volume"]) if h is not None and not h.empty else None
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=8) as ex:
            rows += [r for r in ex.map(one, missing) if r]
    return pd.DataFrame(rows)

@st.cache_resource
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

def heatmap_pool(directory, size):
    """挑出『成交量前N大』的上市櫃個股（不含ETF）；抓不到全市場成交量就退回內建常用股名單。"""
    codes = [c for c, v in directory.items() if v.get("ind") not in ("ETF", None)]
    vol_map = get_official_liquidity() or get_market_volume_snapshot()
    if vol_map:
        ranked = sorted([c for c in codes if c in vol_map], key=lambda c: vol_map[c], reverse=True)[:size]
        if len(ranked) >= 20:
            return ranked, True
    fallback = [c for c, v in BUILTIN_STOCKS.items() if v["ind"] != "ETF"]
    return fallback[:size], False

def build_sector_table(quotes, directory):
    q = quotes.copy()
    q["code"] = q["ticker"].str.split(".").str[0]
    q["name"] = q["code"].map(lambda c: directory.get(c, {}).get("name") or c)
    q["sector"] = q["code"].map(lambda c: directory.get(c, {}).get("ind") or "其他")
    sec = []
    for name, g in q.groupby("sector"):
        w = g["value"].sum()
        sec.append(dict(sector=name, value=w, chg=(g["chg"] * g["value"]).sum() / w if w > 0 else 0.0,
                        up=int((g["chg"] > 0).sum()), n=len(g)))
    sec = pd.DataFrame(sec).sort_values("value", ascending=False).reset_index(drop=True)
    sec["share"] = sec["value"] / sec["value"].sum() * 100
    return q, sec

HEAT_SCALES = {
    "台股慣例（紅漲綠跌）": [[0, "#4f8f6b"], [0.35, "#a9cdb7"], [0.5, "#eceff3"], [0.65, "#e8b9b9"], [1, "#c0504d"]],
    "國際慣例（綠漲紅跌）": [[0, "#c0504d"], [0.35, "#e8b9b9"], [0.5, "#eceff3"], [0.65, "#a9cdb7"], [1, "#4f8f6b"]],
}

def draw_sector_treemap(q, sec, scale, show_stocks=True):
    ids, labels, parents, values, colors, custom = [], [], [], [], [], []
    for _, r in sec.iterrows():
        ids.append(f"S|{r['sector']}"); labels.append(r["sector"]); parents.append("")
        values.append(r["value"]); colors.append(r["chg"]); custom.append([r["chg"], r["share"], f"{int(r['up'])}/{int(r['n'])} 檔上漲"])
    if show_stocks:
        for _, r in q.iterrows():
            ids.append(f"T|{r['code']}"); labels.append(f"{r['name']}（{r['code']}）"); parents.append(f"S|{r['sector']}")
            values.append(r["value"]); colors.append(r["chg"])
            custom.append([r["chg"], r["value"] / q["value"].sum() * 100, f"收盤 {r['close']:.2f}"])
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
        customdata=custom, texttemplate="<b>%{label}</b><br>%{customdata[0]:+.2f}%", textposition="middle center",
        hovertemplate="<b>%{label}</b><br>漲跌 %{customdata[0]:+.2f}%<br>成交值占比 %{customdata[1]:.1f}%<br>%{customdata[2]}<extra></extra>",
        marker=dict(colors=colors, colorscale=scale, cmin=-4, cmax=4, cmid=0, line=dict(width=1.5, color="#ffffff"),
                    colorbar=dict(title="漲跌 %", thickness=12, len=0.7)),
        pathbar=dict(visible=False), tiling=dict(pad=3)))
    fig.update_layout(height=600, margin=dict(l=4, r=4, t=4, b=4), paper_bgcolor="rgba(0,0,0,0)", font=dict(size=14))
    return fig

# ==========================================
# 🐋 大戶籌碼週報（資料層在 wanglai_data.py）
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def wl_fetch_daily(tickers, start, end):
    """批次抓日收盤：回傳 DataFrame（index=日期、columns=ticker）；批次失敗或漏掉的退回逐檔，並自動試上市／上櫃兩種後綴。"""
    tickers = list(tickers)
    frames = {}
    try:
        raw = yf.download(tickers, start=start, end=end, group_by="ticker", progress=False, threads=True, auto_adjust=False)
        if raw is not None and not raw.empty and isinstance(raw.columns, pd.MultiIndex):
            for t in set(raw.columns.get_level_values(0)):
                ser = raw[t]["Close"].dropna()
                if len(ser):
                    frames[t] = ser
    except Exception:
        pass
    missing = [t for t in tickers if t not in frames]
    if missing:
        def one(t):
            base = t.split(".")[0]
            alts = [t] + ([base + ".TWO"] if t.endswith(".TW") else [base + ".TW"] if t.endswith(".TWO") else [])
            for tt in alts:
                try:
                    h = yf.Ticker(tt).history(start=start, end=end)
                    if h is not None and len(h):
                        return t, h["Close"].dropna()
                except Exception:
                    pass
            return t, None
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, ser in ex.map(one, missing):
                if ser is not None and len(ser):
                    frames[t] = ser
    out = pd.DataFrame(frames)
    if not out.empty:
        idx = pd.to_datetime(out.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        out.index = idx.normalize()
        out = out[~out.index.duplicated(keep="last")].sort_index()
    return out

def wl_build_closes(codes, dates, directory):
    """回傳 index=代號、欄位=日期(ISO) 的收盤價；某日休市就取之前最近一個收盤價。"""
    codes = sorted(set(codes))
    if not codes:
        return pd.DataFrame(columns=dates)
    tick = {c: c + directory.get(c, {}).get("suffix", ".TW") for c in codes}
    start = (pd.Timestamp(min(dates)) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(max(dates)) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    daily = wl_fetch_daily(tuple(sorted(tick.values())), start, end)
    out = {}
    for d in dates:
        sub = daily.loc[:pd.Timestamp(d)] if not daily.empty else daily
        out[d] = sub.ffill().iloc[-1] if len(sub) else pd.Series(dtype=float)
    closes = pd.DataFrame(out)
    closes.index = [str(t).split(".")[0] for t in closes.index]
    return closes[~closes.index.duplicated(keep="last")]

def wl_bench(dates):
    daily = wl_fetch_daily(("^TWII",), (pd.Timestamp(min(dates)) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                           (pd.Timestamp(max(dates)) + pd.Timedelta(days=3)).strftime("%Y-%m-%d"))
    if daily.empty:
        return pd.Series(dtype=float)
    ser = daily.iloc[:, 0]
    return pd.Series({d: ser.loc[:pd.Timestamp(d)].iloc[-1] for d in dates if len(ser.loc[:pd.Timestamp(d)])})

def _wl_colorize(view, pct_cols):
    fmt = {c: "{:+.2f}" for c in pct_cols if c in view.columns}
    for c, f in (("融資增減%", "{:+.1f}%"), ("券資比", "{:.1f}"), ("週股價%", "{:+.1f}%")):
        if c in view.columns:
            fmt[c] = f
    sty = view.style.format(fmt, na_rep="—")
    color = lambda v: ("color:#c0504d;font-weight:600" if v > 0 else "color:#3f8f66;font-weight:600" if v < 0 else "") if pd.notna(v) else ""
    mapper = getattr(sty, "map", None) or sty.applymap
    return mapper(color, subset=[c for c in list(fmt) if c != "券資比"])

def _wl_view(d, directory, px):
    v = pd.DataFrame({
        "排名": range(1, len(d) + 1), "代號": d.index,
        "名稱": [directory.get(c, {}).get("name", c) for c in d.index],
        "產業": [directory.get(c, {}).get("ind", "") for c in d.index],
        "大戶Δ": d["big_d"].values, "千張Δ": d["mega_d"].values, "散戶Δ": d["retail_d"].values,
        "融資增減%": d["margin_chg"].values, "券資比": d["ratio"].values,
        "週股價%": [px.get(c, np.nan) for c in d.index], "標籤": d["tags"].values})
    return v

def _wl_highlights(d, directory, px, increase=True):
    nm = lambda c: f"{directory.get(c, {}).get('name', c)}（{c}）"
    out = []
    top = d.index[0]
    r = d.iloc[0]
    pxs = px.get(top, np.nan)
    out.append(f"**{nm(top)}** 大戶 {r['big_d']:+.2f}pp、千張 {r['mega_d']:+.2f}、股東人數 {r['holders_d']:+,.0f} 人" +
               (f"、本週股價 {pxs:+.1f}%" if pd.notna(pxs) else "") + (f"、融資 {r['margin_chg']:+.1f}%" if pd.notna(r["margin_chg"]) else "") + "。")
    n = len(d)
    k = int((d["holders_d"] < 0).sum() if increase else (d["holders_d"] > 0).sum())
    out.append(f"前 {n} 名裡有 {k} 檔股東人數{'減少（籌碼集中）' if increase else '增加（籌碼分散）'}。")
    streak_col = "streak_up" if increase else "streak_dn"
    st3 = d[d[streak_col] >= 3]
    if len(st3):
        out.append(f"連{'買' if increase else '賣'} 3 週以上：" + "、".join(f"{nm(c)} {int(d.loc[c, streak_col])}週" for c in st3.index[:5]) + "。")
    tg = "中大戶升格" if increase else "千張降級"
    tl = d[d["tag_list"].apply(lambda t: tg in t)]
    if len(tl):
        out.append(f"{tg}：" + "、".join(nm(c) for c in tl.index[:6]) + f"（共 {len(tl)} 檔）。")
    return out

def render_big_holder_picks(wk, directory, demo, week_label):
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


def render_wanglai_page():
    st.title("🐋 大戶籌碼週報")
    st.caption("用集保戶股權分散表追蹤「大戶」每週的持股比例變化，並觀察大戶買超的股票隔週表現。資料每週才更新一次。")
    if wl is None:
        st.error("找不到 wanglai_data.py。請把它和 quant_radar_app.py 放在同一個資料夾，再重新整理。")
        return
    directory, _ = get_directory()

    # ---------- 資料來源與更新 ----------
    with st.container(border=True):
        c1, c2 = st.columns([1.4, 2.6])
        src = c1.radio("資料來源", ["📊 真實資料（本機累積）", "🧪 示範資料（隨機產生）"], key="wl_src")
        demo = src.startswith("🧪")
        with c2:
            if demo:
                st.info("示範資料是**隨機產生**的，只用來預覽畫面長什麼樣子；股價和籌碼完全無關，所以示範的成績單不代表任何規律。")
                if st.button("🧪 產生／重新產生示範資料", key="wl_make_demo"):
                    codes = sorted(c for c in directory if re.fullmatch(r"[1-9]\d{3}", str(c)))
                    wl.make_demo(codes, n_weeks=14)
                    st.success("已產生 14 週示範資料。")
            else:
                if st.button("📥 更新集保資料（下載最新一週）", type="primary", key="wl_update"):
                    with st.spinner("下載集保戶股權分散表中…（約 10～60 秒）"):
                        res = wl.collect_latest()
                    if res["ok"]:
                        st.success(f"已儲存資料日期 {res['date']}（{res['n_stocks']} 檔個股）。")
                    else:
                        st.error("下載失敗，請看下方訊息；也可以改用「手動上傳」。")
                    for m in res["messages"]:
                        st.caption("• " + m)
                with st.expander("📎 手動上傳集保 CSV（自動下載失敗時用）"):
                    st.caption("用瀏覽器開 https://opendata.tdcc.com.tw/getOD.ashx?id=1-5 下載 CSV，再上傳到這裡。")
                    up = st.file_uploader("選擇檔案", type=["csv"], key="wl_upload")
                    if up is not None and st.button("匯入這個檔案", key="wl_import"):
                        try:
                            info = wl.ingest_tdcc_text(up.getvalue().decode("utf-8-sig", errors="replace"))
                            st.success(f"已匯入資料日期 {info['date']}（{info['n_stocks']} 檔）。")
                        except Exception as e:
                            st.error(f"匯入失敗：{e}")

    dates, snaps, margins = wl.load_all(demo)
    if not dates:
        st.info("還沒有任何資料。請按上面的按鈕下載（真實資料）或產生示範資料。集保每週只更新一次，累積 2 週就能看到第一份週增減報表。")
        return

    # ---------- 定義與設定 ----------
    with st.expander("⚙️ 定義與顯示設定"):
        s1, s2, s3 = st.columns(3)
        big_label = s1.selectbox("大戶定義", ["400 張以上", "200 張以上"], key="wl_big")
        retail_label = s2.selectbox("散戶定義", ["50 張以下", "10 張以下", "100 張以下"], key="wl_retail",
                                    help="原報表沒有寫明散戶的定義，這裡先預設 50 張以下，可自行切換。")
        top_n = s3.selectbox("榜單檔數", [25, 50], index=1, key="wl_topn")
        st.caption("千張大戶＝持股 1000 張以上。大戶、千張、散戶的變動單位都是「百分點」（占集保庫存比例的變化）。")
    cfg = {"big_from": 12 if big_label.startswith("400") else 11,
           "retail_to": {"50 張以下": 8, "10 張以下": 3, "100 張以下": 9}[retail_label]}

    if len(dates) < 2:
        st.warning(f"目前只有 1 週資料（{dates[0]}）。再累積 1 週（下次集保更新後再下載一次）就能看到週增減。")
        w = wl.layers(snaps[dates[0]], cfg).sort_values("big", ascending=False).head(30)
        v = pd.DataFrame({"代號": w.index, "名稱": [directory.get(c, {}).get("name", c) for c in w.index],
                          "大戶持股%": w["big"].round(2).values, "千張大戶%": w["mega"].round(2).values,
                          "股東人數": w["holders"].values})
        st.markdown("#### 目前大戶持股比例最高的 30 檔")
        st.dataframe(v, hide_index=True, **STRETCH)
        return

    weeks = dates[1:]
    sel = st.selectbox("查看哪一週", weeks[::-1], key="wl_week",
                       format_func=lambda d: f"{d}（相對 {dates[dates.index(d) - 1]}）")
    k = dates.index(sel)

    if demo:
        d_closes, d_bench = wl.load_demo_prices()
    def get_closes(codes, ds):
        try:
            if demo:
                return d_closes.reindex(list(codes))[ds]
            return wl_build_closes(codes, ds, directory)
        except Exception:
            return pd.DataFrame(index=list(codes), columns=ds, dtype=float)
    def week_px(codes):
        cl = get_closes(codes, [dates[k - 1], dates[k]])
        return ((cl[dates[k]] / cl[dates[k - 1]] - 1) * 100).to_dict()

    wk = wl.build_week(dates, snaps, margins, k, cfg)
    t_inc, t_dec, t_swap, t_score, t_pick, t_info = st.tabs(["📈 週增 TOP", "📉 週減 TOP", "🔄 大戶換手", "🏆 成績單", "🎯 大戶選股", "ℹ️ 說明與資料狀態"])

    pct_cols = ["大戶Δ", "千張Δ", "散戶Δ"]
    for tab, inc in ((t_inc, True), (t_dec, False)):
        with tab:
            d = wk.sort_values("big_d", ascending=not inc).head(top_n)
            px = week_px(list(d.index))
            st.markdown(f"#### 大戶{'增持' if inc else '減持'}前 {top_n} 名　<span style='color:#7b8794;font-size:0.85em'>{sel} vs {dates[k-1]}</span>", unsafe_allow_html=True)
            st.dataframe(_wl_colorize(_wl_view(d, directory, px), pct_cols), hide_index=True, **STRETCH, height=min(38 * (len(d) + 1), 900))
            st.caption("紅＝增、綠＝減。融資增減與券資比抓不到的欄位顯示「—」；週股價是兩份快照日期之間的收盤價漲跌。")
            if len(d):
                st.markdown("**重點**")
                for line in _wl_highlights(d, directory, px, inc):
                    st.markdown(f"- {line}")

    with t_swap:
        if k < 2:
            st.info("大戶換手需要至少 3 週資料（要比較上週與本週的方向）。")
        else:
            groups = wl.exchange_groups(wk)
            allc = [c for g in groups.values() for c in g.index]
            px = week_px(allc)
            st.markdown(f"#### 本週大戶變動 ≥1pp 的 {len(allc)} 檔 × 上週動向　<span style='color:#7b8794;font-size:0.85em'>{sel}</span>", unsafe_allow_html=True)
            desc = {"續買": "上週增、本週再增", "回頭車": "上週減、本週回補", "下車": "上週增、本週減", "續賣": "上週減、本週再減"}
            for name, g in groups.items():
                r = pd.Series([px.get(c, np.nan) for c in g.index]).dropna()
                head = f"**{name}　{len(g)} 檔**　<span style='color:#7b8794'>{desc[name]}</span>"
                if len(r):
                    head += f"　｜　本週漲跌 平均 {r.mean():+.1f}%　中位 {r.median():+.1f}%　上漲 {int((r > 0).sum())}/{len(r)}"
                st.markdown(head, unsafe_allow_html=True)
                if len(g):
                    gv = pd.DataFrame({"名稱": [f"{directory.get(c, {}).get('name', c)}（{c}）" for c in g.index],
                                       "上週Δ→本週Δ": [f"{a:+.2f} → {b:+.2f}" for a, b in zip(g["prev_big_d"], g["big_d"])],
                                       "週股價%": [px.get(c, np.nan) for c in g.index]})
                    st.dataframe(_wl_colorize(gv.sort_values("週股價%", ascending=False), []), hide_index=True, **STRETCH)
            st.caption("大戶換手的「週股價」只是描述性統計，不代表大戶動向能預測股價。")

    with t_score:
        if len(dates) < 3:
            st.info("成績單需要至少 3 週資料：用「上週的大戶增減名單」去看「下一週」的股價表現。目前資料不足。")
        else:
            hist_n = st.slider("回看幾週", 3, min(12, len(dates) - 2), min(11, len(dates) - 2), key="wl_hist") if len(dates) > 4 else len(dates) - 2
            use = dates[-(hist_n + 2):]
            cand = set()
            for kk in range(1, len(use) - 1):
                dd = wl.weekly_delta(snaps[use[kk]], snaps[use[kk - 1]], cfg)
                cand |= set(dd.sort_values("big_d", ascending=False).head(50).index) | set(dd.sort_values("big_d").head(50).index)
            WL_LAG_DAYS = 3   # 假設：週五快照 → 下週一收盤才拿得到名單。可自行調整
            pdates = None
            if not demo:
                today = pd.Timestamp.now().normalize()
                pdates = {d: (pd.Timestamp(d) + pd.Timedelta(days=WL_LAG_DAYS)).strftime("%Y-%m-%d")
                          for d in use if pd.Timestamp(d) + pd.Timedelta(days=WL_LAG_DAYS) <= today}
            with st.spinner(f"取得 {len(cand)} 檔股價中…" if not demo else "計算中…"):
                if demo:
                    closes, bench = d_closes, d_bench
                else:
                    pl = sorted(pdates.values())
                    if pl:
                        closes, bench = wl_build_closes(cand, pl, directory), wl_bench(pl)
                    else:
                        closes, bench = pd.DataFrame(), pd.Series(dtype=float)
            sc = wl.score_weeks(use, snaps, closes, bench, cfg, price_dates=pdates)
            if sc.empty:
                st.warning("股價資料不足，算不出成績單（可能是抓不到股價）。")
            else:
                summ = wl.score_summary(sc)
                last = sc.iloc[-1]
                st.markdown(f"#### 最新一週：名單 {last['list_date']} → 報酬 {last['entry_date']} 收盤至 {last['end_date']} 收盤")
                m1, m2, m3 = st.columns(3)
                m1.metric("大戶買組（上週大戶增最多 50 檔）", f"{last['buy_avg']:+.2f}%", f"中位 {last['buy_med']:+.2f}%　{last['buy_up']}漲/{last['buy_dn']}跌", delta_color="off")
                m2.metric("散戶買組（上週大戶減最多 50 檔）", f"{last['sell_avg']:+.2f}%", f"中位 {last['sell_med']:+.2f}%　{last['sell_up']}漲/{last['sell_dn']}跌", delta_color="off")
                m3.metric("加權指數同期", f"{last['bench']:+.2f}%", f"買組跑贏 {last['buy_beat']} 檔、賣組 {last['sell_beat']} 檔", delta_color="off")

                st.markdown(f"#### 歷史 {summ['weeks']} 週紀錄")
                hv = pd.DataFrame({"週": [f"W{i + 1}" for i in range(len(sc))], "名單日": sc["list_date"], "報酬區間": sc["entry_date"].str[5:] + " → " + sc["end_date"].str[5:],
                                   "買組%": sc["buy_avg"], "賣組%": sc["sell_avg"], "加權%": sc["bench"], "結果": sc["result"]})
                fig = go.Figure()
                fig.add_trace(go.Bar(x=hv["週"], y=hv["買組%"], name="大戶買組", marker_color="#b08d57"))
                fig.add_trace(go.Bar(x=hv["週"], y=hv["賣組%"], name="散戶買組", marker_color="#9aa5b4"))
                fig.add_trace(go.Scatter(x=hv["週"], y=hv["加權%"], name="加權指數", mode="lines+markers", line=dict(color="#2f4064", dash="dot")))
                fig.update_layout(barmode="group", height=320, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="週報酬 %", legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig, **STRETCH, key="wl_score_chart")
                st.dataframe(_wl_colorize(hv, ["買組%", "賣組%", "加權%"]).format({"買組%": "{:+.2f}", "賣組%": "{:+.2f}", "加權%": "{:+.2f}"}), hide_index=True, **STRETCH)

                st.markdown("#### 合起來看")
                st.markdown(
                    f"- **直接比輸贏**：大戶買組 **{summ['win']} 勝 {summ['lose']} 敗 {summ['tie']} 平**（兩組平均報酬差距小於 0.1 個百分點算平）。\n"
                    f"- **平均每週**：買組 {summ['buy_mean']:+.2f}%、賣組 {summ['sell_mean']:+.2f}%；**逐週複利累積**：買組 {summ['buy_cum']:+.1f}%、賣組 {summ['sell_cum']:+.1f}%、加權 {summ['bench_cum']:+.1f}%（不含手續費與稅）。\n"
                    f"- **正報酬週數**：買組 {summ['buy_pos']}/{summ['weeks']}，賣組 {summ['sell_pos']}/{summ['weeks']}。")
                if summ["weeks"] < 20:
                    st.warning(f"⚠️ 只有 {summ['weeks']} 週資料，樣本很小：幾週的輸贏很容易只是運氣，不能當成「大戶跟單有效」的證據。累積越久越有參考價值。" +
                               ("　**目前是隨機示範資料，本來就不該有任何規律。**" if demo else ""))

                kk = len(use) - 2
                wk2 = wl.build_week(use, snaps, margins, kk, cfg)
                ret = last["buy_ret"]
                f = wk2.reindex(ret.index)
                rank = pd.Series(range(1, len(f.sort_values("big_d", ascending=False)) + 1), index=f.sort_values("big_d", ascending=False).index).reindex(ret.index)
                conds = [("榜單前 10 名（vs 11–50 名）", rank <= 10, None),
                         ("千張同步（千張Δ ≥ +1pp）", f["mega_d"] >= 1, None),
                         ("中大戶升格", f["tag_list"].apply(lambda t: "中大戶升格" in t), None),
                         ("連買 2 週以上（vs 只買 1 週）", f["streak_up"] >= 2, None),
                         ("回頭車", f["tag_list"].apply(lambda t: "回頭車" in t), None),
                         ("股東人數減少", f["holders_d"] < 0, None),
                         ("融資增加（vs 減少或持平）", f["margin_chg"] > 0, f["margin_chg"].notna()),
                         ("券資比 ≥ 10（vs < 10）", f["ratio"] >= 10, f["ratio"].notna())]
                rows = []
                for name, cond, valid in conds:
                    rr = ret if valid is None else ret[valid.reindex(ret.index).fillna(False)]
                    cc = cond.reindex(rr.index).fillna(False)
                    ss = wl.split_stats(rr, cc)
                    fmt_ = lambda x: f"{x['n']} 檔　{x['avg']:+.2f}%　{x['up']}漲/{x['dn']}跌" if x["n"] else "—"
                    rows.append({"條件": name, "符合": fmt_(ss["符合"]), "不符合": fmt_(ss["不符合"])})
                st.markdown(f"#### 本週把買組切開看　<span style='color:#7b8794;font-size:0.85em'>名單 {last['list_date']}</span>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(rows), hide_index=True, **STRETCH)
                st.caption("切開後每組只有幾檔到幾十檔，平均數很容易被少數幾檔拉動，只能當描述，不要拿來下結論。")

    with t_pick:
        render_big_holder_picks(wk, directory, demo, sel)

    with t_info:
        st.markdown("#### 已存資料")
        sv = pd.DataFrame({"資料日期": dates, "個股檔數": [len(snaps[d]) for d in dates],
                           "有融資融券資料": ["✅" if d in margins else "—" for d in dates]})
        st.dataframe(sv.iloc[::-1], hide_index=True, **STRETCH)
        st.caption(f"存放位置：{wl.data_dir(demo)}")
        st.markdown(
            "#### 名詞與規則\n"
            "- **大戶**：持股 400 張以上；**千張大戶**：1000 張以上；**散戶**：預設 50 張以下（可在設定切換）。Δ 單位是「占集保庫存比例的百分點」。\n"
            "- **千張降級**：千張大戶減少、但 400～999 張那一層增加（大戶往下掉一級）。**中大戶升格**：400～999 張層減少、千張大戶增加。\n"
            "- **回頭車**：上週大戶減（≤-1pp）、本週增（≥+1pp）。**下車**：上週增、本週減。**連買／連賣 N**：連續 N 週大戶增（減）≥1pp。\n"
            "- **融資增減**：融資餘額相對上一份快照的變化%；**券資比**＝融券餘額 ÷ 融資餘額 ×100。\n"
            "- **成績單**：名單＝上週集保變動大戶增幅（減幅）前 50 檔；報酬＝名單公布後第一個交易日收盤，到下一週同一天收盤，等權平均，不含交易成本。\n"
            "#### 限制\n"
            "- 集保資料每週才更新，而且是「持股分級」統計，**看不出誰在買**，也無法分辨是主力還是多個大戶同時動作。\n"
            "- 大戶持股比例上升不等於會漲；成績單的週數少時，勝負多半是隨機波動。僅為公開籌碼統計，不構成投資建議。")
        if demo and st.button("🗑️ 刪除示範資料", key="wl_del_demo"):
            wl.clear_demo()
            st.rerun()

# ==========================================
# 🤖 模擬自動量化交易：多策略沙盒、盤中監控、每日報告（引擎在 sandbox_engine.py）
# ==========================================
@st.cache_data(ttl=30, show_spinner=False)
def sb_live_prices(tickers):
    """各檔最新價：優先 1 分 K 最後一筆；抓不到退回最近收盤價。回傳 (價格dict, 來源dict)。"""
    def one(t):
        for kw, label in (({"period": "1d", "interval": "1m"}, "分K"), ({"period": "5d"}, "日K")):
            try:
                h = yf.Ticker(t).history(**kw)
                if h is not None and len(h) and pd.notna(h["Close"].iloc[-1]):
                    return t, float(h["Close"].iloc[-1]), label
            except Exception:
                pass
        return t, None, "無"
    out, src = {}, {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, p_, lab in ex.map(one, list(tickers)):
            src[t] = lab
            if p_ is not None:
                out[t] = p_
    return out, src

def _sb_now():
    return pd.Timestamp.now(tz="Asia/Taipei").to_pydatetime().replace(tzinfo=None)

def _sb_param_text(p):
    parts = [f"分數≥{p['entry_threshold']}", f"風報比≥{p['min_rr']}", f"單筆風險{p['risk_pct']}%", f"最多{p['max_positions']}檔",
             f"單檔≤{p['max_pos_pct']:.0f}%", p["buy_mode"]]
    if p.get("min_win_rate"):
        parts.append(f"勝率≥{p['min_win_rate']}%")
    if p.get("breakeven_pct"):
        parts.append(f"獲利{p['breakeven_pct']}%保本")
    if p.get("tech_filter"):
        parts.append("技術：" + "＋".join(p["tech_filter"]))
    return "　·　".join(parts)

def sb_run_scan(state, pool, directory, now):
    """盤前／盤中掃描：每個『技術條件組合』只掃一次，再分給各策略；先出場、再處理掛單、最後建倉。"""
    log = []
    active = {sid: a for sid, a in state["strategies"].items() if a.get("active", True)}
    groups = {}
    for sid, a in active.items():
        groups.setdefault(tuple(a["params"].get("tech_filter", [])), []).append(sid)
    cands = {tf: scan_candidates(pool, {}, directory=directory, tech_filter=list(tf) or None) for tf in groups}
    held = sorted(sbe.watched_tickers(state))
    live, _ = sb_live_prices(tuple(held)) if held else ({}, {})
    scores = {}
    for tk in held:
        ev = evaluate_single_stock(tk, directory)
        scores[tk] = ev["score"] if ev else None
        if ev and tk not in live:
            live[tk] = ev["price"]
    for tf, sids in groups.items():
        prices = dict(live)
        for c in cands[tf]:
            prices.setdefault(c["ticker"], c["price"])
        for sid in sids:
            a = state["strategies"][sid]
            sbe.process_exits(a, prices, scores, now, log, "手動掃描")
            sbe.process_orders(a, prices, now, log, "手動掃描")
            sbe.place_entries(a, cands[tf], prices, now, log, "手動掃描")
            sbe.record_equity(a, prices, now.strftime("%Y-%m-%d"))
    sbe.save_state(state)
    sbe.append_log(log)
    return log, {", ".join(tf) or "無技術條件": len(c) for tf, c in cands.items()}

def render_sandbox_page():
    st.title("🤖 模擬自動量化交易")
    st.info("全部是**模擬**：不連券商、不碰真錢。網頁**必須開著**才會監控（關掉分頁就停止）；Yahoo 盤中報價可能延遲 15～20 分鐘。"
            "成本假設：手續費 0.1425%、證交稅 0.3%（賣出）。")
    if sbe is None:
        st.error("找不到 sandbox_engine.py。請把它和 quant_radar_app.py 放在同一個資料夾，再重新整理。")
        return
    directory, _ = get_directory()
    state = sbe.load_state()
    now = _sb_now()

    if not state["strategies"]:
        with st.container(border=True):
            st.markdown("#### 建立虛擬帳戶")
            cap = st.number_input("每個策略的起始虛擬資金（元）", 100000, 100000000, 1000000, 100000, key="sb_init_cap")
            st.caption("系統會建立 4 組預設策略（均衡穩健、動能順勢、拉回承接、嚴選高勝率），各自一個獨立帳戶，同時運行互相比較。")
            if st.button("建立 4 組系統預設策略", type="primary", key="sb_init"):
                sbe.ensure_builtin(state, cap)
                sbe.save_state(state)
                st.rerun()
        return

    if st.session_state.get("sb_scan_msg"):
        st.success(st.session_state.pop("sb_scan_msg"))

    ms_text, _lv = market_status()
    held_all = sorted(sbe.watched_tickers(state))
    prices, psrc = sb_live_prices(tuple(held_all)) if held_all else ({}, {})
    t_perf, t_run, t_mgr, t_log, t_rep = st.tabs(["📊 績效比較", "▶️ 掃描與盤中監控", "🧩 策略管理", "📜 交易紀錄", "📝 每日報告"])

    # ---------- 績效比較 ----------
    with t_perf:
        rows = []
        for sid, a in state["strategies"].items():
            if not a.get("active", True):
                continue
            m = sbe.metrics(a, prices)
            rows.append({"策略": a["name"], "權益": m["equity"], "累積報酬%": m["ret"], "已實現損益": m["realized"], "未實現損益": m["unrealized"],
                         "持股": m["n_pos"], "掛單": m["n_orders"], "已平倉": m["trades"], "勝率%": m["win"], "最大回撤%": m["mdd"]})
        if rows:
            pv = pd.DataFrame(rows)
            sty = pv.style.format({"權益": "{:,.0f}", "累積報酬%": "{:+.2f}", "已實現損益": "{:+,.0f}", "未實現損益": "{:+,.0f}", "勝率%": "{:.0f}", "最大回撤%": "{:.1f}"}, na_rep="—")
            col = lambda v: ("color:#c0504d;font-weight:600" if v > 0 else "color:#3f8f66;font-weight:600" if v < 0 else "") if pd.notna(v) else ""
            sty = (getattr(sty, "map", None) or sty.applymap)(col, subset=["累積報酬%", "已實現損益", "未實現損益"])
            st.dataframe(sty, hide_index=True, **STRETCH)
            fig = go.Figure()
            for sid, a in state["strategies"].items():
                h = a["equity_hist"]
                if a.get("active", True) and len(h) >= 2:
                    fig.add_trace(go.Scatter(x=[x["date"] for x in h], y=[x["equity"] / a["initial_capital"] * 100 for x in h], mode="lines+markers", name=a["name"]))
            if fig.data:
                fig.update_layout(height=320, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="權益（起始=100）", legend=dict(orientation="h", y=-0.25))
                st.plotly_chart(fig, **STRETCH, key="sb_equity_chart")
            else:
                st.caption("權益曲線需要至少 2 個交易日的紀錄；每次掃描或監控都會記錄當日權益。")
            st.caption("紅＝賺、綠＝賠（台股慣例）。權益＝現金＋持股以最新價估值；未實現損益已扣掉預估的賣出手續費與證交稅。")
        else:
            st.warning("目前沒有啟用的策略，請到「策略管理」開啟。")
        for sid, a in state["strategies"].items():
            if a.get("active", True) and (a["positions"] or a["orders"]):
                with st.expander(f"{a['name']}　持股 {len(a['positions'])}　掛單 {len(a['orders'])}"):
                    if a["positions"]:
                        pr = pd.DataFrame([{"代號": tk, "名稱": p_["name"], "股數": p_["shares"], "成本": p_["cost"], "現價": prices.get(tk, np.nan),
                                            "損益%": (prices.get(tk, p_["cost"]) / p_["cost"] - 1) * 100, "停損": p_["stop"], "第一停利": p_["t1"], "第二停利": p_["t2"],
                                            "進場時間": p_["entry_time"]} for tk, p_ in a["positions"].items()])
                        st.dataframe(pr.style.format({"成本": "{:.2f}", "現價": "{:.2f}", "損益%": "{:+.2f}", "停損": "{:.2f}", "第一停利": "{:.2f}", "第二停利": "{:.2f}"}, na_rep="—"), hide_index=True, **STRETCH)
                    if a["orders"]:
                        od = pd.DataFrame([{"代號": tk, "名稱": o["name"], "觸發價（跌到才買）": o["trigger"], "現價": prices.get(tk, np.nan), "停損": o["stop"], "建立時間": o["created"]} for tk, o in a["orders"].items()])
                        st.dataframe(od, hide_index=True, **STRETCH)

    # ---------- 掃描與盤中監控 ----------
    with t_run:
        with st.container(border=True):
            st.markdown("#### ① 盤前／盤中掃描：依各策略條件建倉或掛單")
            r1, r2 = st.columns([1.4, 2])
            pool_choice = r1.radio("掃描範圍", ["🕒 自動觀察清單", "🚀 全市場流動性池"], key="sb_pool")
            pool_size = r2.slider("流動性池大小", 30, 200, 80, 10, key="sb_pool_size") if pool_choice.startswith("🚀") else None
            if st.button("▶ 執行掃描（所有啟用策略）", type="primary", key="sb_scan"):
                if pool_choice.startswith("🚀"):
                    pool, ok = build_smart_pool(directory, size=pool_size)
                    if not ok:
                        st.warning("全市場成交量排行抓不到，已改用內建常用清單。")
                else:
                    pool = get_watchlist() or list(INDUSTRY_MAP.keys())
                with st.spinner(f"掃描 {len(pool)} 檔、處理各策略中…"):
                    log, cn = sb_run_scan(state, pool, directory, now)
                buys = [r for r in log if r["動作"] == "買進"]
                sells = [r for r in log if r["動作"] == "賣出"]
                orders_ = [r for r in log if r["動作"] == "掛單"]
                st.session_state["sb_scan_msg"] = f"掃描完成（{len(pool)} 檔）：買進 {len(buys)} 筆、賣出 {len(sells)} 筆、新掛單 {len(orders_)} 筆。符合技術條件的候選數：{cn}"
                st.rerun()
            st.caption("掃描用的是日線資料與今日最新價；沒有納入籌碼連買賣超。「拉回觸價」策略不會立刻買，而是掛單，等盤中監控偵測到跌到觸發價才成交。")

        with st.container(border=True):
            st.markdown("#### ② 盤中監控：觸價自動建倉、觸及停損停利自動出場")
            mc1, mc2, mc3 = st.columns([1.2, 1, 2])
            monitor_on = mc1.toggle("🔴 啟動盤中監控", key="sb_monitor")
            interval = mc2.selectbox("檢查間隔", [30, 60, 120], index=1, format_func=lambda x: f"{x} 秒", key="sb_interval")
            mc3.checkbox("非盤中也檢查（測試用：以最近價格判斷，方便晚上試功能）", key="sb_force")

            def _tick_body():
                st_ = sbe.load_state()
                n_ = _sb_now()
                watched = sorted(sbe.watched_tickers(st_))
                status = market_status()[0]
                if not watched:
                    st.caption("目前沒有持股或掛單需要監控。先執行上面的掃描。")
                    return
                if status != "盤中" and not st.session_state.get("sb_force"):
                    st.info(f"目前是「{status}」，不在交易時段（09:00–13:30），監控待命中，不會觸發任何交易。")
                    return
                px, src = sb_live_prices(tuple(watched))
                log_ = sbe.tick(st_, px, n_, "盤中監控")
                sbe.save_state(st_)
                if log_:
                    sbe.append_log(log_)
                    st.session_state.setdefault("sb_events", [])
                    st.session_state["sb_events"] = (log_ + st.session_state["sb_events"])[:30]
                    st.success(f"本次檢查觸發 {len(log_)} 筆動作")
                w = []
                for sid_, a_ in st_["strategies"].items():
                    if not a_.get("active", True):
                        continue
                    for tk, p_ in a_["positions"].items():
                        cur = px.get(tk)
                        w.append({"策略": a_["name"], "代號": tk, "類型": "持股", "現價": cur, "觸發價": p_["stop"], "說明": "停損線",
                                  "距離%": (cur / p_["stop"] - 1) * 100 if cur else np.nan})
                    for tk, o in a_["orders"].items():
                        cur = px.get(tk)
                        w.append({"策略": a_["name"], "代號": tk, "類型": "掛單", "現價": cur, "觸發價": o["trigger"], "說明": "跌到才買",
                                  "距離%": (cur / o["trigger"] - 1) * 100 if cur else np.nan})
                if w:
                    st.dataframe(pd.DataFrame(w).style.format({"現價": "{:.2f}", "觸發價": "{:.2f}", "距離%": "{:+.2f}"}, na_rep="—"), hide_index=True, **STRETCH)
                st.caption(f"最近檢查：{n_.strftime('%H:%M:%S')}　·　報價來源：" + "、".join(sorted(set(src.values()))))

            if monitor_on:
                frag = getattr(st, "fragment", None)
                if frag is None:
                    st.warning("你的 Streamlit 版本不支援自動重新整理（需要 1.37 以上），請改用下面的「手動檢查一次」。")
                else:
                    frag(run_every=int(interval))(_tick_body)()
            if st.button("手動檢查一次", key="sb_manual_tick"):
                _tick_body()
            if st.session_state.get("sb_events"):
                st.markdown("**本次開啟期間的觸發紀錄**")
                ev = pd.DataFrame(st.session_state["sb_events"])[["時間", "策略", "動作", "代號", "名稱", "價格", "股數", "損益", "原因"]]
                st.dataframe(ev, hide_index=True, **STRETCH)
            st.caption("買進價是「觸發當下抓到的價格」，不是掛單價；停損、停利也以觸發當下價格出場，所以跳空時成交價可能比停損價更差。")

    # ---------- 策略管理 ----------
    with t_mgr:
        for sid, a in list(state["strategies"].items()):
            with st.container(border=True):
                c1, c2, c3 = st.columns([4, 1, 1.3])
                c1.markdown(f"**{a['name']}**" + ("　" + pill("系統預設", "gray") if a["builtin"] else "　" + pill("自訂", "yellow")), unsafe_allow_html=True)
                c1.caption(a["desc"])
                c1.caption(_sb_param_text(a["params"]))
                act = c2.toggle("啟用", value=a.get("active", True), key=f"sb_act_{sid}")
                if act != a.get("active", True):
                    a["active"] = act
                    sbe.save_state(state)
                    st.rerun()
                if c3.button("重置帳戶", key=f"sb_reset_{sid}", help="清空持股、掛單與損益，資金回到起始金額（交易紀錄保留）"):
                    state["strategies"][sid] = sbe.new_account(a["name"], a["desc"], a["params"], a["initial_capital"], a["builtin"])
                    sbe.save_state(state)
                    st.rerun()
                if not a["builtin"] and c3.button("刪除策略", key=f"sb_del_{sid}"):
                    del state["strategies"][sid]
                    sbe.save_state(state)
                    st.rerun()
        with st.expander("➕ 新增自訂策略"):
            with st.form("sb_new_form"):
                f1, f2 = st.columns(2)
                nm = f1.text_input("策略名稱", placeholder="例如：我的短線策略")
                cap = f2.number_input("起始虛擬資金（元）", 100000, 100000000, 1000000, 100000)
                g1, g2, g3 = st.columns(3)
                et = g1.slider("進場：綜合分數 ≥", 0, 80, 40, 5)
                rr = g2.slider("風報比 ≥", 1.0, 4.0, 1.5, 0.5)
                rk = g3.slider("單筆風險 %", 0.5, 5.0, 2.0, 0.5)
                h1, h2, h3 = st.columns(3)
                mp = h1.slider("最多持股檔數", 1, 10, 5)
                mpp = h2.slider("單檔上限 %（占總資金）", 5, 50, 25, 5)
                be = h3.slider("獲利幾 % 後停損上移到成本（0＝不啟用）", 0, 20, 0, 2)
                i1, i2 = st.columns(2)
                bm = i1.radio("進場方式", ["即時進場", "拉回觸價"], horizontal=True)
                mw = i2.slider("歷史勝率 ≥ %（0＝不限制）", 0, 70, 0, 5)
                tf = st.multiselect("技術面必須符合（全部成立）", list(TECH_FILTER_OPTIONS.keys()))
                if st.form_submit_button("建立策略", type="primary"):
                    if not nm.strip():
                        st.warning("請輸入策略名稱。")
                    else:
                        sid_new = "custom_" + str(int(now.timestamp()))
                        params = {"entry_threshold": et, "min_rr": rr, "risk_pct": rk, "max_positions": mp, "max_pos_pct": float(mpp),
                                  "buy_mode": bm, "min_win_rate": mw, "breakeven_pct": float(be), "tech_filter": tf}
                        state["strategies"][sid_new] = sbe.new_account("🧪 " + nm.strip(), "自訂策略", params, cap)
                        sbe.save_state(state)
                        st.rerun()
        c1, c2 = st.columns(2)
        if c1.button("補回缺少的系統預設策略", key="sb_restore"):
            cap0 = next(iter(state["strategies"].values()))["initial_capital"]
            if sbe.ensure_builtin(state, cap0):
                sbe.save_state(state)
            st.rerun()
        with c2.expander("⚠️ 全部清除"):
            if st.checkbox("我確定要清除所有策略、持股與交易紀錄", key="sb_confirm_reset") and st.button("清除全部", key="sb_reset_all"):
                sbe.reset_all()
                st.rerun()

    # ---------- 交易紀錄 ----------
    with t_log:
        lg = sbe.load_log()
        if lg.empty:
            st.info("還沒有任何交易紀錄。")
        else:
            f1, f2 = st.columns(2)
            pick = f1.multiselect("策略", sorted(lg["策略"].unique()), key="sb_log_strat")
            acts = f2.multiselect("動作", sorted(lg["動作"].unique()), key="sb_log_act")
            v = lg[(lg["策略"].isin(pick) if pick else pd.Series(True, index=lg.index)) & (lg["動作"].isin(acts) if acts else pd.Series(True, index=lg.index))].iloc[::-1]
            st.dataframe(v, hide_index=True, **STRETCH)
            st.download_button("⬇️ 匯出 CSV", data=v.to_csv(index=False).encode("utf-8-sig"), file_name="sandbox_log.csv", mime="text/csv")

    # ---------- 每日報告 ----------
    with t_rep:
        lg = sbe.load_log()
        today_iso = now.strftime("%Y-%m-%d")
        fname = f"sandbox_{today_iso.replace('-', '')}.md"
        if ms_text == "已收盤" and fname not in sbe.list_reports():
            sbe.save_report(sbe.build_report(state, lg, today_iso, prices), today_iso)
            st.success("已收盤，今日報告已自動產生並存檔。")
        d_sel = st.date_input("報告日期", value=now.date(), key="sb_rep_date")
        iso = d_sel.strftime("%Y-%m-%d")
        md = sbe.build_report(state, lg, iso, prices)
        st.markdown(md)
        b1, b2 = st.columns(2)
        b1.download_button("⬇️ 下載這份報告（Markdown）", data=md.encode("utf-8"), file_name=f"sandbox_{iso}.md", mime="text/markdown")
        if b2.button("💾 儲存這份報告", key="sb_save_rep"):
            sbe.save_report(md, iso)
            st.success("已儲存。")
        old = sbe.list_reports()
        if old:
            with st.expander(f"📂 已存報告（{len(old)} 份）"):
                pick_r = st.selectbox("選擇報告", old, key="sb_rep_pick")
                st.markdown(sbe.read_report(pick_r))
        st.caption("報告在你開啟本頁、且已收盤時會自動產生一次；若要每天固定時間自動產出而不用開網頁，需要另外設定排程，可以告訴我。")

def resolve_display_name(tk, code_bare, info, directory=None):
    """
    強制優先順序：INDUSTRY_MAP 手打的中文名 > 全市場 directory（證交所/櫃買官方簡稱）> Yahoo 英文名 > 代號本身。
    directory 涵蓋約 1,995 檔上市櫃，是解決「候選股清單出現一堆英文名」的關鍵一步。
    """
    return (INDUSTRY_MAP.get(tk, {}).get("name")
            or (directory or {}).get(code_bare, {}).get("name")
            or info.get('shortName') or info.get('longName') or tk)

def _radar_bar(value, lo, hi):
    """把分數壓成 0~1 給 st.progress 用；None 回傳 None（畫面上顯示「無資料」而不是硬塞 0）。"""
    if value is None:
        return None
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))

def radar_verdict(tech, fund, chip_ok, chip):
    tech_strong = tech >= 30
    fund_strong = fund >= 15
    chip_strong = chip_ok and chip is not None and chip >= 10
    if tech_strong and fund_strong:
        return "🌟 雙效合一（技術＋基本面同步轉強，波段主升型態）"
    if tech_strong and chip_strong:
        return "⚡ 技術＋籌碼共振（動能強，留意基本面是否跟上）"
    if tech_strong and not fund_strong:
        return "⚡ 技術面強、基本面普通（偏短線題材，見好收）"
    if fund_strong and not tech_strong:
        return "🐢 基本面佳、技術面尚未表態（可先觀察，等分數轉強再進場）"
    return "⚪ 技術與基本面皆尚未明顯轉強"

TECH_FILTER_OPTIONS = {
    "站上月線": lambda latest, prev: latest['Close'] > latest['MA20'],
    "MACD 剛翻紅（今日由負轉正）": lambda latest, prev: latest['Hist'] > 0 and prev['Hist'] <= 0,
    "威廉指標超賣（< -80）": lambda latest, prev: latest['WPR'] < -80,
    "CCI 超賣（< -100）": lambda latest, prev: latest['CCI'] < -100,
}

def passes_tech_filter(latest, prev, selected):
    """技術面自訂篩選條件，多選時要求全部成立（AND）。"""
    if not selected:
        return True
    return all(TECH_FILTER_OPTIONS[key](latest, prev) for key in selected)

def scan_candidates(tickers, streak_map, fund_filter=None, q_income_cache=None, directory=None, tech_filter=None,
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


@st.cache_data(ttl=900, show_spinner=False)
def get_market_direction(symbol="0050.TW"):
    """
    大盤隔日方向預測：把個股用的同一套評分＋回測引擎，直接套用在0050（或指定大盤代理）身上。
    邏輯與個股分析完全相同，只是分析的對象換成大盤，不是另外做一套模型。
    """
    info, df, _ = load_stock_data(symbol)
    if df is None or df.empty or len(df) < 40:
        return None
    df_ind = compute_indicators(df)
    latest, prev = df_ind.iloc[-1], df_ind.iloc[-2]
    k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
    pattern_msgs, _ = detect_advanced_patterns(df_ind.tail(150))
    bt = backtest_score_system(df_ind)
    direction, action, buy_price, _r, color, score, bucket = predict_next_day(latest, prev, k_name, pattern_msgs, bt)
    wr = n = None
    if bt is not None and not bt.empty and bucket in bt.index:
        wr, n = bt.loc[bucket, '上漲機率(%)'], int(bt.loc[bucket, '樣本數'])
    return dict(symbol=symbol, price=latest['Close'], direction=direction, action=action, score=score,
               bucket=bucket, color=color, wr=wr, n=n)

# ==========================================
# ★ 功能G：財經新聞雷達（Beta；關鍵字比對，非真正語意分析） ★
# 以下 RSS 網址是「常見的公開財經新聞來源」，格式一改版就可能失效。
# 抓不到就整批回傳 None，畫面上清楚顯示「暫時抓不到」，不會捏造新聞。
# ==========================================
NEWS_RSS_CANDIDATES = [
    "https://news.ltn.com.tw/rss/business.xml",
    "https://www.cna.com.tw/rss/finance.xml",
]
NEWS_CATEGORY_KEYWORDS = {
    "🔥 AI": ["AI", "人工智慧", "輝達", "NVIDIA", "GPU", "生成式"],
    "💾 記憶體": ["記憶體", "DRAM", "NAND", "美光", "SK海力士", "三星電子"],
    "🚢 航運": ["航運", "貨櫃", "運價", "SCFI", "長榮", "陽明", "萬海", "散裝"],
    "💰 Fed／利率": ["Fed", "聯準會", "升息", "降息", "利率", "鮑爾", "央行"],
    "🏭 半導體": ["晶圓", "半導體", "台積電", "聯電", "封測", "IC設計", "代工"],
}
NEWS_POSITIVE_WORDS = ["大漲", "創新高", "增產", "利多", "亮眼", "上調", "買超", "看好", "強勁", "成長", "受惠"]
NEWS_NEGATIVE_WORDS = ["大跌", "重挫", "下修", "利空", "示警", "違約", "裁員", "衰退", "賣超", "看淡", "崩跌", "熄火"]

@cache_if_ok(1800)
def get_news_items(max_items=20):
    if not HAS_SCRAPER:
        return None
    for url in NEWS_RSS_CANDIDATES:
        try:
            res = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(res.content)
            items = root.findall(".//item")
            out = []
            for it in items[:max_items]:
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                if title:
                    out.append(dict(title=title, link=link))
            if out:
                return out
        except Exception:
            continue
    return None

def classify_news(title, directory):
    cats = [c for c, kws in NEWS_CATEGORY_KEYWORDS.items() if any(k in title for k in kws)]
    pos = sum(1 for w in NEWS_POSITIVE_WORDS if w in title)
    neg = sum(1 for w in NEWS_NEGATIVE_WORDS if w in title)
    impact = "正面" if pos > neg else ("負面" if neg > pos else "中性")
    stars = "★" * min(5, max(1, pos + neg)) if (pos or neg) else "★"
    tickers = []
    if directory:
        for code, v in directory.items():
            nm = v.get("name", "")
            if nm and len(nm) >= 2 and nm in title:
                tickers.append(f"{nm}（{code}）")
    return dict(categories=cats or ["其他"], impact=impact, stars=stars, tickers=tickers[:5])


@st.cache_data(ttl=900, show_spinner=False)
def get_macro_risk_flags():
    """
    給其他頁面（例如投資組合管理的倉位水位）共用的簡化總經風險旗標。
    門檻：VIX≥25 偏高、費半單日跌幅≥3% 重挫、台幣單日急貶≥0.8%。任何一項觸發就列入清單。
    """
    flags = []
    vix = get_macro_series("^VIX")
    sox = get_macro_series("^SOX")
    fx = get_macro_series("TWD=X")
    if vix and vix['value'] >= 25:
        flags.append(f"VIX 恐慌指數偏高（{vix['value']:.1f}）")
    if sox and sox['chg_pct'] <= -3:
        flags.append(f"費城半導體指數單日重挫（{sox['chg_pct']:+.1f}%）")
    if fx and fx['chg_pct'] >= 0.8:
        flags.append(f"台幣單日急貶（{fx['chg_pct']:+.2f}%）")
    return flags

def _macro_call(fx, vix, tx):
    if fx is None and vix is None and tx is None:
        return None
    risk_off = 0
    if fx is not None and fx['chg_pct'] > 0.3: risk_off += 1
    if vix is not None and vix['value'] >= 20: risk_off += 1
    if tx is not None and tx.get('net') is not None and tx['net'] < 0: risk_off += 1
    if risk_off >= 2:
        return "🔴 三項指標偏向風險趨避（台幣走貶／VIX偏高／外資空單），大環境對台股相對不利"
    if risk_off == 0:
        return "🟢 三項指標偏向風險偏好，大環境對台股相對友善"
    return "🟡 指標方向不一致，市場氣氛偏中性或分歧"

# ==========================================
# 模式二：📚 教學庫
# ==========================================
# ==========================================
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

def render_market_forecast(tone=0, show_nav=True):
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
    if show_nav and st.button("📰 開盤前完整情報 → 盤前必讀", key="mf_go_premarket"):
        _jump("📰 盤前必讀")

def render_portfolio_balance(rows, cash_on_hand, total_capital, total_mv, directory):
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

@st.cache_data(ttl=300, show_spinner=False)
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

@st.cache_data(ttl=3600, show_spinner=False)
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
    render_tomorrow_forecast(summ, quotes)

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

def _etf_tech_check(codes, directory):
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

def _guess_etf_kind(name):
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

def _alert_prices(tickers):
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

def render_sync_status():
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

if app_mode == "🏠 戰情室首頁":
    st.title("🏠 戰情室首頁")
    render_sync_status()
    st.caption("一進來就看重點，不用每頁點過去——下面任何一塊都可以點按鈕直接跳到完整頁面。")

    # ---- 每日早報：把總經數字濃縮成一句話 ----
    vix = get_macro_series("^VIX")
    sox = get_macro_series("^SOX")
    fx = get_macro_series("TWD=X")
    bits, tone = [], 0
    if sox:
        bits.append(f"費半 {sox['chg_pct']:+.1f}%")
        tone += 1 if sox['chg_pct'] > 0.5 else (-1 if sox['chg_pct'] < -0.5 else 0)
    if vix:
        vix_lv = "恐慌" if vix['value'] >= 30 else "偏高" if vix['value'] >= 20 else "平穩"
        bits.append(f"VIX {vix['value']:.0f}（{vix_lv}）")
        tone += -1 if vix['value'] >= 25 else (1 if vix['value'] < 16 else 0)
    if fx:
        bits.append(f"台幣{'貶' if fx['chg_pct'] >= 0 else '升'} {abs(fx['chg_pct']):.2f}%")
        tone += -1 if fx['chg_pct'] >= 0.5 else (1 if fx['chg_pct'] <= -0.3 else 0)
    if bits:
        verdict = pill("🟢 偏多順風", "green") if tone >= 2 else pill("🔴 防守避險", "red") if tone <= -2 else pill("🟡 中性觀望", "yellow")
        st.markdown(f"📰 **今日開盤前重點**：{'、'.join(bits)} → 綜合研判：{verdict}", unsafe_allow_html=True)
        st.caption("僅用三項總經數字做簡單加權，不是嚴謹預測模型，請一定要搭配「📡 總經雷達」完整頁面再判斷。")
    else:
        st.caption("總經資料暫時抓不到，略過每日早報。")

    st.divider()
    render_market_forecast(tone)

    st.divider()
    st.markdown("#### 📊 大盤與總經快照")
    md = get_market_direction("0050.TW")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("大盤方向（0050代理）", md['direction'] if md else "—", f"分數 {md['score']}" if md else None)
    c2.metric("VIX 恐慌指數", f"{vix['value']:.1f}" if vix else "—", f"{vix['chg_pct']:+.1f}%" if vix else None, delta_color="inverse")
    c3.metric("費半 SOX", f"{sox['value']:,.0f}" if sox else "—", f"{sox['chg_pct']:+.2f}%" if sox else None)
    c4.metric("美元／台幣", f"{fx['value']:.3f}" if fx else "—", f"{fx['chg_pct']:+.2f}%" if fx else None, delta_color="inverse")
    if st.button("查看完整總經雷達 →", key="home_go_macro"):
        st.session_state["_pending_app_mode"] = "📡 總經雷達"; st.rerun()

    st.divider()
    st.markdown("#### 💼 投資組合快照")
    _home_portfolio = load_portfolio()
    if _home_portfolio is not None and not _home_portfolio.empty:
        _home_dir, _ = get_directory()
        total_mv = total_cost = today_pnl = total_pnl = 0.0
        n_missing = 0
        with st.spinner("更新持倉現價中…"):
            for _, r in _home_portfolio.iterrows():
                code = str(r['代號']).strip()
                tk = code if "." in code else code + ".TW"
                ev = evaluate_single_stock(tk, _home_dir)
                shares, cost = float(r['股數']), float(r['均價'])
                is_short = str(r.get('方向', 'Long')) == 'Short'
                if ev:
                    sign = -1 if is_short else 1
                    total_mv += ev['price'] * shares
                    total_cost += cost * shares
                    total_pnl += (ev['price'] - cost) * shares * sign  # 空方價格下跌才賺，符號要反過來
                    if ev['prev_close']:
                        today_pnl += (ev['price'] - ev['prev_close']) * shares * sign
                else:
                    n_missing += 1
        k1, k2, k3 = st.columns(3)
        k1.metric("總市值", f"${total_mv:,.0f}")
        k2.metric("今日估計損益", f"${today_pnl:,.0f}", f"{today_pnl/total_mv*100:+.2f}%" if total_mv else None, delta_color="normal" if today_pnl >= 0 else "inverse")
        k3.metric("累計未實現損益", f"${total_pnl:,.0f}", f"{total_pnl/total_cost*100:+.1f}%" if total_cost else None, delta_color="normal" if total_pnl >= 0 else "inverse")
        if n_missing:
            st.caption(f"⚠️ 有 {n_missing} 檔抓不到即時股價，未計入以上數字。")
        st.caption("「今日估計損益」用個股現價與前一交易日收盤價的差額估算，空方部位已自動反向計算，僅供參考。")
    else:
        st.info("還沒有建立投資組合。")
    if st.button("前往完整投資組合管理 →", key="home_go_portfolio"):
        st.session_state["_pending_app_mode"] = "💼 投資組合管理"; st.rerun()

    st.divider()
    st.markdown("#### ⭐ 今日評分最高候選股 Top 3")
    _home_watchlist = get_watchlist()
    _home_pool = (_home_watchlist or list(INDUSTRY_MAP.keys()))[:15]
    with st.spinner("快速掃描中…"):
        _home_dir2, _ = get_directory()
        _home_candidates = scan_candidates(_home_pool, {}, directory=_home_dir2)
    _home_top3 = _home_candidates[:3] if _home_candidates else []
    if _home_top3:
        for c in _home_top3:
            with st.container(border=True):
                hc1, hc2, hc3 = st.columns([2, 1, 1])
                hc1.markdown(f"**{c['name']}（{c['code']}）**")
                hc2.metric("綜合分數", f"{c['composite']:+d}")
                hc3.metric("現價", f"${c['price']:.2f}")
    else:
        st.info("候選股掃描暫無結果，可能是觀察清單是空的或資料暫時抓不到。")
    st.caption("只掃觀察清單前 15 檔，求快速；要看完整排序與入選原因，請到「⭐ 每日候選股」。")
    if st.button("查看完整候選股清單 →", key="home_go_candidates"):
        st.session_state["_pending_app_mode"] = "⭐ 每日候選股"; st.rerun()

    st.divider()
    st.caption("⚠️ 以上所有數字皆為規則式試算，非統計顯著驗證過的預測模型，也不構成投資建議；過去表現不代表未來績效。")


    with st.container(border=True):
        _hc1, _hc2 = st.columns([4, 1.2])
        _hc1.markdown("**🔥 今天的錢跑去哪個族群？**　看各產業的成交熱度與漲跌，3 秒掌握資金流向。")
        if _hc2.button("查看資金熱力圖", key="home_to_heatmap", **STRETCH):
            st.session_state["_pending_app_mode"] = "🔥 資金熱力圖"
            st.rerun()

    st.divider()
    st.markdown("#### 🧭 投資流程導覽（由上而下選方向，由下而上挑好公司）")
    NAV_STEPS = [
        ("1️⃣ 大環境分析", "判斷市場大方向：利率、匯率、VIX、費半", "📡 總經雷達"),
        ("2️⃣ 產業分析", "選對賽道：用產業篩選＋同業比較找出成長方向", "⭐ 每日候選股"),
        ("3️⃣ 好公司分析", "質化審查：商業模式、護城河、上下游地位", "📈 個股分析"),
        ("4️⃣ 合理價格評估", "本益比／殖利率估值，判斷貴不貴（在個股分析的「財務體質」分頁）", "📈 個股分析"),
        ("5️⃣ 執行與風險控管", "部位大小、停損停利、持續追蹤", "💼 投資組合管理"),
    ]
    for _col, (_t, _d, _target) in zip(st.columns(5), NAV_STEPS):
        with _col:
            with st.container(border=True):
                st.markdown(f"**{_t}**")
                st.caption(_d)
                if st.button(f"前往 {_target.split(' ', 1)[1]}", key=f"nav_{_t}", **STRETCH):
                    st.session_state["_pending_app_mode"] = _target
                    st.rerun()
    st.caption("這是建議路徑，不是強制順序。")

elif app_mode == "📚 教學庫":
    st.title("📚 量化交易與技術指標大百科")
    st.markdown("收錄實戰交易中最核心的技術分析工具與型態圖鑑。")

    st.subheader("📊 1. 基礎 K 線型態 (單根 K 棒)")
    basic_k = {
        "大陽線": "開盤即最低，全日走揚最高收盤。看多情緒極濃烈。",
        "大陰線": "開盤即最高，全日走低最低收盤。看空情緒極濃烈。",
        "下影線 (錘子)": "大跌後遇多頭支撐。連續下跌後出現容易是觸底訊號。",
        "上影線 (避雷針)": "強勢攻擊但在高檔遇賣壓。多頭末段出現為反轉下跌訊號。",
        "十字線": "多空勢均力敵，通常是股價反轉或趨於盤整的前兆。",
        "T字線": "開盤大幅下挫但買單強勢收復。下跌波中出現可能反轉。"
    }
    k_cols = st.columns(2)
    for i, (k_name, k_desc) in enumerate(basic_k.items()):
        with k_cols[i % 2].container(border=True):
            sub_c1, sub_c2 = st.columns([1, 3])
            with sub_c1: st.plotly_chart(draw_kline_illustration(k_name), **STRETCH, config={'displayModeBar': False}, key=f"kline_illust_{k_name}")
            with sub_c2: st.markdown(f"**{k_name}**"); st.write(k_desc)

    st.subheader("📐 2. 進階 K 線反轉與整理型態")
    patterns = {
        "頭肩頂": "三個高峰組成，中央最高。跌破頸線預示大跌。",
        "雙重頂": "高點兩次反彈失敗的 M 頭。跌破支撐線代表型態完成準備下跌。",
        "圓弧頂": "拋物線狀，市場逐步由強轉弱，預示未來可能下跌。",
        "三角收斂": "波動縮小，供需達平衡。一旦突破邊界將表態大行情。",
        "箱型": "一定範圍內波動的橫向整理。突破箱型邊界時形成新趨勢。"
    }
    for p_name, p_desc in patterns.items():
        with st.container(border=True):
            col1, col2 = st.columns([1, 2])
            with col1: st.plotly_chart(draw_pattern_illustration(p_name), **STRETCH, config={'displayModeBar': False}, key=f"pattern_illust_{p_name}")
            with col2: st.markdown(f"### {p_name}"); st.write(p_desc)

    st.subheader("📈 3. 趨勢與振盪指標大全")
    with st.expander("展開查看【技術指標】列表"):
        st.markdown("""
        * **MACD**：黃金交叉(買進)，死亡交叉(賣出)。
        * **RSI (相對強弱指標)**：超過70％為超買區，低於30％為超賣區。
        * **威廉指標 (Williams %R)**：大於-20％為超買，小於-80％為超賣。
        * **CCI (順勢指標)**：無上下限，通常以+100與-100作超買超賣判斷。
        * **布林通道**：根據通道放大與收縮分析趨勢。
        """)

# ==========================================
# 模式：💼 投資組合管理
# ==========================================
elif app_mode == "💼 投資組合管理":
    st.title("💼 投資組合管理")
    st.caption("輸入你實際持有的股票代號、股數、均價，系統會自動抓即時股價算出市值、損益、操作建議與風控指標。資料存在本機 CSV，重啟不會遺失，不會上傳到任何地方。")

    directory, _live_ok = get_directory()

    with st.expander("➕ 新增 / 更新持股", expanded=True):
        sc1, sc2 = st.columns([2, 1.4])
        pf_query = sc1.text_input("🔍 搜尋股票（打代號或中文名）", key="pf_search_query", placeholder="例如 2330 或 台積電")
        pf_options, pf_total_hits = search_stocks(pf_query, directory)
        if pf_query.strip() and not pf_options:
            pf_options = [pf_query.strip().upper()]
        elif pf_query.strip() and pf_total_hits > len(pf_options):
            sc1.caption(f"找到 {pf_total_hits} 檔，只列出前 {len(pf_options)} 檔，請多打幾個字縮小範圍")
        code_choice = sc2.selectbox(
            "選擇股票", pf_options, key="pf_add_code_select",
            format_func=lambda c: f"{directory[c]['name']}（{c}）" if c in directory else c
        ) if pf_options else None

        fc1, fc2 = st.columns([1.3, 3])
        if fc1.button("💰 用現價帶入均價", disabled=not code_choice, **STRETCH):
            suffix = directory.get(code_choice, {}).get("suffix", ".TW")
            with st.spinner("抓取即時股價中…"):
                ev = evaluate_single_stock(code_choice + suffix, directory)
            if ev and ev.get("price"):
                st.session_state["pf_add_cost"] = round(ev["price"], 2)
                fc2.success(f"已帶入現價 ${ev['price']:.2f}，請確認股數後再按下方「儲存這筆持股」。")
            else:
                fc2.warning("抓不到即時股價，請手動輸入均價。")

        pc2, pc3, pc4 = st.columns([1, 1, 2])
        p_shares = pc2.number_input("股數", min_value=0, value=0, step=100, key="pf_add_shares")
        st.session_state.setdefault("pf_add_cost", 0.0)
        p_cost = pc3.number_input("均價", min_value=0.0, step=0.1, key="pf_add_cost")
        p_note = pc4.text_input("備註（選填）", placeholder="例如：核心持股", key="pf_add_note")
        p_side_label = st.radio("部位方向", ["🟢 多方 (Long)", "🔴 空方 (Short)"], horizontal=True, key="pf_add_side")
        p_side = "Short" if p_side_label.startswith("🔴") else "Long"
        p_tags = st.multiselect("自訂標籤（選填，方便之後篩選分類）", TAG_OPTIONS, key="pf_add_tags")
        if st.button("儲存這筆持股", type="primary"):
            code_clean = (code_choice or normalize_ticker(pf_query).split(".")[0] or "").strip()
            if not code_clean or p_shares <= 0 or p_cost <= 0:
                st.warning("請搜尋並選擇股票、填入股數與均價（股數與均價需大於 0）。")
            else:
                upsert_portfolio_position(code_clean, p_shares, p_cost, p_side, p_note, tags=",".join(p_tags))
                st.success(f"已儲存 {code_clean}（{'空方' if p_side=='Short' else '多方'}），股數 {p_shares}、均價 ${p_cost:.2f}。同代號再次輸入會覆蓋成最新資料。")
                st.rerun()
        st.caption("同一個代號重複輸入會直接覆蓋成最新的股數、均價、方向與標籤（代表你更新了這筆部位），不會疊加。空方部位的損益、停損停利與加碼邏輯會自動反過來計算。")

    with st.expander("💰 現金水位設定（選填，用於倉位配置與資金風險暴露計算）"):
        cash_on_hand = st.number_input("目前可用現金（TWD，不含股票市值）", min_value=0, value=0, step=10000, key="pf_cash")
        risk_cap_pct = st.slider("單筆最大可承受風險（% 總資金，用於資金風險暴露警示）", 0.5, 10.0, 2.0, 0.5, key="pf_risk_cap")
        st.caption("有填現金，風控計算會用「現金＋股票市值」當總資金基準；不填則退而求其次用「股票總市值」計算，準確度較低但仍可參考。")

    portfolio = load_portfolio()
    if portfolio.empty:
        st.info("還沒有任何持股紀錄，在上方新增第一筆部位吧。")
    else:
        with st.spinner("抓取即時股價、跑技術評分、計算市值與風控指標中…（持股較多時需要一點時間）"):
            rows = []
            for _, r in portfolio.iterrows():
                code = str(r['代號']).strip()
                shares, cost = float(r['股數']), float(r['均價'])
                pos_side = str(r.get('方向') or 'Long').strip() or 'Long'
                is_short = (pos_side == 'Short')
                tag_list = [t for t in str(r.get('標籤') or '').split(",") if t.strip()]
                try:
                    tk, info, df_p, _q = load_with_fallback(normalize_ticker(code))
                except Exception:
                    tk, info, df_p = normalize_ticker(code), {}, None

                price = score = bucket = tech_direction = color = near_stop = far_stop = target1 = target2 = can_add = ma20 = None
                if df_p is not None and len(df_p) >= 40:
                    try:
                        df_ind = compute_indicators(df_p)
                        latest, prev = df_ind.iloc[-1], df_ind.iloc[-2]
                        price = latest['Close']
                        k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
                        bt = backtest_score_system(df_ind)
                        tech_direction, _act, _buy, _rem, color, score, bucket = predict_next_day(latest, prev, k_name, [], bt)
                        lv = compute_levels(df_ind, latest, price, score)
                        near_stop, far_stop, target1, target2 = lv['near_stop'], lv['far_stop'], lv['target1'], lv['target2']
                        ma20, can_add = lv['ma20'], lv['can_add']
                    except Exception:
                        pass
                elif df_p is not None and not df_p.empty:
                    price = df_p['Close'].iloc[-1]

                name = resolve_display_name(tk, code, info or {}, directory) if price is not None else (
                    INDUSTRY_MAP.get(tk, {}).get("name") or directory.get(code, {}).get("name") or code)
                industry = directory.get(code, {}).get("ind") or "未知"

                market_value = price * shares if price is not None else None
                cost_basis = cost * shares
                # ---- 多空損益：多方賺的是漲、空方賺的是跌，符號要反過來 ----
                if market_value is not None:
                    pnl_amt = (market_value - cost_basis) if not is_short else (cost_basis - market_value)
                else:
                    pnl_amt = None
                pnl_pct = (pnl_amt / cost_basis * 100) if (pnl_amt is not None and cost_basis > 0) else None

                # ---- 多空停損停利：空方完全反過來——漲過前波高點是停損，跌到支撐才是停利 ----
                if not is_short:
                    pos_stop, pos_stop_far = near_stop, far_stop
                    pos_tp1, pos_tp2 = target1, target2
                    pos_add_price = ma20 if can_add else None
                    dist_stop_pct = (price - pos_stop) / price * 100 if (price and pos_stop) else None
                    dist_tp1_pct = (pos_tp1 - price) / price * 100 if (price and pos_tp1) else None
                else:
                    pos_stop, pos_stop_far = target1, target2
                    pos_tp1, pos_tp2 = near_stop, far_stop
                    pos_add_price = ma20 if (score is not None and score <= 0 and ma20 is not None and ma20 > price) else None
                    dist_stop_pct = (pos_stop - price) / price * 100 if (price and pos_stop) else None
                    dist_tp1_pct = (price - pos_tp1) / price * 100 if (price and pos_tp1) else None

                # ---- 1. 操作指示：多空分開判斷，結合技術分數 + 是否已觸價 ----
                if score is None:
                    action_text, action_color = "資料不足，無法判斷", "off"
                elif dist_stop_pct is not None and dist_stop_pct <= 0:
                    action_text, action_color = ("🛑 已跌破近端停損，應出場" if not is_short else "🛑 已漲過停損價，空單應回補"), "error"
                elif dist_tp1_pct is not None and dist_tp1_pct <= 0:
                    action_text, action_color = "✅ 已達第一停利，可分批獲利了結", "success"
                elif not is_short:
                    if score >= 40:
                        action_text, action_color = "續抱，回檔至加碼價可分批加碼", "success"
                    elif score >= 0:
                        action_text, action_color = "續抱觀察，不追高不加碼", "info"
                    elif score > -30:
                        action_text, action_color = ("獲利減碼保護，技術轉弱" if (pnl_pct or 0) > 0 else "技術轉弱，嚴設停損"), "warning"
                    else:
                        action_text, action_color = "偏空訊號明確，建議減碼或出場", "error"
                else:  # 空方：技術面分數的解讀要反過來——分數轉多對空單是壞消息
                    if score <= -30:
                        action_text, action_color = "續抱，反彈至加碼價可分批加碼空單", "success"
                    elif score <= 0:
                        action_text, action_color = "續抱觀察，不追空不加碼", "info"
                    elif score < 40:
                        action_text, action_color = ("獲利減碼保護，技術轉多" if (pnl_pct or 0) > 0 else "技術轉多，空單風險增加，嚴設停損"), "warning"
                    else:
                        action_text, action_color = "技術面明確轉多，空單風險高，建議減碼或回補", "error"

                # ---- 4. 動態移動停利提醒（多空皆適用：獲利越多，防守線越該往保本方向移動）----
                trailing_note = None
                if pnl_pct is not None:
                    if pnl_pct >= 30:
                        trailing_note = f"🎯 獲利已達 {pnl_pct:.0f}%，建議把停損移到至少成本價（保本）以上，鎖住大部分利潤"
                    elif pnl_pct >= 15:
                        trailing_note = f"🎯 獲利已達 {pnl_pct:.0f}%，建議把停損移到成本價（保本），避免獲利吐回"

                # ---- 1. 個別持股資金風險暴露（觸及停損對總資金的影響；多空都算「價格往不利方向走到停損」的虧損）----
                if price and pos_stop:
                    risk_amt = max(0.0, (price - pos_stop) if not is_short else (pos_stop - price)) * shares
                else:
                    risk_amt = None

                rows.append(dict(code=code, name=name, shares=shares, cost=cost, price=price, industry=industry,
                                 market_value=market_value, cost_basis=cost_basis, pnl_amt=pnl_amt, pnl_pct=pnl_pct,
                                 note=r.get('備註') or "", pos_side=pos_side, is_short=is_short,
                                 tech_direction=tech_direction, color=color, score=score,
                                 pos_stop=pos_stop, pos_stop_far=pos_stop_far, pos_tp1=pos_tp1, pos_tp2=pos_tp2,
                                 dist_stop_pct=dist_stop_pct, dist_tp1_pct=dist_tp1_pct, pos_add_price=pos_add_price,
                                 action_text=action_text, action_color=action_color, trailing_note=trailing_note,
                                 risk_amt=risk_amt, tags=tag_list))

        total_mv = sum(x['market_value'] for x in rows if x['market_value'] is not None)
        total_cost = sum(x['cost_basis'] for x in rows)
        total_pnl = total_mv - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else None
        n_missing = sum(1 for x in rows if x['market_value'] is None)
        total_capital = (cash_on_hand + total_mv) if cash_on_hand > 0 else total_mv

        st.markdown("#### 📊 即時資產戰情室")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("總市值", f"${total_mv:,.0f}")
        k2.metric("總成本", f"${total_cost:,.0f}")
        k3.metric("未實現損益", f"${total_pnl:,.0f}", f"{total_pnl_pct:+.1f}%" if total_pnl_pct is not None else None,
                 delta_color="normal" if total_pnl >= 0 else "inverse")
        k4.metric("持股檔數", f"{len(rows)} 檔")
        if n_missing:
            st.warning(f"⚠️ 有 {n_missing} 檔抓不到即時股價，暫不計入總市值與損益，請確認代號是否正確。")

        # ---- 快速跳轉個股分析：選一檔持股，直接切到「📈 個股分析」並自動帶入該股票 ----
        jc1, jc2 = st.columns([3, 1])
        jump_options = [f"{x['name']}（{x['code']}）" for x in rows]
        jump_code_by_label = {f"{x['name']}（{x['code']}）": x['code'] for x in rows}
        jump_label = jc1.selectbox("🔎 快速跳轉個股分析", jump_options, key="pf_jump_select", label_visibility="collapsed")
        if jc2.button("📈 前往個股分析", **STRETCH):
            st.session_state["_pending_app_mode"] = "📈 個股分析"
            st.session_state["_pending_stock_code"] = jump_code_by_label[jump_label]
            st.rerun()
        st.caption("點擊後會立即切換到「📈 個股分析」分頁，並自動載入該檔股票完整的技術指標、公司與產業、財務體質分析。")

        # ---- 2. 倉位水位與現金配置 ----
        if cash_on_hand > 0:
            stock_pct = total_mv / total_capital * 100 if total_capital > 0 else None
            cash_pct = 100 - stock_pct if stock_pct is not None else None
            st.markdown("#### 💰 倉位水位")
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("股票部位佔比", f"{stock_pct:.1f}%" if stock_pct is not None else "—")
            cc2.metric("現金部位佔比", f"{cash_pct:.1f}%" if cash_pct is not None else "—")
            cc3.metric("總資金（現金＋市值）", f"${total_capital:,.0f}")

            macro_flags = get_macro_risk_flags()
            if macro_flags and stock_pct is not None and stock_pct >= 70:
                st.error(
                    f"🚨 總經風險警示與高持股比同時出現：目前股票倉位 {stock_pct:.0f}%，而「📡 總經雷達」偵測到 "
                    + "、".join(macro_flags) + "。建議檢視手上部位，評估是否該降低曝險或緊縮停損。"
                )
            elif macro_flags:
                st.warning("⚠️ 「📡 總經雷達」目前偵測到風險訊號：" + "、".join(macro_flags) + "，雖然你的倉位比例還算健康，仍建議留意後續走勢。")
            elif stock_pct is not None and stock_pct >= 90:
                st.warning(f"⚠️ 股票倉位高達 {stock_pct:.0f}%，現金緩衝很薄，若大盤出現風險警示（見「📡 總經雷達」）會較難應對，可考慮保留更多現金。")

        for x in rows:
            x['weight_pct'] = (x['market_value'] / total_mv * 100) if (x['market_value'] is not None and total_mv > 0) else None
            x['risk_pct_of_capital'] = (x['risk_amt'] / total_capital * 100) if (x['risk_amt'] is not None and total_capital > 0) else None

        table_df = pd.DataFrame([{
            "股票": f"{x['name']}（{x['code']}）",
            "部位": "🟢 多方" if not x['is_short'] else "🔴 空方",
            "技術方向": x['tech_direction'] or "資料不足", "操作建議": x['action_text'],
            "股數": int(x['shares']), "均價": round(x['cost'], 2),
            "現價": round(x['price'], 2) if x['price'] is not None else None,
            "市值": round(x['market_value'], 0) if x['market_value'] is not None else None,
            "損益(%)": round(x['pnl_pct'], 2) if x['pnl_pct'] is not None else None,
            "佔比(%)": round(x['weight_pct'], 1) if x['weight_pct'] is not None else None,
            "加碼參考價": round(x['pos_add_price'], 2) if x['pos_add_price'] is not None else None,
            "停損價": round(x['pos_stop'], 2) if x['pos_stop'] is not None else None,
            "距停損(%)": round(x['dist_stop_pct'], 1) if x['dist_stop_pct'] is not None else None,
            "第一停利": round(x['pos_tp1'], 2) if x['pos_tp1'] is not None else None,
            "距第一停利(%)": round(x['dist_tp1_pct'], 1) if x['dist_tp1_pct'] is not None else None,
            "第二停利": round(x['pos_tp2'], 2) if x['pos_tp2'] is not None else None,
            "資金風險暴露(%)": round(x['risk_pct_of_capital'], 2) if x['risk_pct_of_capital'] is not None else None,
            "備註": x['note'],
        } for x in rows])
        # ---- 精簡卡片視圖：每檔只露出最核心的 5 項，細節收進展開區 ----
        all_tags = sorted({t for x in rows for t in x['tags']})
        tag_filter = st.multiselect("🏷️ 依標籤篩選持股", all_tags, key="pf_tag_filter") if all_tags else []
        shown_rows = [x for x in rows if not tag_filter or any(t in x['tags'] for t in tag_filter)]

        def _action_level(color):
            return {"success": "green", "info": "gray", "warning": "yellow", "error": "red"}.get(color, "gray")

        st.markdown("#### 📋 持股一覽")
        for x in shown_rows:
            with st.container(border=True):
                h1, h2, h3, h4, h5 = st.columns([2.2, 1, 1.3, 1, 2.6])
                side_pill = pill("多方", "green") if not x['is_short'] else pill("空方", "red")
                h1.markdown(f"**{x['name']}（{x['code']}）** {side_pill}", unsafe_allow_html=True)
                if x['tags']:
                    h1.markdown(" ".join(pill(t, "gray") for t in x['tags']), unsafe_allow_html=True)
                h2.metric("現價", f"{x['price']:.2f}" if x['price'] is not None else "—")
                h3.metric("市值", f"{x['market_value']:,.0f}" if x['market_value'] is not None else "—")
                if x['pnl_pct'] is not None:
                    h4.metric("損益", f"{x['pnl_pct']:+.1f}%", delta=None)
                else:
                    h4.metric("損益", "—")
                h5.markdown("**操作建議**")
                h5.markdown(pill(x['action_text'], _action_level(x['action_color'])), unsafe_allow_html=True)
                with st.expander("展開價位與風控細節"):
                    d1, d2, d3, d4 = st.columns(4)
                    d1.metric("加碼參考價", f"{x['pos_add_price']:.2f}" if x['pos_add_price'] is not None else "暫不建議",
                              help="多方：拉回月線且分數未轉弱才建議加碼；空方：反彈到月線且分數偏空才建議加碼空單")
                    d2.metric("停損價", f"{x['pos_stop']:.2f}" if x['pos_stop'] is not None else "—",
                              f"距 {x['dist_stop_pct']:.1f}%" if x['dist_stop_pct'] is not None else None, delta_color="off",
                              help="取月線結構停損與 ATR 波動度停損中較貼近現價者；空方方向相反")
                    d3.metric("第一停利", f"{x['pos_tp1']:.2f}" if x['pos_tp1'] is not None else "—",
                              f"距 {x['dist_tp1_pct']:.1f}%" if x['dist_tp1_pct'] is not None else None, delta_color="off")
                    d4.metric("第二停利", f"{x['pos_tp2']:.2f}" if x['pos_tp2'] is not None else "—")
                    e1, e2, e3, e4 = st.columns(4)
                    e1.metric("股數", f"{int(x['shares']):,}")
                    e2.metric("均價", f"{x['cost']:.2f}")
                    e3.metric("佔比", f"{x['weight_pct']:.1f}%" if x['weight_pct'] is not None else "—")
                    e4.metric("資金風險暴露", f"{x['risk_pct_of_capital']:.2f}%" if x['risk_pct_of_capital'] is not None else "—",
                              help="萬一觸及停損，對你整體總資金造成的虧損%")
                    st.caption(f"技術方向：{x['tech_direction'] or '資料不足'}　·　產業：{x['industry']}" + (f"　·　備註：{x['note']}" if x['note'] else ""))

        with st.expander("📊 完整寬表格（所有欄位，適合匯出或大螢幕檢視）"):
            st.dataframe(table_df, **STRETCH, hide_index=True)
        st.caption(
            "「部位」是你設定的多方／空方；「技術方向」是量化模型對這檔股票目前的技術面解讀，兩者不一定一致——例如空方部位搭配「技術面偏多」就是風險訊號。"
            "空方的「停損價」「停利價」已自動反轉方向計算（停損在上、停利在下）。"
            "「距停損(%)」「距第一停利(%)」正值代表還沒到、負值代表已經觸價；「資金風險暴露(%)」＝觸及停損時的虧損金額÷總資金，"
            "代表「萬一這筆部位觸及停損，對你整體資金會造成多少%虧損」，超過你設定的單筆風險上限時下方會跳出警示。"
        )

        # ---- 1. 資金風險暴露彙總警示 ----
        high_risk = [x for x in rows if x['risk_pct_of_capital'] is not None and x['risk_pct_of_capital'] > risk_cap_pct]
        if high_risk:
            names = "、".join(f"{x['name']}（{x['risk_pct_of_capital']:.1f}%）" for x in high_risk)
            st.error(f"🚨 以下持股若跌到停損出場，單筆虧損會超過你設定的 {risk_cap_pct:.1f}% 風險上限：{names}。建議考慮減碼或下移加碼計畫。")

        # ---- 4. 移動停利提醒彙總 ----
        trailing_hits = [x for x in rows if x['trailing_note']]
        if trailing_hits:
            st.markdown("#### 🎯 移動停利提醒")
            for x in trailing_hits:
                st.info(f"**{x['name']}（{x['code']}）**　{x['trailing_note']}")

        if total_mv > 0:
            st.markdown("#### 🧪 壓力測試沙盒（What-if）")
            shock = st.slider("假設大盤一天內漲跌多少 %？", -10.0, 10.0, -2.0, 0.5, key="pf_stress_shock",
                              help="簡化假設：每檔持股都跟大盤等幅度同向變動（beta=1）。實際上高波動股通常跌更多、防禦股跌較少，這只是粗估。")
            delta_total = 0.0
            for x in rows:
                if x['market_value'] is not None:
                    move = x['market_value'] * shock / 100.0
                    delta_total += (-move if x['is_short'] else move)
            base_capital = total_capital if total_capital > 0 else total_mv
            s1, s2, s3 = st.columns(3)
            s1.metric("預估資產變動", f"${delta_total:+,.0f}", delta_color="normal" if delta_total >= 0 else "inverse")
            s2.metric("佔總資金", f"{delta_total / base_capital * 100:+.2f}%" if base_capital > 0 else "—")
            s3.metric("情境後總資產", f"${base_capital + delta_total:,.0f}")
            st.caption("空方部位在大盤下跌時會獲利、上漲時虧損，已自動反向計算。這是等比例同步變動的粗估，不包含個股獨立風險、跳空與流動性問題。")

            st.markdown("#### 🥧 資產配置權重（個股）")
            weight_series = pd.Series(
                {f"{x['name']}（{x['code']}）": x['weight_pct'] for x in rows if x['weight_pct'] is not None}
            ).sort_values(ascending=False)
            st.bar_chart(weight_series)
            top1 = weight_series.index[0]
            if weight_series.iloc[0] >= 40:
                st.warning(f"⚠️ 單一持股「{top1}」佔比高達 {weight_series.iloc[0]:.1f}%，集中度偏高，留意個股風險對整體資產的影響。")

            # ---- 3. 產業賽道集中度雷達 ----
            st.markdown("#### 🏭 產業賽道集中度")
            ind_mv = {}
            for x in rows:
                if x['market_value'] is not None:
                    ind_mv[x['industry']] = ind_mv.get(x['industry'], 0) + x['market_value']
            ind_series = pd.Series(ind_mv).sort_values(ascending=False)
            ind_pct = ind_series / ind_series.sum() * 100
            st.bar_chart(ind_pct)
            top_ind, top_ind_pct = ind_pct.index[0], ind_pct.iloc[0]
            if top_ind_pct >= 70:
                st.error(f"🚨 「{top_ind}」產業佔整體持股 {top_ind_pct:.0f}%，過度集中在單一賽道，一旦該產業系統性利空，資產會同步重挫，建議分散配置。")
            elif top_ind_pct >= 50:
                st.warning(f"⚠️ 「{top_ind}」產業佔整體持股 {top_ind_pct:.0f}%，集中度偏高，留意該產業的系統性風險。")

        render_portfolio_balance(rows, cash_on_hand, total_capital, total_mv, directory)

        exp_p1, exp_p2 = st.columns(2)
        with exp_p1:
            csv_pf = table_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ 匯出成 CSV", data=csv_pf, file_name="portfolio.csv", mime="text/csv", **STRETCH)
        with exp_p2:
            xlsx_pf = to_excel_bytes(table_df)
            if xlsx_pf:
                st.download_button("⬇️ 匯出成 Excel", data=xlsx_pf, file_name="portfolio.xlsx",
                                  mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **STRETCH)
            else:
                st.caption("本機未安裝 openpyxl，暫時只能匯出 CSV。")

        with st.expander("🗑️ 刪除持股"):
            del_opts = [f"{x['name']}（{x['code']}）" for x in rows]
            code_by_label = {f"{x['name']}（{x['code']}）": x['code'] for x in rows}
            to_del = st.multiselect("選擇要刪除的持股", del_opts)
            if to_del and st.button("刪除選取的持股"):
                delete_portfolio_positions([code_by_label[d] for d in to_del])
                st.rerun()

    st.caption("⚠️ 市值、損益、操作建議與風控指標皆為規則式試算，未計入手續費、交易稅與股利，僅供個人記錄與風控參考，不構成投資建議。")

elif app_mode == "🔔 到價通知":
    render_alerts_page()

elif app_mode == "📰 盤前必讀":
    render_premarket_page()

elif app_mode == "📊 ETF 專區":
    render_etf_page()

elif app_mode == "🤖 模擬自動交易":
    render_sandbox_page()

elif app_mode == "🔥 資金熱力圖":
    st.title("🔥 資金流動熱力圖")
    st.caption("方塊越大＝成交值越大，顏色＝今日漲跌幅。3 秒看出今天的錢集中在哪個族群、哪些族群在熄火。")

    _hm_directory, _hm_live = get_directory()
    with st.container(border=True):
        hc1, hc2, hc3 = st.columns([1.4, 1.6, 1.4])
        hm_scale_name = hc1.radio("配色習慣", list(HEAT_SCALES.keys()), key="hm_scale")
        hm_size = hc2.slider("取成交量前幾大個股", 40, 300, 120, 20, key="hm_size",
                             help="數字越大涵蓋越完整，但要抓的個股資料越多，首次載入會久一點（之後 10 分鐘內有快取）。")
        hm_stocks = hc3.checkbox("展開顯示個股方塊", value=True, key="hm_stocks",
                                 help="取消勾選只看產業層級，畫面更簡潔。")

    _pool, _pool_ok = heatmap_pool(_hm_directory, hm_size)
    if not _pool_ok:
        st.warning("全市場成交量排行暫時抓不到（證交所來源），已改用內建的常用股名單，涵蓋範圍較小。")
    _tickers = tuple(c + _hm_directory.get(c, {}).get("suffix", ".TW") for c in _pool)
    with st.spinner(f"抓取 {len(_tickers)} 檔個股報價中…（首次載入較久）"):
        _quotes = fetch_heat_quotes(_tickers)

    if _quotes is None or _quotes.empty or len(_quotes) < 5:
        st.error("抓不到足夠的報價資料，無法繪製熱力圖。請稍後再試，或檢查網路連線。")
    else:
        _q, _sec = build_sector_table(_quotes, _hm_directory)
        _big = _sec[_sec["share"] >= 3]
        _best = (_big if not _big.empty else _sec).sort_values("chg", ascending=False).iloc[0]
        _worst = (_big if not _big.empty else _sec).sort_values("chg", ascending=True).iloc[0]
        _top = _sec.iloc[0]
        st.markdown(
            f"**成交最集中**：{_top['sector']}（占 {_top['share']:.0f}%，加權 {_top['chg']:+.2f}%）　"
            f"**漲幅最強**：{_best['sector']}（{_best['chg']:+.2f}%）　"
            f"**跌幅最重**：{_worst['sector']}（{_worst['chg']:+.2f}%）")
        st.caption(f"資料日期 {_q['asof'].mode().iloc[0]}　·　樣本 {len(_q)} 檔　·　上漲 {int((_q['chg'] > 0).sum())} 檔、下跌 {int((_q['chg'] < 0).sum())} 檔")

        st.plotly_chart(draw_sector_treemap(_q, _sec, HEAT_SCALES[hm_scale_name], hm_stocks), **STRETCH, key="sector_heatmap")

        st.markdown("#### 📋 族群資金一覽")
        _view = pd.DataFrame({
            "族群": _sec["sector"], "成交值占比(%)": _sec["share"].round(1), "加權漲跌(%)": _sec["chg"].round(2),
            "上漲家數": _sec["up"].astype(int).astype(str) + " / " + _sec["n"].astype(int).astype(str)})
        st.dataframe(_view, hide_index=True, **STRETCH)

        _sc1, _sc2 = st.columns(2)
        with _sc1:
            st.markdown("**🟢 領漲個股（成交值前段班）**")
            for _, r in _q.sort_values("chg", ascending=False).head(5).iterrows():
                st.markdown(f"- {r['name']}（{r['code']}）{r['chg']:+.2f}%　<span style='color:#7b8794'>{r['sector']}</span>", unsafe_allow_html=True)
        with _sc2:
            st.markdown("**🔴 領跌個股**")
            for _, r in _q.sort_values("chg", ascending=True).head(5).iterrows():
                st.markdown(f"- {r['name']}（{r['code']}）{r['chg']:+.2f}%　<span style='color:#7b8794'>{r['sector']}</span>", unsafe_allow_html=True)

        with st.expander("❓ 這張圖怎麼看、有什麼限制"):
            st.markdown(
                "- **方塊大小**＝成交值（收盤價×成交股數，近似值），代表錢集中在哪裡。\n"
                "- **顏色**＝當日漲跌幅（族群顏色是依成交值加權的平均）。大方塊又大漲＝資金湧入；大方塊卻下跌＝主力撤退或獲利了結。\n"
                "- **這不是真正的資金淨流入**：成交值是買賣雙方的總量，不能分辨買超或賣超；要看主力動向還要搭配法人買賣超。\n"
                "- **只涵蓋成交量前 N 大**的個股，冷門股與小型股沒有納入；產業分類採證交所產業別，與市場慣用的題材分類（如 AI、CoWoS）不同。\n"
                "- 資料來自 Yahoo Finance，可能有延遲，點方塊可放大該族群。")

elif app_mode == "🐋 大戶籌碼":
    render_wanglai_page()

elif app_mode == "⭐ 每日候選股":
    st.title("⭐ 每日量化候選股")
    st.warning(
        "⚠️ 以下是技術面、籌碼面、基本面與歷史回測勝率的**規則式加總排序**，不是投資建議、不是明牌推薦。"
        "排名高不代表會漲，請把「為什麼入選」與「潛在風險」都看過再自行判斷，並做好停損與部位控管。"
    )
    directory, _live_ok = get_directory()
    watchlist = get_watchlist()

    with st.container(border=True):
        st.markdown("#### ⚙️ 掃描設定")
        cp1, cp2 = st.columns([1.2, 2])
        pool_options = ["🕒 自動觀察清單" if watchlist else "🕒 自動觀察清單（目前是空的）", "🚀 全市場流動性池", "✍️ 自訂清單"]
        with cp1:
            pool_choice = st.radio("候選池", pool_options)
        with cp2:
            if pool_choice.startswith("✍️"):
                pool_raw = st.text_area("輸入股票代號（逗號或換行分隔）", value=", ".join(INDUSTRY_MAP.keys()), height=100)
                pool = list(dict.fromkeys(normalize_ticker(t) for t in pool_raw.replace("，", ",").replace("\n", ",").split(",") if t.strip()))
            elif pool_choice.startswith("🚀"):
                pool_size = st.slider("流動性池大小（前N大成交量）", 30, 300, 100, 10,
                                      help="數字越大涵蓋越完整，但要抓的個股資料也越多，掃描時間會拉長。")
                pool = None  # 實際按下掃描時才抓（見下方 run_btn）
            else:
                pool = watchlist or list(INDUSTRY_MAP.keys())
                st.caption(f"目前共 {len(pool)} 檔（在「📈 個股分析」查看過的股票會自動加進來）")

        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            with st.expander("🎛️ 技術面篩選"):
                tech_filter = st.multiselect("必須符合（多選＝全部成立）", list(TECH_FILTER_OPTIONS.keys()))
                if tech_filter:
                    st.caption("只有同時符合所有條件的股票才會入選，條件越多、檔數通常越少。")
        with fc2:
            with st.expander("🔎 基本面硬篩"):
                use_filter = st.checkbox("啟用基本面篩選", value=False)
                min_roe = st.slider("最低 ROE (%)", 0, 30, 15) if use_filter else None
                max_dte = st.slider("最高負債權益比", 20, 300, 100) if use_filter else None
                require_eps = st.checkbox("要求 EPS 為正", value=True) if use_filter else False
                require_ocf = st.checkbox("要求營業現金流為正", value=True) if use_filter else False
                require_fcf = st.checkbox("要求自由現金流為正", value=False) if use_filter else False
                if use_filter:
                    st.caption("資料缺失時預設不刷掉，避免 Yahoo 沒填欄位就被誤刪；請自行確認財報。")
        with fc3:
            with st.expander("🎯 風報比篩選"):
                rr_choice = st.radio("只保留 RR 大於…", ["不限制", "1 : 1.5", "1 : 2", "1 : 3"], index=0)
                min_rr = {"不限制": None, "1 : 1.5": 1.5, "1 : 2": 2.0, "1 : 3": 3.0}[rr_choice]
                if min_rr:
                    st.caption("RR ＝（第一停利－現價）÷（現價－近端停損）。避免選到停損空間太大、賺賠不對稱的標的。")
        with fc4:
            with st.expander("🏭 產業賽道"):
                industry_filter = st.multiselect("只看這些產業（不選＝不限制）", sorted(set(TW_INDUSTRY_CODE.values())))
                if industry_filter:
                    st.caption("先選賽道、再挑個股——由下而上選股法的第一步。")

        rb1, rb2 = st.columns([3, 1])
        top_n = rb1.slider("顯示前幾名", 3, 20, 5)
        rb2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        run_btn = rb2.button("🔍 開始掃描", type="primary", **STRETCH)

    if run_btn:
        if pool_choice.startswith("🚀"):
            with st.spinner("抓取全市場成交量排行中…"):
                pool, pool_ok = build_smart_pool(directory, size=pool_size)
            if not pool_ok:
                st.error("全市場成交量資料暫時抓不到（證交所來源問題），已退回內建常用清單代替，範圍會小很多。")
        if not pool:
            st.warning("候選池是空的，請至少輸入一檔股票，或先去「📈 個股分析」查看幾檔累積自動觀察清單。")
        else:
            fund_filter = dict(min_roe=min_roe / 100 if min_roe else None, max_dte=max_dte,
                               require_positive_ocf=require_ocf, require_positive_fcf=require_fcf,
                               require_positive_eps=require_eps) if use_filter else None
            with st.spinner(f"多維度掃描 {len(pool)} 檔股票中…（含籌碼連買偵測與交易計畫試算，池子越大耗時越久）"):
                code_list = [t.split(".")[0] for t in pool]
                streak_map = get_institutional_streaks(code_list, days=5) or {}
                candidates = scan_candidates(pool, streak_map, fund_filter=fund_filter, directory=directory,
                                            tech_filter=tech_filter, min_rr=min_rr, industry_filter=industry_filter or None)
            st.session_state['candidates_result'] = candidates
            st.session_state['candidates_chip_ok'] = bool(streak_map)
            st.session_state['candidates_pool_n'] = len(pool)

    candidates = st.session_state.get('candidates_result')
    if candidates:
        st.caption(f"本次掃描 {st.session_state.get('candidates_pool_n', '?')} 檔，符合條件並成功分析 {len(candidates)} 檔。")
        if not st.session_state.get('candidates_chip_ok'):
            st.info("ℹ️ 這次掃描籌碼連續買賣超資料暫時抓不到（證交所資料來源問題），排名僅以技術面＋基本面＋歷史回測勝率計算。")
        shown = candidates[:top_n]
        if not shown:
            st.info("候選池裡沒有股票符合篩選條件或有足夠的歷史資料，試著放寬基本面門檻或換一個候選池。")
        for i, c in enumerate(shown, 1):
            with st.container(border=True):
                h1, h2, h3 = st.columns([3, 1, 1])
                h1.markdown(f"### #{i}　{c['name']}（{c['code']}）")
                h2.metric("現價", f"${c['price']:.2f}")
                h3.metric("綜合分數", f"{c['composite']:+d}")

                st.caption(radar_verdict(c['tech'], c['fund'], c['has_chip_data'], c['chip']))
                sb1, sb2, sb3 = st.columns(3)
                with sb1:
                    bar = _radar_bar(c['tech'], -75, 55)
                    st.progress(bar if bar is not None else 0.0, text=f"🟢 技術動能　{c['tech']:+d} 分")
                    st.caption("MACD、威廉指標、月線位置")
                with sb2:
                    bar = _radar_bar(c['fund'], -45, 25)
                    st.progress(bar if bar is not None else 0.0, text=f"🔵 基本面體質　{c['fund']:+d} 分")
                    st.caption("EPS、營收年增、毛利率、負債比")
                with sb3:
                    if c['has_chip_data']:
                        bar = _radar_bar(c['chip'], -25, 25)
                        st.progress(bar if bar is not None else 0.0, text=f"🟣 法人籌碼　{c['chip']:+d} 分")
                    else:
                        st.progress(0.0, text="🟣 法人籌碼　無資料")
                    st.caption("外資／投信連續買賣超天數")
                st.metric("歷史勝率", f"{c['wr']:.0f}%（N={c['n']}）" if c['wr'] is not None and c['n'] is not None else "樣本不足")

                st.markdown(f"**📋 交易計畫｜{c['direction']}｜{c['entry_action']}**")
                p1, p2, p3, p4, p5 = st.columns(5)
                p1.metric("參考買價", f"${c['buy_price']:.2f}")
                p2.metric("近端停損", f"${c['stop']:.2f}")
                p3.metric("第一停利", f"${c['target1']:.2f}")
                p4.metric("第二停利", f"${c['target2']:.2f}")
                p5.metric("風險報酬比", f"1 : {c['rr']:.1f}" if c['rr'] is not None else "—")
                if c['horizon']:
                    h = c['horizon']
                    st.caption(f"📊 歷史同類進場的平均結果：報酬 {h['avg_return']:+.1f}%、約 {h['avg_days']:.0f} 個交易日內出場、"
                              f"勝率 {h['win_rate']:.0f}%（N={h['n']} 筆歷史交易）。這是這檔股票過去實際模擬交易的統計，不是預測保證。")
                else:
                    st.caption("📊 歷史同類進場次數過少，無法估計預期報酬與天數。")

                rc1, rc2 = st.columns(2)
                with rc1:
                    st.markdown("**✅ 為什麼入選**")
                    for r in c['reasons'] or ["—"]:
                        st.markdown(f"- {r}")
                with rc2:
                    st.markdown("**⚠️ 潛在風險**")
                    for r in c['risks'] or ["—"]:
                        st.markdown(f"- {r}")

                if st.button("📝 存入策略日誌", key=f"journal_{c['ticker']}_{i}"):
                    ok = append_journal_entry({
                        "存入時間": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                        "代號": c['code'], "名稱": c['name'], "分數": c['composite'], "分數區間": score_to_bucket(c['tech']),
                        "方向": c['direction'], "存入時股價": c['price'], "參考買價": c['buy_price'],
                        "近端停損": c['stop'], "第一停利": c['target1'], "第二停利": c['target2'],
                        "預計天數(歷史平均)": round(c['horizon']['avg_days'], 1) if c['horizon'] else None,
                    })
                    st.toast("已存入策略日誌！" if ok else "存檔失敗，可能是檔案系統無法寫入。")

        result_df = pd.DataFrame([{"代號": c['code'], "名稱": c['name'], "現價": c['price'], "綜合分數": c['composite'],
                                   "技術面": c['tech'], "基本面": c['fund'], "籌碼面": c['chip'] if c['has_chip_data'] else None,
                                   "歷史勝率(%)": c['wr'], "樣本數": c['n'], "方向": c['direction'],
                                   "參考買價": c['buy_price'], "近端停損": c['stop'], "第一停利": c['target1'], "第二停利": c['target2'],
                                   "預期報酬(%)": c['horizon']['avg_return'] if c['horizon'] else None,
                                   "預計天數": c['horizon']['avg_days'] if c['horizon'] else None} for c in shown])
        exp_cd1, exp_cd2 = st.columns(2)
        with exp_cd1:
            csv_data = result_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ 匯出成 CSV", data=csv_data, file_name="daily_candidates.csv", mime="text/csv", **STRETCH)
        with exp_cd2:
            xlsx_cd = to_excel_bytes(result_df)
            if xlsx_cd:
                st.download_button("⬇️ 匯出成 Excel", data=xlsx_cd, file_name="daily_candidates.xlsx",
                                  mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **STRETCH)
            else:
                st.caption("本機未安裝 openpyxl，暫時只能匯出 CSV。")

        st.caption(
            "計算方式：技術面＝MACD／威廉指標／K棒／月線位置；基本面＝EPS、ROE、營收年增、毛利率、營益率、營運/自由現金流、負債權益比；"
            "籌碼面＝外資與投信近5個交易日的連續買賣超（僅涵蓋上市 .TW）；歷史勝率與預期報酬天數＝這檔股票過去同一分數區間的實際回測結果。"
            "四項僅是規則式加總，權重為經驗設定，過去統計不代表未來績效，不構成投資建議。"
        )
    else:
        st.info("設定候選池後，按左側「🔍 開始掃描候選股」。")

elif app_mode == "🗂 觀察清單掃描":
    st.title("🗂 觀察清單掃描")
    st.caption("⚠️ 分數與回測皆為規則式試算，非統計顯著驗證過的模型，也不構成投資建議。過去表現不代表未來績效。")

    with st.expander("💾 觀察清單備份／還原（匯出成 CSV、或匯入別台電腦的備份）"):
        _wl_now = get_watchlist()
        _wl_df = pd.DataFrame({"代號": [t.split(".")[0] for t in _wl_now], "完整代號": _wl_now})
        wl_c1, wl_c2 = st.columns(2)
        with wl_c1:
            st.caption(f"目前共 {len(_wl_now)} 檔")
            if _wl_now:
                st.download_button("⬇️ 匯出觀察清單 CSV", data=_wl_df.to_csv(index=False).encode("utf-8-sig"),
                                  file_name="watchlist_backup.csv", mime="text/csv", key="wl_export_csv")
                _wl_xlsx = to_excel_bytes(_wl_df)
                if _wl_xlsx:
                    st.download_button("⬇️ 匯出觀察清單 Excel", data=_wl_xlsx, file_name="watchlist_backup.xlsx",
                                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="wl_export_xlsx")
            else:
                st.caption("清單是空的，沒有東西可以匯出。")
        with wl_c2:
            up = st.file_uploader("匯入備份 CSV（需有「完整代號」欄位，或任何一欄是股票代號）", type=["csv"], key="wl_import")
            if up is not None:
                try:
                    up_df = pd.read_csv(up)
                    col = "完整代號" if "完整代號" in up_df.columns else up_df.columns[0]
                    imported = [normalize_ticker(str(t)) for t in up_df[col].dropna().tolist()]
                    imported = [t for t in imported if t]
                    if imported:
                        merge_watchlist(imported)
                        st.success(f"已匯入 {len(imported)} 檔，合併進觀察清單。")
                        st.rerun()
                    else:
                        st.warning("這個檔案裡沒有找到看起來像股票代號的內容。")
                except Exception as e:
                    st.error(f"匯入失敗，請確認檔案格式：{e}")

    watchlist_tks = get_watchlist()
    pool_options = list(dict.fromkeys(watchlist_tks + list(INDUSTRY_MAP.keys())))
    pool_default = watchlist_tks if watchlist_tks else list(INDUSTRY_MAP.keys())
    _directory_for_names, _ = get_directory()

    def _pool_label(k):
        bare = k.split(".")[0]
        nm = INDUSTRY_MAP.get(k, {}).get("name") or _directory_for_names.get(bare, {}).get("name")
        return f"{nm}（{bare}）" if nm else bare

    with st.container(border=True):
        st.markdown("#### ⚙️ 掃描設定")
        picked = st.multiselect("觀察清單（自動記錄你在「個股分析」看過的股票）", pool_options, default=pool_default, format_func=_pool_label)
        sc1, sc2 = st.columns([3, 1])
        extra_raw = sc1.text_input("再加其他代號（逗號分隔）", placeholder="例如 2317, 2412")
        sc2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        scan_btn = sc2.button("開始掃描", type="primary", **STRETCH)
        st.caption(f"目前觀察清單共 {len(watchlist_tks)} 檔" + ("（尚未瀏覽過任何股票，先顯示預設常用股）" if not watchlist_tks else "。"))

    def interpret_signal(win_rate, sample_n):
        """
        用「歷史勝率偏離50%的幅度」而非分數本身來給訊號解讀，
        因為分數的高低不代表真的準，勝率才是真正驗證過的依據。
        """
        if sample_n is None or sample_n < 10:
            return "樣本不足，無法判斷"
        if win_rate is None:
            return "無歷史資料"
        edge = win_rate - 50
        if abs(edge) < 5:
            return "⚪ 接近五五波，此分數區間無明顯優勢"
        elif edge >= 15:
            return f"🟢 歷史明顯偏多({win_rate:.0f}%)，仍建議搭配停損"
        elif edge >= 5:
            return f"🟡 歷史略偏多({win_rate:.0f}%)，優勢不大"
        elif edge <= -15:
            return f"🔴 歷史明顯偏空({win_rate:.0f}%)，不建議偏多操作"
        else:
            return f"🟠 歷史略偏空({win_rate:.0f}%)，不建議偏多操作"

    if scan_btn:
        extras = [normalize_ticker(t) for t in extra_raw.replace("，", ",").split(",") if t.strip()]
        tickers = list(dict.fromkeys(list(picked) + extras))
        if not tickers:
            st.warning("請至少選擇一檔股票。")
            st.stop()
        results = []
        progress = st.progress(0.0, text="掃描中...")
        for idx, tk in enumerate(tickers):
            try:
                info, df, _ = load_stock_data(tk)
                if df.empty or len(df) < 40:
                    results.append({"代號": tk, "名稱": "資料不足", "狀態": "略過"})
                    continue
                df_ind = compute_indicators(df)
                latest, prev = df_ind.iloc[-1], df_ind.iloc[-2]
                k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
                score = compute_score(latest, prev, k_name, patterns=None)
                bucket = score_to_bucket(score)
                bt_stats = backtest_score_system(df_ind)
                win_rate = None
                sample_n = None
                if bt_stats is not None and not bt_stats.empty and bucket in bt_stats.index:
                    win_rate = bt_stats.loc[bucket, '上漲機率(%)']
                    sample_n = bt_stats.loc[bucket, '樣本數']

                name = resolve_display_name(tk, tk.split(".")[0], info, _directory_for_names)
                results.append({
                    "代號": tk, "名稱": name, "收盤價": round(latest['Close'], 2),
                    "綜合分數": score, "分數區間": bucket,
                    "區間歷史勝率(%)": round(win_rate, 1) if win_rate is not None else None,
                    "區間樣本數": int(sample_n) if sample_n is not None else None,
                    "訊號解讀": interpret_signal(win_rate, sample_n),
                    "狀態": "完成"
                })
            except Exception as e:
                results.append({"代號": tk, "名稱": "抓取失敗", "狀態": f"錯誤: {e}"})
            progress.progress((idx + 1) / len(tickers), text=f"掃描中... ({idx+1}/{len(tickers)})")
        progress.empty()

        result_df = pd.DataFrame(results)
        if "綜合分數" in result_df.columns:
            result_df = result_df.sort_values("綜合分數", ascending=False, na_position="last")

        # 存進 session_state：按「匯出CSV」也會觸發重新執行，
        # 若只靠 scan_btn 判斷，結果會在按下載當下被清空。
        st.session_state['watchlist_scan_result'] = result_df

    scan_result = st.session_state.get('watchlist_scan_result')
    if scan_result is not None:
        result_df = scan_result
        st.subheader("📋 掃描結果（依綜合分數排序）")
        st.dataframe(result_df, **STRETCH, hide_index=True)

        exp_s1, exp_s2 = st.columns(2)
        with exp_s1:
            csv_data = result_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ 匯出成 CSV", data=csv_data, file_name="watchlist_scan_result.csv", mime="text/csv", **STRETCH)
        with exp_s2:
            xlsx_s = to_excel_bytes(result_df)
            if xlsx_s:
                st.download_button("⬇️ 匯出成 Excel", data=xlsx_s, file_name="watchlist_scan_result.xlsx",
                                  mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **STRETCH)
            else:
                st.caption("本機未安裝 openpyxl，暫時只能匯出 CSV。")

        st.markdown("#### 這張表在說什麼、該怎麼用")
        st.markdown(
            "- **綜合分數／分數區間**：只是把技術指標按規則加總，分數高不等於「會漲」，單獨看沒有意義。\n"
            "- **區間歷史勝率**：這檔股票過去分數落在同一區間時，隔天真的上漲的比例，才是有被驗證過的數字。\n"
            "- **訊號解讀**：直接告訴你勝率離 50%（純猜測）有多遠。⚪ 代表沒有優勢，🟢/🟡 偏多，🔴/🟠 偏空。\n"
            "- **這不是「買進清單」**：即使顯示偏多，也只代表過去統計上機率略高，仍需搭配停損與部位控制，不是進場保證。"
        )
        if "區間歷史勝率(%)" in result_df.columns:
            valid_wr = result_df["區間歷史勝率(%)"].dropna()
            if len(valid_wr) > 0 and (valid_wr - 50).abs().mean() < 5:
                st.warning("⚠️ 這次掃描的標的，勝率大多落在 45%~55% 之間，代表目前這套評分規則在這批股票上幾乎沒有分辨多空的能力，請勿只依據分數操作。")
    else:
        st.info("在左側輸入股票代號清單後，按「開始掃描」進行批次分析。")

# ==========================================
# 模式一：📈 個股分析（選了就分析，不用按按鈕）
# ==========================================
elif app_mode == "📝 策略日誌":
    st.title("📝 策略日誌與覆盤")
    st.caption("在「📈 個股分析」或「⭐ 每日候選股」按「存入策略日誌」記錄下來的每一筆，都會出現在這裡。回來查看時會自動用目前股價，回頭檢查當時預測的方向、停損停利是否已經發生。")

    journal = load_journal()
    if journal.empty:
        st.info("目前還沒有任何日誌紀錄。去「📈 個股分析」看幾檔股票，或跑一次「⭐ 每日候選股」，點「📝 存入策略日誌」就會出現在這裡。")
    else:
        with st.spinner("回頭核對目前股價與歷史績效中…"):
            statuses, cur_prices, returns = [], [], []
            h5_list, h10_list, h20_list = [], [], []
            for _, r in journal.iterrows():
                code = str(r['代號'])
                try:
                    _tk, _info, df_j, _q = load_with_fallback(normalize_ticker(code))
                    cur_price = df_j['Close'].iloc[-1] if df_j is not None and not df_j.empty else None
                except Exception:
                    df_j = None
                    cur_price = None
                cur_prices.append(cur_price)
                horizon_actuals = compute_horizon_actuals(r.get('存入時間'), df_j)
                h5_list.append(horizon_actuals[5]); h10_list.append(horizon_actuals[10]); h20_list.append(horizon_actuals[20])
                if cur_price is None or pd.isna(r.get('參考買價')):
                    statuses.append("查無現價"); returns.append(None); continue
                entry = r['參考買價']
                if pd.notna(r.get('第二停利')) and cur_price >= r['第二停利']:
                    statuses.append("✅ 已達第二停利")
                elif pd.notna(r.get('第一停利')) and cur_price >= r['第一停利']:
                    statuses.append("✅ 已達第一停利")
                elif pd.notna(r.get('近端停損')) and cur_price <= r['近端停損']:
                    statuses.append("🛑 已觸及停損")
                else:
                    statuses.append("⏳ 進行中")
                returns.append((cur_price - entry) / entry * 100 if entry else None)

        journal = journal.copy()
        journal['目前股價'] = cur_prices
        journal['狀態'] = statuses
        journal['報酬(%)'] = [round(r, 2) if r is not None else None for r in returns]

        # ---- 功能3：距停損/停利還有多少空間，讓「進行中」的部位也能一眼看出安全邊際 ----
        def _dist(row, col):
            p, target = row.get('目前股價'), row.get(col)
            if pd.isna(p) or pd.isna(target) or p == 0:
                return None
            return round((target - p) / p * 100, 1)
        journal['距停損(%)'] = journal.apply(lambda r: _dist(r, '近端停損'), axis=1)
        journal['距第一停利(%)'] = journal.apply(lambda r: _dist(r, '第一停利'), axis=1)
        journal['5日後(%)'] = h5_list
        journal['10日後(%)'] = h10_list
        journal['20日後(%)'] = h20_list
        journal = journal.sort_values('存入時間', ascending=False).reset_index()

        # ---- 功能3：醒目警示——剛觸及停損／停利的紀錄，不要埋在表格裡，直接跳出來 ----
        alerts = journal[journal['狀態'].isin(["✅ 已達第一停利", "✅ 已達第二停利", "🛑 已觸及停損"])]
        if not alerts.empty:
            st.markdown("#### 🔔 需要你注意的紀錄")
            for _, r in alerts.iterrows():
                tag = f"{r['名稱']}（{r['代號']}）　存入時 ${r['存入時股價']:.2f}　目前 ${r['目前股價']:.2f}　報酬 {r['報酬(%)']:+.1f}%"
                if r['狀態'] == "🛑 已觸及停損":
                    st.error(f"🛑 **已觸及停損**：{tag}")
                else:
                    st.success(f"✅ **{r['狀態']}**：{tag}")
            st.caption("以上是本次重新整理時，狀態剛好落在「已達停利」或「已觸及停損」的紀錄；請自行到看盤軟體確認即時報價再決定是否真的出場。")
            st.divider()

        resolved = journal[journal['狀態'].isin(["✅ 已達第一停利", "✅ 已達第二停利", "🛑 已觸及停損"])]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("總筆數", len(journal))
        m2.metric("已有結果", len(resolved))
        win_n = (resolved['狀態'] != "🛑 已觸及停損").sum() if len(resolved) else 0
        m3.metric("命中停利比例", f"{win_n/len(resolved)*100:.0f}%" if len(resolved) else "尚無資料")
        m4.metric("平均報酬（全部，含進行中）", f"{journal['報酬(%)'].mean():+.1f}%" if journal['報酬(%)'].notna().any() else "無資料")

        show_cols = ["存入時間", "代號", "名稱", "方向", "分數區間", "存入時股價", "目前股價",
                    "參考買價", "近端停損", "距停損(%)", "第一停利", "距第一停利(%)", "第二停利",
                    "預計天數(歷史平均)", "狀態", "報酬(%)", "5日後(%)", "10日後(%)", "20日後(%)"]
        def _status_level(txt):
            t = str(txt)
            if "停損" in t: return "red"
            if "停利" in t: return "green"
            return "yellow"

        st.markdown("#### 📋 日誌一覽")
        for _, jr in journal.iterrows():
            with st.container(border=True):
                j1, j2, j3, j4 = st.columns([2.4, 1, 1, 2])
                j1.markdown(f"**{jr['名稱']}（{jr['代號']}）**　{jr['存入時間']}")
                j2.metric("存入時股價", f"{jr['存入時股價']:.2f}")
                ret = jr['報酬(%)']
                j3.metric("目前報酬", f"{ret:+.1f}%" if pd.notna(ret) else "—")
                j4.markdown("**狀態**")
                j4.markdown(pill(str(jr['狀態']), _status_level(jr['狀態'])), unsafe_allow_html=True)
                with st.expander("展開價位與後續表現"):
                    x1, x2, x3, x4 = st.columns(4)
                    x1.metric("參考買價", f"{jr['參考買價']:.2f}")
                    x2.metric("近端停損", f"{jr['近端停損']:.2f}", f"距 {jr['距停損(%)']:.1f}%" if pd.notna(jr['距停損(%)']) else None, delta_color="off")
                    x3.metric("第一停利", f"{jr['第一停利']:.2f}", f"距 {jr['距第一停利(%)']:.1f}%" if pd.notna(jr['距第一停利(%)']) else None, delta_color="off")
                    x4.metric("第二停利", f"{jr['第二停利']:.2f}")
                    y1, y2, y3 = st.columns(3)
                    for col_, lab in ((y1, "5日後(%)"), (y2, "10日後(%)"), (y3, "20日後(%)")):
                        v = jr[lab]
                        col_.metric(lab, f"{v:+.1f}%" if pd.notna(v) else "尚未到期")
                    st.caption(f"{jr['方向']}　·　{jr['分數區間']}　·　歷史平均約 {jr['預計天數(歷史平均)']} 天達標")

        with st.expander("📊 完整寬表格（所有欄位）"):
            st.dataframe(journal[show_cols], **STRETCH, hide_index=True)

        # ---- 視覺化回測績效快照：累積「存入時決策」在固定天數後的實際表現，形塑個人勝率資料庫 ----
        st.markdown("#### 📊 個人策略勝率資料庫（N 日後實際表現）")
        horizon_rows = []
        for h, col in ((5, "5日後(%)"), (10, "10日後(%)"), (20, "20日後(%)")):
            vals = journal[col].dropna()
            if len(vals):
                horizon_rows.append({"天數": f"{h} 日後", "樣本數": len(vals), "平均報酬(%)": round(vals.mean(), 2),
                                     "勝率(%)": round((vals > 0).mean() * 100, 1)})
        if horizon_rows:
            st.dataframe(pd.DataFrame(horizon_rows), **STRETCH, hide_index=True)
            st.caption("統計每一筆存入日誌的紀錄，從存入當天算起第 5／10／20 個交易日的實際漲跌幅（尚未經過那麼多天的紀錄不計入）。"
                      "樣本數越多，這張表越能反映你自己這套選股邏輯的真實表現，是調整模型參數最直接的依據。")
        else:
            st.info("目前還沒有任何紀錄存入滿 5 個交易日，等時間到了這裡會自動顯示統計結果。")

        del_options = [f"{i}：{row['存入時間']} {row['名稱']}（{row['代號']}）" for i, row in journal.iterrows()]
        to_delete = st.multiselect("選擇要刪除的紀錄", del_options)
        if to_delete and st.button("🗑️ 刪除選取的紀錄"):
            idxs = [journal.loc[journal.index[int(s.split("：")[0])], 'index'] for s in to_delete]
            delete_journal_entries(idxs)
            st.rerun()

        exp_c1, exp_c2 = st.columns(2)
        with exp_c1:
            csv_data = journal[show_cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ 匯出成 CSV", data=csv_data, file_name="strategy_journal.csv", mime="text/csv", **STRETCH)
        with exp_c2:
            xlsx_data = to_excel_bytes(journal[show_cols])
            if xlsx_data:
                st.download_button("⬇️ 匯出成 Excel", data=xlsx_data, file_name="strategy_journal.xlsx",
                                  mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", **STRETCH)
            else:
                st.caption("本機未安裝 openpyxl，暫時只能匯出 CSV。")

        with st.expander("📥 匯入日誌備份（還原之前匯出的 CSV）"):
            up_j = st.file_uploader("選擇備份檔案", type=["csv"], key="journal_import")
            if up_j is not None:
                try:
                    import_df = pd.read_csv(up_j)
                    required_cols = {"代號", "名稱", "參考買價"}
                    if not required_cols.issubset(set(import_df.columns)):
                        st.error("這個檔案缺少必要欄位（代號／名稱／參考買價），看起來不是本系統匯出的日誌備份。")
                    else:
                        raw_cols = [c for c in JOURNAL_COLUMNS if c in import_df.columns]
                        n = import_journal_rows(import_df[raw_cols])
                        if n:
                            st.success(f"已匯入 {n} 筆紀錄，接到現有日誌後面。")
                            st.rerun()
                        else:
                            st.error("匯入失敗，請確認本機可以寫入檔案。")
                except Exception as e:
                    st.error(f"讀取檔案失敗：{e}")

        st.caption(
            "「距停損(%)」「距第一停利(%)」是目前股價距離該價位還有多少百分比，正值代表還沒到、負值代表已經跌破或漲過頭；"
            "「命中停利比例」只計算已經有明確結果（達停利或觸及停損）的筆數，「進行中」的不計入，樣本數少時參考價值有限。這是檢驗模型參數是否需要調整的第一手資料。"
        )

elif app_mode == "📡 總經雷達":
    st.title("📡 台股宏觀總經與籌碼雷達")
    st.caption("看的是「大盤大方向」，不是個股訊號；請與「📈 個股分析」的結果一起看，不要單獨依賴這頁做決策。")

    st.markdown("#### 🔮 大盤隔日方向預測（以 0050 為代理）")
    md = get_market_direction("0050.TW")
    if md:
        {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}[md['color']](
            f"**{md['direction']}**　·　0050 現價 ${md['price']:.2f}　·　分數 {md['score']}　·　{md['action']}")
        if md['wr'] is not None:
            st.caption(f"📊 歷史驗證：0050 過去分數落在同一區間（{md['bucket']}）時，隔日上漲機率 {md['wr']:.1f}%（N={md['n']}）。")
        st.caption("這是把個股分析用的同一套技術評分引擎，套用在 0050 這檔追蹤大盤的 ETF 上，邏輯完全一致，只是分析對象換成大盤。")
    else:
        st.info("大盤方向資料暫時抓不到。")
    st.divider()

    fx = get_macro_series("TWD=X")
    vix = get_macro_series("^VIX")
    sox = get_macro_series("^SOX")
    tx = get_taifex_foreign_tx()

    call = _macro_call(fx, vix, tx)
    if call:
        (st.error if call.startswith("🔴") else st.success if call.startswith("🟢") else st.warning)(call)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if fx:
            st.metric("美元／台幣 (USD/TWD)", f"{fx['value']:.3f}", f"{fx['chg_pct']:+.2f}%", delta_color="inverse" if fx['chg_pct'] > 0 else "normal")
            st.caption("台幣走貶（數字上升）常與外資匯出、避險情緒升高有關；台幣走升則反映資金回流台股。")
        else:
            st.metric("美元／台幣 (USD/TWD)", "無資料")
            st.caption("資料來源暫時連不上。")
    with c2:
        if vix:
            level = "😱 恐慌" if vix['value'] >= 30 else ("⚠️ 偏高" if vix['value'] >= 20 else "😌 平穩")
            st.metric("VIX 恐慌指數", f"{vix['value']:.1f}", f"{vix['chg_pct']:+.1f}%", delta_color="inverse" if vix['chg_pct'] > 0 else "normal")
            st.caption(f"目前屬於「{level}」。經驗上 20 以上偏警戒，30 以上視為顯著恐慌，市場波動風險升高。")
        else:
            st.metric("VIX 恐慌指數", "無資料")
            st.caption("資料來源暫時連不上。")
    with c3:
        if sox:
            st.metric("費城半導體指數 (SOX)", f"{sox['value']:,.0f}", f"{sox['chg_pct']:+.2f}%", delta_color="normal" if sox['chg_pct'] >= 0 else "inverse")
            st.caption("台股半導體權重高，費半大跌隔天台股半導體股容易連動走弱，是重要的隔夜領先指標。")
        else:
            st.metric("費城半導體指數 (SOX)", "無資料")
            st.caption("資料來源暫時連不上。")
    with c4:
        if tx and tx.get('net') is not None:
            bias = "偏多" if tx['net'] > 0 else "偏空" if tx['net'] < 0 else "中性"
            st.metric("台指期外資淨未平倉", f"{tx['net']:,} 口", bias, delta_color="normal" if tx['net'] > 0 else "inverse")
            st.caption("正值＝外資淨多單，對台股偏樂觀；負值＝淨空單，是常見的短線籌碼風向球之一。")
        else:
            st.metric("台指期外資淨未平倉", "暫時抓不到")
            st.caption("⚠️ 期交所網頁格式較易變動，這項資料最容易失敗。可直接查詢台灣期貨交易所官網「三大法人-區分各期貨契約」確認正確數字。")

    risk_flags = get_macro_risk_flags()
    if risk_flags:
        st.error("🚨 總經風險警示：" + "、".join(risk_flags) + "。「💼 投資組合管理」的倉位水位區塊會同步提醒。")

    if fx and vix:
        st.markdown("#### 近一個月走勢")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=fx['series'].index, y=fx['series'].values, name="USD/TWD", line=dict(color="#1f77b4")), secondary_y=False)
        fig.add_trace(go.Scatter(x=vix['series'].index, y=vix['series'].values, name="VIX", line=dict(color="#e5484d")), secondary_y=True)
        fig.update_layout(height=320, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.2))
        fig.update_yaxes(title_text="USD/TWD", secondary_y=False)
        fig.update_yaxes(title_text="VIX", secondary_y=True)
        st.plotly_chart(fig, **STRETCH, key="macro_trend_chart")

    st.caption("⚠️ 這些是總體市場的參考指標，反映的是大盤氣氛而非特定股票的基本面；台指期外資部位資料源自台灣期貨交易所，若與官網數字有出入請以官網為準。")

    st.divider()
    st.markdown("#### 📰 財經新聞雷達（Beta）")
    st.caption("⚠️ 分類、影響方向與關聯個股是**關鍵字比對**，不是真正的語意理解 AI，僅供快速瀏覽用，請務必點進原文確認。新聞來源若改版失效會直接顯示抓不到，不會捏造內容。")
    news_directory, _ = get_directory()
    news_items = get_news_items()
    if news_items:
        for it in news_items[:12]:
            tag = classify_news(it['title'], news_directory)
            icon = "🟢" if tag['impact'] == "正面" else ("🔴" if tag['impact'] == "負面" else "⚪")
            with st.container(border=True):
                st.markdown(f"{icon} **[{it['title']}]({it['link']})**")
                extra = f" ｜ 關聯：{', '.join(tag['tickers'])}" if tag['tickers'] else ""
                st.caption(f"{' '.join(tag['categories'])} ｜ 影響：{tag['impact']} {tag['stars']}{extra}")
    else:
        st.info("新聞來源暫時抓不到（RSS 網址可能已改版或失效）。這是全站最不確定的功能，如果你手邊有目前有效的財經新聞 RSS 網址，告訴我可以直接換上。")

elif app_mode == "📈 個股分析":
    directory, live_ok = get_directory()
    with st.container(border=True):
        ss1, ss2, ss3 = st.columns([2, 2.4, 1])
        query = ss1.text_input("🔍 搜尋股票", placeholder="打代號開頭（如 2）或公司名（如 台積）", key="stock_search_query",
                               help="打數字會列出「代號開頭相同」的股票並顯示公司名；打中文則找名稱包含的公司。輸入後按 Enter。")
        options, total_hits = search_stocks(query, directory)
        _hint = ""
        if query.strip() and not options:
            options = [query.strip().upper()]
            _hint = "名單中找不到，將直接使用你輸入的代號。"
        elif query.strip():
            _hint = f"找到 {total_hits} 檔" + (f"，只列出前 {len(options)} 檔，請多打幾個字縮小範圍" if total_hits > len(options) else "")
        code = ss2.selectbox("選擇股票", options, key="stock_select_code",
                             format_func=lambda c: f"{directory[c]['name']}（{c}）" if c in directory else c)
        ss3.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
        if ss3.button("🔄 更新資料", **STRETCH):
            st.cache_data.clear()
            st.session_state["_dir_failed_at"] = 0
        st.caption((_hint + "　" if _hint else "") + (f"✅ 已載入完整上市櫃名單（{len(directory)} 檔）" if live_ok
                   else "ℹ️ 目前使用內建常用名單（連不上證交所名單）。仍可直接輸入任何代號。"))

    entry = directory.get(code)
    raw_ticker = (code + entry["suffix"]) if entry else normalize_ticker(code)
    with st.spinner(f"載入 {raw_ticker} 資料中…"):
        ticker, info, df, q_income = load_with_fallback(raw_ticker)

    if df is None or df.empty or len(df) < 40:
        st.error("找不到足夠的歷史資料（至少需要 40 個交易日）。請確認代號是否正確；上櫃股票會自動嘗試 .TWO。")
        st.stop()

    touch_watchlist(ticker)  # 成功看過的股票自動加進觀察清單，之後不用重打
    pure = ticker.split(".")[0]
    en_name = info.get('longName') or info.get('shortName')
    zh_name = INDUSTRY_MAP[ticker]['name'] if ticker in INDUSTRY_MAP else (entry['name'] if entry else None)
    industry_name = entry['ind'] if entry else None
    stock_name = zh_name or en_name or ticker          # 沒有中文名就用英文名
    if ticker in INDUSTRY_MAP:
        target_pe = INDUSTRY_MAP[ticker]['target_pe']
    else:
        pe_raw = info.get('trailingPE')
        target_pe = int(pe_raw) if isinstance(pe_raw, (int, float)) and pe_raw > 0 else 15

    df = compute_indicators(df)
    latest, prev = df.iloc[-1], df.iloc[-2]
    current_price = latest['Close']
    price_diff = current_price - prev['Close']
    pct_diff = price_diff / prev['Close'] * 100 if prev['Close'] > 0 else 0.0
    vol_today, vol_prev = latest['Volume'] / 1000, prev['Volume'] / 1000
    vol_pct = (vol_today - vol_prev) / vol_prev * 100 if vol_prev > 0 else 0
    vol_status = "大爆量" if vol_pct > 50 else "量增" if vol_pct > 10 else "量縮" if vol_pct < -10 else "量平穩"

    k_name = analyze_today_kline(latest['Open'], latest['High'], latest['Low'], latest['Close'])
    pattern_msgs, pattern_annotations = detect_advanced_patterns(df.tail(150))
    backtest_stats = backtest_score_system(df)
    direction, action, buy_price, _reminder, color_theme, score, bucket = predict_next_day(latest, prev, k_name, pattern_msgs, backtest_stats)
    lv = compute_levels(df, latest, current_price, score)
    foreign_buy, trust_buy, chip_status = get_taiwan_chips(pure)

    # ---------- 頁首：名稱＋報價 ----------
    st.title(f"{stock_name}　{pure}")
    prof = COMPANY_PROFILES.get(ticker)
    sub = " · ".join(x for x in [prof['category'] if prof else industry_name, en_name if zh_name else None] if x)
    if sub:
        st.caption(sub)

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("收盤價", f"${current_price:.2f}", f"{price_diff:+.2f} ({pct_diff:+.2f}%)")
    q2.metric("成交量", f"{vol_today:,.0f} 張", f"{vol_pct:+.1f}% {vol_status}", delta_color="normal" if vol_pct > 0 else "inverse")
    if chip_status == "success":
        q3.metric("外資買賣超", f"{foreign_buy:,}", "買超" if foreign_buy > 0 else "賣超", delta_color="normal" if foreign_buy > 0 else "inverse")
        q4.metric("投信買賣超", f"{trust_buy:,}", "買超" if trust_buy > 0 else "賣超", delta_color="normal" if trust_buy > 0 else "inverse")
    else:
        q3.metric("外資買賣超", "—")
        q4.metric("投信買賣超", "—")
        st.caption("法人籌碼暫時抓不到（來源網頁可能改版或連線逾時），不影響其他分析。")

    tab_overview, tab_hold, tab_chart, tab_company, tab_fin, tab_bt = st.tabs(
        ["🏠 總覽", "💼 我的持股", "📊 技術圖表", "🏢 公司與產業", "📑 財務體質", "🧪 回測驗證"])

    # ---------- 🏠 總覽：先給結論 ----------
    with tab_overview:
        {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}[color_theme](
            f"### {direction}　·　分數 {score}\n{action}")

        # ------------------------------------
        # ★ 功能1：明日多空機率與相似情境分析 ★
        # ------------------------------------
        st.markdown("#### 🔮 明日多空機率與相似情境分析")
        comps = score_components(latest, prev, k_name, pattern_msgs)
        bias_pct = (current_price - latest['MA20']) / latest['MA20'] * 100 if latest['MA20'] > 0 else np.nan
        sc = build_scenario_view(score, bucket, backtest_stats, comps, pattern_msgs, bias_pct)

        if sc['wr'] is not None:
            p1, p2, p3 = st.columns(3)
            p1.metric("隔日上漲機率", f"{sc['wr']:.1f}%")
            p2.metric("隔日下跌機率", f"{100 - sc['wr']:.1f}%")
            p3.metric("歷史相似樣本數", f"N = {sc['n']}")
            st.caption(f"📊 信心水準：{confidence_label(sc['n'])}。「相似情境」指過去這檔股票分數落在同一區間（{bucket}）的所有交易日。")
        else:
            st.info("這個分數區間目前沒有足夠的歷史相似情境可供統計。")

        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("**✅ 支持偏多的條件**")
            if sc['bullish']:
                for t, p in sc['bullish']:
                    st.markdown(f"- {t}（+{p} 分）")
            else:
                st.caption("目前沒有偏多的技術條件成立。")
        with rc2:
            st.markdown("**⚠️ 潛在風險與偏空條件**")
            if sc['bearish'] or sc['extra_risks']:
                for t, p in sc['bearish']:
                    st.markdown(f"- {t}（{p} 分）")
                for t in sc['extra_risks']:
                    st.markdown(f"- {t}")
            else:
                st.caption("目前沒有明顯的偏空條件成立。")
        for t in sc['caution']:
            st.caption(f"🕵️ {t}")

        st.warning("⚠️ 以上機率來自歷史相似情境統計與目前技術指標條件的組合，反映的是「過去」相同狀況下的統計結果，"
                  "**不代表、也不保證明日實際漲跌**，不構成投資建議。權重為經驗設定，非統計最佳化，可信度請以左方「隔日上漲機率」旁的樣本數與「🧪 回測驗證」分頁為準。")

        if st.button("📝 存入策略日誌", key=f"journal_overview_{ticker}"):
            horizon = historical_horizon_stats(df, bucket)
            ok = append_journal_entry({
                "存入時間": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                "代號": pure, "名稱": stock_name, "分數": score, "分數區間": bucket,
                "方向": direction, "存入時股價": current_price, "參考買價": buy_price,
                "近端停損": lv['near_stop'], "第一停利": lv['target1'], "第二停利": lv['target2'],
                "預計天數(歷史平均)": round(horizon['avg_days'], 1) if horizon else None,
            })
            st.toast("已存入策略日誌！" if ok else "存檔失敗，可能是檔案系統無法寫入。")

        st.divider()

        def pct_from(p): return f"{(p / current_price - 1) * 100:+.1f}%"
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("參考買價", f"${buy_price:.2f}", pct_from(buy_price), delta_color="off", help="依訊號強弱推算的掛單參考價")
        m2.metric("近端停損", f"${lv['near_stop']:.2f}", pct_from(lv['near_stop']), delta_color="off",
                 help=f"取「月線停損」${lv['ma20_stop']:.2f} 與「ATR波動度停損（現價-2×ATR）」" +
                      (f"${lv['atr_stop']:.2f}" if lv['atr_stop'] else "（ATR無法計算）") + " 兩者中較貼近現價者，風險較保守")
        m3.metric("第一停利", f"${lv['target1']:.2f}", pct_from(lv['target1']), delta_color="off", help="前波高點附近")
        m4.metric("風險報酬比", f"1 : {lv['rr']:.1f}" if lv['rr'] is not None else "—", help="現價到第一停利 ÷ 現價到近端停損")
        st.caption("已經持有這檔？到「💼 我的持股」輸入股數與均價，會給你專屬的加碼、停損、停利價位。")

        with st.expander("🧮 部位試算機（如果現在要進場，該買幾張？）"):
            pc1, pc2 = st.columns(2)
            capital = pc1.number_input("總資金 (TWD)", min_value=10000, value=500000, step=10000, key="ps_capital")
            risk_pct = pc2.slider("願意承受的最大虧損 (% 總資金)", 0.5, 10.0, 2.0, 0.5, key="ps_risk_pct")
            risk_per_share = buy_price - lv['near_stop']
            if risk_per_share > 0:
                risk_amount = capital * (risk_pct / 100.0)
                raw_shares = min(risk_amount / risk_per_share, capital / buy_price)
                lots = int(raw_shares // 1000)
                shares_final = lots * 1000
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("每股風險（買價−近端停損）", f"${risk_per_share:.2f}")
                r2.metric("可承受最大虧損", f"${risk_amount:,.0f}")
                r3.metric("建議整股部位", f"{lots} 張（{shares_final:,} 股）")
                r4.metric("預估投入金額", f"${shares_final * buy_price:,.0f}")
                if lots == 0 and raw_shares > 0:
                    st.info(f"連 1 張都超出設定的風險或資金上限，可考慮零股買進約 {int(raw_shares)} 股（約 ${int(raw_shares)*buy_price:,.0f}），或提高風險%／資金。")
                st.caption("計算依據：參考買價與近端停損的價差；未計手續費與交易稅，僅供風控參考，非投資建議。")
            else:
                st.warning("目前參考買價不高於近端停損，無法計算合理部位，請重新檢視進場時機。")

    # ---------- 💼 我的持股 ----------
    with tab_hold:
        holding_panel(ticker, current_price, score, lv)

    # ---------- 📊 技術圖表 ----------
    with tab_chart:
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("MACD 柱狀體", f"{latest['Hist']:.2f}", "多頭" if latest['Hist'] > 0 else "空頭", delta_color="normal" if latest['Hist'] > 0 else "inverse")
        wpr = latest['WPR']
        t2.metric("威廉指標", f"{wpr:.0f}", "超買" if wpr > -20 else "超賣" if wpr < -80 else "中性", delta_color="inverse" if wpr > -20 else "off")
        cci = latest['CCI']
        t3.metric("CCI", f"{cci:.0f}", "超買" if cci > 100 else "超賣" if cci < -100 else "中性", delta_color="inverse" if cci > 100 else "off")
        t4.metric("今日 K 棒", k_name.split(" ")[0])
        chart_panel(df, pattern_annotations)

    # ---------- 🏢 公司與產業 ----------
    with tab_company:
        render_company_tab(ticker, pure, info, zh_name, en_name, df, industry_name, directory)

    # ---------- 📑 財務體質 ----------
    with tab_fin:
        render_fundamentals(info, q_income, current_price, target_pe, ticker)

    # ---------- 🧪 回測驗證 ----------
    with tab_bt:
        backtest_panel(df, backtest_stats)

    st.divider()
    st.caption("⚠️ 本工具為技術指標的規則式試算，並非統計顯著驗證過的預測模型，也不構成投資建議；過去表現不代表未來績效。")
