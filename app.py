import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import re
import os
import time
import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==========================================
# 載入外部套件與大戶籌碼資料層
# ==========================================
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_SCRAPER = True
except ImportError:
    HAS_SCRAPER = False

try:
    import wanglai_data as wl
    HAS_WANGLAI = True
except ImportError:
    HAS_WANGLAI = False

def _st_version():
    try: return tuple(int(x) for x in st.__version__.split(".")[:2])
    except: return (0, 0)
STRETCH = {"width": "stretch"} if _st_version() >= (1, 50) else {"use_container_width": True}

# ==========================================
# 頁面與樣式設定
# ==========================================
st.set_page_config(page_title="J喜金融｜量化投資戰情室", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@500;700&display=swap');
.stApp {background: #f4f6f9;}
header[data-testid="stHeader"] {background: transparent;}
.block-container {padding-top: 1rem; max-width: 1280px;}
h1, h2, h3 {color: #1f2a3d; font-weight: 800;}
h4 {color: #1f2a3d; border-left: 4px solid #b08d57; padding-left: 10px; margin-top: 0.4rem;}
div[data-testid="stMetric"] {background: #ffffff; padding: 12px 16px; border-radius: 12px; border: 1px solid #e1e8ed; border-left: 4px solid #b08d57; box-shadow: 0 1px 4px rgba(31,42,61,0.04);}
div[data-testid="stExpander"] {background: #ffffff; border-radius: 12px; border: 1px solid #e1e8ed;}
.jx-brand {display: inline-flex; align-items: baseline; padding: 6px 14px; background: #ffffff; border: 1px solid #d1d9e0; border-radius: 8px; box-shadow: 0 2px 6px rgba(31,42,61,0.06); font-family: 'Noto Serif TC', serif;}
.jx-brand-j {font-size: 1.8rem; font-style: italic; font-weight: 700; color: #b08d57; margin-right: 4px;}
.jx-brand-name {font-size: 1.4rem; font-weight: 700; color: #2f3e55; letter-spacing: 0.12em;}
.jx-brand-sub {font-size: 0.65rem; letter-spacing: 0.25em; color: #788896; margin-left: 8px;}
.st-key-jx_topnav div[data-baseweb="select"] > div {background: #f4f6f9 !important; border: 1px solid #d1d9e0 !important; border-radius: 6px !important; min-height: 38px; font-weight: 600;}
.qr-pill {display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.82em; font-weight: 700; margin: 1px 2px;}
.qr-pill-green  {background: #dceee2; color: #2f6b4f;}
.qr-pill-yellow {background: #f6e6b8; color: #7a5d12;}
.qr-pill-red    {background: #f4dede; color: #9c4848;}
.qr-pill-gray   {background: #e4eaf0; color: #55657b;}
</style>
""", unsafe_allow_html=True)
def pill(text, level="gray"): return f'<span class="qr-pill qr-pill-{level}">{text}</span>'
def _fragment(func): frag = getattr(st, "fragment", None); return frag(func) if frag else func

# ==========================================
# 本機資料儲存與讀取
# ==========================================
DATA_DIR = os.path.join(os.path.expanduser("~"), ".quant_radar_data")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.csv")
AUTOTRADE_STATE_FILE = os.path.join(DATA_DIR, "autotrade_state.json")
AUTOTRADE_LOG_FILE = os.path.join(DATA_DIR, "autotrade_log.csv")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal.csv")
JOURNAL_COLUMNS = ["存入時間", "代號", "名稱", "分數", "分數區間", "方向", "存入時股價", "參考買價", "近端停損", "第一停利", "第二停利", "預計天數(歷史平均)"]

def _ensure_data_dir():
    try: os.makedirs(DATA_DIR, exist_ok=True); return True
    except: return False

def get_watchlist():
    if "_watchlist" not in st.session_state:
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f: st.session_state["_watchlist"] = json.load(f)
        except: st.session_state["_watchlist"] = []
    return st.session_state["_watchlist"]

def touch_watchlist(ticker, max_items=30):
    wl = [t for t in get_watchlist() if t != ticker]
    wl.insert(0, ticker)
    st.session_state["_watchlist"] = wl[:max_items]
    if _ensure_data_dir():
        try:
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f: json.dump(st.session_state["_watchlist"], f)
        except: pass

def load_portfolio():
    if _ensure_data_dir() and os.path.exists(PORTFOLIO_FILE):
        try:
            df = pd.read_csv(PORTFOLIO_FILE, dtype={"代號": str})
            df["代號"] = df["代號"].astype(str).str.strip()
            if "方向" not in df.columns: df["方向"] = "Long"
            if "標籤" not in df.columns: df["標籤"] = ""
            return df[["代號", "股數", "均價", "方向", "備註", "標籤"]]
        except: pass
    return pd.DataFrame(columns=["代號", "股數", "均價", "方向", "備註", "標籤"])

def save_portfolio(df):
    if _ensure_data_dir(): df.to_csv(PORTFOLIO_FILE, index=False)

def load_journal():
    if _ensure_data_dir() and os.path.exists(JOURNAL_FILE):
        try: return pd.read_csv(JOURNAL_FILE, parse_dates=["存入時間"])
        except: pass
    return pd.DataFrame(columns=JOURNAL_COLUMNS)

def append_journal_entry(row: dict):
    df = load_journal()
    new_row = pd.DataFrame([row])
    df = pd.concat([df, new_row], ignore_index=True)
    if _ensure_data_dir():
        try: df.to_csv(JOURNAL_FILE, index=False); return True
        except: pass
    return False

def load_autotrade_state():
    default = {"cash": 0.0, "positions": {}, "initialized": False}
    if _ensure_data_dir() and os.path.exists(AUTOTRADE_STATE_FILE):
        try:
            with open(AUTOTRADE_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "cash" in data: return {**default, **data}
        except: pass
    return default

def load_autotrade_log():
    if _ensure_data_dir() and os.path.exists(AUTOTRADE_LOG_FILE):
        try: return pd.read_csv(AUTOTRADE_LOG_FILE, dtype={"代號": str})
        except: pass
    return pd.DataFrame(columns=["時間", "代號", "名稱", "動作", "股數", "價格", "金額", "原因"])

# ==========================================
# 頂部導覽列模組
# ==========================================
HOME_MODE = "🏠 戰情室首頁"
NAV_GROUPS = [
    ("premarket", "🌅 晨間準備", ["🌅 盤前必讀"]),
    ("search",   "🔍 選股雷達", ["⭐ 每日候選股", "🗂 觀察清單掃描", "🐋 大戶籌碼"]),
    ("research", "📈 研究室",   ["📈 個股分析", "📡 總經雷達", "📊 ETF 專區"]),
    ("desk",     "💼 操盤室",   ["💼 投資組合管理", "🤖 模擬自動交易"]),
    ("academy",  "🎓 覆盤學院", ["📝 策略日誌", "📚 教學庫"]),
]
ALL_MODES = [HOME_MODE] + [m for _, _, ms in NAV_GROUPS for m in ms]

if "_pending_app_mode" in st.session_state:
    st.session_state["app_mode_radio"] = st.session_state.pop("_pending_app_mode")
    pending_code = st.session_state.pop("_pending_stock_code", None)
    if pending_code: st.session_state["stock_select_code"] = pending_code

if st.session_state.get("app_mode_radio") not in ALL_MODES:
    st.session_state["app_mode_radio"] = HOME_MODE
app_mode = st.session_state["app_mode_radio"]

def _topnav_pick(gid):
    chosen = st.session_state.get(f"topnav_{gid}")
    if chosen in ALL_MODES: st.session_state["app_mode_radio"] = chosen

hd1, hd2 = st.columns([3, 1])
hd1.markdown('<div class="jx-brand"><span class="jx-brand-j">J</span><span class="jx-brand-name">喜金融</span><span class="jx-brand-sub">量化投資戰情室</span></div>', unsafe_allow_html=True)
hd2.markdown(f'<div style="text-align: right; color: #55657b; font-weight: 600; padding-top: 10px;">📅 {pd.Timestamp.now().strftime("%Y/%m/%d")}</div>', unsafe_allow_html=True)

with st.container(key="jx_topnav"):
    _nc = st.columns([1, 1.2, 1.4, 1.4, 1.4, 1.4])
    _nc[0].button("🏠 首頁", on_click=lambda: st.session_state.update({"app_mode_radio": HOME_MODE}), type="primary" if app_mode == HOME_MODE else "secondary", **STRETCH)
    for _i, (_gid, _gtitle, _gmodes) in enumerate(NAV_GROUPS, start=1):
        with _nc[_i]:
            st.selectbox(_gtitle, _gmodes, index=_gmodes.index(app_mode) if app_mode in _gmodes else None, placeholder=f"{_gtitle} ▾", key=f"topnav_{_gid}", on_change=_topnav_pick, args=(_gid,), label_visibility="collapsed")

# ==========================================
# 市場與公司名單庫
# ==========================================
BUILTIN_STOCK_TEXT = """
1101 台泥 水泥
1301 台塑 塑膠
2317 鴻海 電腦週邊
2330 台積電 半導體
2303 聯電 半導體
2454 聯發科 半導體
2603 長榮 航運
2881 富邦金 金融保險
3711 日月光
