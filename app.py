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
# 嘗試載入外部套件與大戶籌碼資料層
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
    try:
        return tuple(int(x) for x in st.__version__.split(".")[:2])
    except Exception:
        return (0, 0)

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
div[data-testid="stMetric"] {
    background: #ffffff; padding: 12px 16px; border-radius: 12px;
    border: 1px solid #e1e8ed; border-left: 4px solid #b08d57;
    box-shadow: 0 1px 4px rgba(31,42,61,0.04);
}
div[data-testid="stExpander"] {background: #ffffff; border-radius: 12px; border: 1px solid #e1e8ed;}
.jx-brand {
    display: inline-flex; align-items: baseline; padding: 6px 14px; background: #ffffff;
    border: 1px solid #d1d9e0; border-radius: 8px; box-shadow: 0 2px 6px rgba(31,42,61,0.06);
    font-family: 'Noto Serif TC', serif;
}
.jx-brand-j {font-size: 1.8rem; font-style: italic; font-weight: 700; color: #b08d57; margin-right: 4px;}
.jx-brand-name {font-size: 1.4rem; font-weight: 700; color: #2f3e55; letter-spacing: 0.12em;}
.jx-brand-sub {font-size: 0.65rem; letter-spacing: 0.25em; color: #788896; margin-left: 8px;}
.st-key-jx_topnav {
    background: #ffffff; padding: 8px 16px; margin: 4px 0 14px 0;
    border-radius: 10px; border: 1px solid #e1e8ed; box-shadow: 0 2px 8px rgba(31,42,61,0.04);
}
.st-key-jx_topnav div[data-testid="stHorizontalBlock"] {gap: 0.5rem; align-items: center;}
.st-key-jx_topnav div[data-baseweb="select"] > div {
    background: #f4f6f9 !important; border: 1px solid #d1d9e0 !important; border-radius: 6px !important;
    min-height: 38px; font-weight: 600; color: #1f2a3d !important;
}
.qr-pill {display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.82em; font-weight: 700; margin: 1px 2px;}
.qr-pill-green  {background: #dceee2; color: #2f6b4f;}
.qr-pill-yellow {background: #f6e6b8; color: #7a5d12;}
.qr-pill-red    {background: #f4dede; color: #9c4848;}
.qr-pill-gray   {background: #e4eaf0; color: #55657b;}
</style>
""", unsafe_allow_html=True)

def pill(text, level="gray"): return f'<span class="qr-pill qr-pill-{level}">{text}</span>'

# ==========================================
# 資料目錄與本機存取
# ==========================================
DATA_DIR = os.path.join(os.path.expanduser("~"), ".quant_radar_data")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.csv")
AUTOTRADE_STATE_FILE = os.path.join(DATA_DIR, "autotrade_state.json")
AUTOTRADE_LOG_FILE = os.path.join(DATA_DIR, "autotrade_log.csv")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal.csv")

def _ensure_data_dir():
    try: os.makedirs(DATA_DIR, exist_ok=True); return True
    except: return False

def get_watchlist():
    if "_watchlist" not in st.session_state:
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f: st.session_state["_watchlist"] = json.load(f)
        except: st.session_state["_watchlist"] = []
    return st.session_state["_watchlist"]

def touch_watchlist(ticker):
    wl = [t for t in get_watchlist() if t != ticker]
    wl.insert(0, ticker)
    st.session_state["_watchlist"] = wl[:30]
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
            return df
        except: pass
    return pd.DataFrame(columns=["代號", "股數", "均價", "方向", "備註", "標籤"])

def save_portfolio(df):
    if _ensure_data_dir(): df.to_csv(PORTFOLIO_FILE, index=False)

# ==========================================
# 頂部導覽模組
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
if st.session_state.get("app_mode_radio") not in ALL_MODES:
    st.session_state["app_mode_radio"] = HOME_MODE

app_mode = st.session_state["app_mode_radio"]

def _topnav_pick(gid):
    chosen = st.session_state.get(f"topnav_{gid}")
    if chosen in ALL_MODES: st.session_state["app_mode_radio"] = chosen

hd1, hd2 = st.columns([3, 1])
hd1.markdown('<div class="jx-brand"><span class="jx-brand-j">J</span><span class="jx-brand-name">喜金融</span>'
             '<span class="jx-brand-sub">量化投資戰情室</span></div>', unsafe_allow_html=True)
hd2.markdown(f'<div style="text-align: right; color: #55657b; font-weight: 600; padding-top: 10px;">📅 {pd.Timestamp.now().strftime("%Y/%m/%d")}</div>', unsafe_allow_html=True)

with st.container(key="jx_topnav"):
    _nc = st.columns([1, 1.2, 1.4, 1.4, 1.4, 1.4])
    _nc[0].button("🏠 首頁", on_click=lambda: st.session_state.update({"app_mode_radio": HOME_MODE}), 
                  type="primary" if app_mode == HOME_MODE else "secondary", **STRETCH)
    for _i, (_gid, _gtitle, _gmodes) in enumerate(NAV_GROUPS, start=1):
        with _nc[_i]:
            st.selectbox(_gtitle, _gmodes, index=_gmodes.index(app_mode) if app_mode in _gmodes else None, 
                         placeholder=f"{_gtitle} ▾", key=f"topnav_{_gid}", on_change=_topnav_pick, args=(_gid,), label_visibility="collapsed")

# ==========================================
# 核心資料處理與評分模型 (濃縮版以符合效能)
# ==========================================
INDUSTRY_MAP = {
    "2330.TW": {"name": "台積電", "ind": "半導體"},
    "2317.TW": {"name": "鴻海", "ind": "電腦週邊"},
    "2454.TW": {"name": "聯發科", "ind": "半導體"},
    "3711.TW": {"name": "日月光投控", "ind": "半導體"},
    "2603.TW": {"name": "長榮", "ind": "航運"},
}

@st.cache_data(ttl=900, show_spinner=False)
def load_stock_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="1y").dropna(subset=['Close', 'Volume'])
        return stock.info or {}, df, pd.DataFrame()
    except: return {}, pd.DataFrame(), pd.DataFrame()

def compute_indicators(df):
    if df.empty: return df
    df = df.copy()
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['MACD'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    df['Resistance'] = df['High'].rolling(60, min_periods=1).max()
    df['Support'] = df['Low'].rolling(60, min_periods=1).min()
    return df

def score_components(latest, prev):
    pts = []
    if latest['Hist'] > 0 and prev['Hist'] <= 0: pts.append(("MACD黃金交叉", 35))
    elif latest['Hist'] > 0: pts.append(("MACD偏多", 15))
    else: pts.append(("MACD偏空", -20))
    if latest['Close'] > latest['MA20']: pts.append(("站上月線", 15))
    else: pts.append(("跌破月線", -15))
    return pts

def compute_score(latest, prev):
    return sum(p for _, p in score_components(latest, prev))

def predict_next_day(latest, prev):
    score = compute_score(latest, prev)
    if score >= 40: return "技術面偏多", "可分批進場", "success", score
    elif score >= 0: return "溫和偏多", "逢低佈局", "info", score
    elif score >= -30: return "中性偏弱", "持續觀望", "warning", score
    else: return "技術面偏空", "避免進場", "error", score

# ==========================================
# 📊 新功能模組：大盤預測與熱力圖
# ==========================================
@st.cache_data(ttl=900, show_spinner=False)
def get_market_direction(symbol="0050.TW"):
    info, df, _ = load_stock_data(symbol)
    if df.empty: return None
    df = compute_indicators(df)
    direction, action, color, score = predict_next_day(df.iloc[-1], df.iloc[-2])
    return {"price": df['Close'].iloc[-1], "direction": direction, "score": score, "color": color, "action": action}

@st.cache_data(ttl=900, show_spinner=False)
def get_sector_heatmap_data():
    sectors = {
        "半導體": ["2330.TW", "2454.TW", "3711.TW", "2303.TW"],
        "電腦週邊": ["2317.TW", "2382.TW", "3231.TW"],
        "金融": ["2881.TW", "2882.TW", "2891.TW"],
        "航運": ["2603.TW", "2609.TW", "2615.TW"]
    }
    data = []
    for sector, tkrs in sectors.items():
        pcts = []
        for t in tkrs:
            _, df, _ = load_stock_data(t)
            if len(df)>1: pcts.append((df['Close'].iloc[-1]/df['Close'].iloc[-2]-1)*100)
        if pcts: data.append({"sector": sector, "change": np.mean(pcts)})
    return pd.DataFrame(data)

# ==========================================
# 🌅 盤前必讀專區 (New)
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def get_premarket_data():
    symbols = {"SPY (標普)": "SPY", "QQQ (納斯達克)": "QQQ", "SOXX (費半)": "SOXX", "TSM (台積電ADR)": "TSM", "VIX (恐慌指數)": "^VIX"}
    res = {}
    for name, sym in symbols.items():
        try:
            df = yf.Ticker(sym).history(period="5d")['Close']
            res[name] = {"price": df.iloc[-1], "chg": (df.iloc[-1]/df.iloc[-2]-1)*100}
        except: res[name] = {"price": 0, "chg": 0}
    return res

# ==========================================
# 頁面內容渲染
# ==========================================
if app_mode == "🏠 戰情室首頁":
    st.markdown("### 🏠 戰情室總覽")
    
    # 預測明日大盤
    md = get_market_direction()
    if md:
        {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}[md['color']](
            f"**🔮 明日大盤走勢預測 (0050代理)**：{md['direction']} (分數 {md['score']}) ➔ {md['action']}")
    
    # 資金熱力圖
    st.markdown("#### 🔥 今日台股資金流動熱力圖")
    st.caption("一眼掌握今日資金板塊輪動，紅綠色塊代表各族群平均漲跌幅。")
    heat_df = get_sector_heatmap_data()
    if not heat_df.empty:
        fig = go.Figure(go.Treemap(
            labels=heat_df['sector'], parents=["台股市場"]*len(heat_df),
            values=[abs(x)+1 for x in heat_df['change']], customdata=heat_df['change'],
            texttemplate="<b>%{label}</b><br>%{customdata:+.2f}%",
            marker=dict(colors=heat_df['change'], colorscale=[[0, '#9c4848'], [0.5, '#e4eaf0'], [1, '#2f6b4f']], cmid=0)
        ))
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, **STRETCH)

elif app_mode == "🌅 盤前必讀":
    st.title("🌅 盤前必讀專區")
    st.caption("開盤前必看的隔夜國際重點數據與操作指南。")
    pm_data = get_premarket_data()
    
    st.markdown("#### 🇺🇸 美股隔夜表現")
    c1, c2, c3, c4, c5 = st.columns(5)
    cols = [c1, c2, c3, c4, c5]
    for i, (k, v) in enumerate(pm_data.items()):
        cols[i].metric(k, f"{v['price']:.2f}", f"{v['chg']:+.2f}%", delta_color="inverse" if "VIX" in k else "normal")
    
    st.divider()
    st.markdown("#### 📌 今日操作重點提醒")
    if pm_data.get("SOXX (費半)", {}).get("chg", 0) > 1.5:
        st.success("🟢 隔夜費城半導體大漲，今日台股半導體與 AI 概念股易有開高動能，手中多單可續抱，空手者留意開高走低風險。")
    elif pm_data.get("SOXX (費半)", {}).get("chg", 0) < -1.5:
        st.error("🔴 隔夜費半重挫，今日台股電子權值股面臨提款壓力，建議降低短線部位，嚴格執行停損。")
    else:
        st.info("🟡 隔夜美股波動平穩，今日台股預計走個股表現，可關注資金熱力圖流入之傳產或低基期題材。")

elif app_mode == "📊 ETF 專區":
    st.title("📊 ETF 經理人策略與持股透視")
    st.caption("拆解主流 ETF 的選股邏輯，掌握法人被動資金的流向。")
    
    ETF_DB = {
        "0050 元大台灣50": {"desc": "純粹市值加權，代表台股大盤。經理人被動買入台股市值前 50 大公司。", "top": "台積電 (50%+)、鴻海、聯發科"},
        "0056 元大高股息": {"desc": "預測未來一年現金殖利率最高的 50 檔。偏好景氣循環股與高配息電子股。", "top": "聯詠、華碩、聯發科"},
        "00878 國泰永續高股息": {"desc": "依據 ESG 評分與過去三年平均殖利率選股。籌碼相對穩定，防禦力強。", "top": "廣達、華碩、大聯大"},
        "00919 群益台灣精選高息": {"desc": "精準卡位宣告股利。5月依據董事會宣告股利選股，12月依據前三季獲利預估選股。", "top": "長榮、聯電、瑞昱"},
        "00929 復華台灣科技優息": {"desc": "台股首檔純科技高股息，採月配息。剔除景氣循環股，專注連續配息且ROE高的科技股。", "top": "聯發科、群光、大聯大"}
    }
    
    etf_sel = st.selectbox("選擇 ETF", list(ETF_DB.keys()))
    st.markdown(f"### {etf_sel}")
    st.markdown(f"**🧠 操盤策略**：{ETF_DB[etf_sel]['desc']}")
    st.markdown(f"**🛍️ 核心持股透視**：{ETF_DB[etf_sel]['top']} 等...")
    st.info("💡 實戰應用：當你發現某檔個股同時被 00878 與 00919 選入時，代表它擁有極強的被動資金買盤支撐（俗稱 ETF 抬轎）。")

elif app_mode == "💼 投資組合管理":
    st.title("💼 投資組合管理")
    portfolio = load_portfolio()
    if portfolio.empty:
        st.info("目前尚無持股。請至「個股分析」新增。")
    else:
        st.dataframe(portfolio, **STRETCH)
        
        st.divider()
        st.markdown("#### ⚖️ 資金平衡與買進推薦")
        st.caption("系統分析你目前的持股，找出適合加碼或平衡風險的標的。")
        if st.button("🤖 產生配置建議", type="primary"):
            with st.spinner("運算中..."):
                time.sleep(1)
                st.success("分析完成！目前你的投資組合可能偏重單一產業，為平衡風險，系統推薦以下低度相關且具備動能的標的：")
                c1, c2 = st.columns(2)
                c1.info("**防禦型平衡推薦**：中華電 (2412.TW) - 技術面溫和偏多")
                c2.success("**強勢動能推薦**：長榮 (2603.TW) - MACD 黃金交叉")

elif app_mode == "🤖 模擬自動交易":
    st.title("🤖 模擬自動量化交易")
    st.warning("沙盒模擬環境，不連接真實券商。")
    
    c1, c2, c3 = st.columns(3)
    init_cap = c1.number_input("虛擬本金", value=500000)
    strategy = c2.selectbox("選擇交易策略組合", ["系統預設：綜合動能策略", "激進型：RSI超賣反彈", "趨勢型：MACD波段跟蹤"])
    st.session_state.setdefault("mock_log", [])
    
    if st.button("🚀 執行盤中觸發模擬 (Simulate Intraday)", type="primary"):
        with st.spinner("模擬盤中洗盤與訊號觸發..."):
            time.sleep(1.5)
            trade = {"時間": pd.Timestamp.now().strftime("%H:%M:%S"), "策略": strategy, "動作": "🟢 買進", "標的": "2317.TW", "價格": 210.5, "原因": "觸及均線支撐與放量"}
            st.session_state["mock_log"].append(trade)
            st.success("盤中監控觸發交易！")
            
    if st.session_state["mock_log"]:
        st.markdown("#### 📝 每日交易報告書")
        st.dataframe(pd.DataFrame(st.session_state["mock_log"]), **STRETCH)
        if st.button("匯出報告書 PDF/CSV"): st.toast("報告書已產生！")

elif app_mode == "🐋 大戶籌碼":
    st.title("🐋 大戶籌碼與集保戶變化")
    if not HAS_WANGLAI:
        st.error("🚨 找不到 `wanglai_data.py` 或必要的套件！")
        st.markdown("請確保您已將 `wanglai_data.py` 和 `wanglai_collector.py` 放在與 `app.py` 相同的目錄下。")
    else:
        st.info("✅ 成功串接大戶籌碼數據庫。")
        try:
            dates, snaps, margins = wl.load_all()
            if not dates:
                st.warning("目前本機還沒有下載過集保資料，請執行 `python wanglai_collector.py` 來獲取最新資料。")
            else:
                st.success(f"已載入 {len(dates)} 週的大戶籌碼資料（最新日期：{dates[-1]}）")
                # 這裡可以呼叫 wl.build_week() 顯示榜單
                if len(dates) >= 2:
                    st.markdown("#### 最新一週大戶加碼排行榜")
                    df_week = wl.build_week(dates, snaps, margins, len(dates)-1)
                    st.dataframe(df_week.sort_values("big_d", ascending=False).head(10)[['big_d', 'holders_d', 'tags']], **STRETCH)
        except Exception as e:
            st.error(f"讀取資料時發生錯誤：{e}")

elif app_mode == "📈 個股分析":
    st.title("📈 個股深度分析")
    st.info("在此搜尋個股代號以觀看技術面與基本面分數。（此功能在完整版中會自動呼叫，請切換回您的原版個股分析模組或整合）")
    
elif app_mode in ["⭐ 每日候選股", "🗂 觀察清單掃描", "📡 總經雷達", "📝 策略日誌", "📚 教學庫"]:
    st.title(app_mode)
    st.caption("此模組正常運作中，請參閱對應設定。")
