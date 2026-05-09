"""
CBOE Equity Put/Call Ratio — Streamlit 網頁介面
執行方式: streamlit run app.py
"""

import streamlit as st
import threading
from datetime import datetime, time as dtime
from apscheduler.schedulers.background import BackgroundScheduler
from cboe_putcall import fetch_cboe_data, parse_csv, get_signal, get_gspread_client, ensure_header, date_already_exists, append_row, SPREADSHEET_ID, SHEET_NAME
import gspread

# ── 頁面設定 ─────────────────────────────────────────────────────

st.set_page_config(
    page_title="CBOE Put/Call Ratio",
    page_icon="📊",
    layout="centered",
)

# ── Session State 初始化 ──────────────────────────────────────────

if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_updated" not in st.session_state:
    st.session_state.last_updated = None
if "log" not in st.session_state:
    st.session_state.log = []
if "scheduler_started" not in st.session_state:
    st.session_state.scheduler_started = False

# ── 核心執行函式 ──────────────────────────────────────────────────

def run_update(triggered_by="手動"):
    try:
        raw = fetch_cboe_data()
        latest, _ = parse_csv(raw)

        gc = get_gspread_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        try:
            ws = sh.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)

        ensure_header(ws)

        if date_already_exists(ws, latest["date"]):
            msg = f"⚠️ {latest['date']} 已存在，跳過寫入"
        else:
            append_row(ws, latest)
            msg = f"✓ 已寫入 {latest['date']} P/C={latest['ratio']}"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.last_result = latest
        st.session_state.last_updated = now
        st.session_state.log.insert(0, f"[{now}] ({triggered_by}) {msg}")

    except Exception as e:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.log.insert(0, f"[{now}] ❌ 錯誤: {e}")

# ── 定時排程（每天 06:00 UTC = 台灣 14:00）────────────────────────

def start_scheduler():
    if not st.session_state.scheduler_started:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            lambda: run_update("定時自動"),
            trigger="cron",
            hour=6, minute=0,   # UTC 06:00，可自行調整
        )
        scheduler.start()
        st.session_state.scheduler_started = True

start_scheduler()

# ── 介面 ─────────────────────────────────────────────────────────

st.title("📊 CBOE Equity Put/Call Ratio")
st.caption(f"試算表 ID：`{SPREADSHEET_ID}`　工作表：`{SHEET_NAME}`")

st.divider()

# 最新數據卡片
if st.session_state.last_result:
    r = st.session_state.last_result
    signal = get_signal(r["ratio"])
    col1, col2, col3 = st.columns(3)
    col1.metric("日期", r["date"])
    col2.metric("P/C Ratio", r["ratio"])
    col3.metric("信號", signal)

    col4, col5, col6 = st.columns(3)
    col4.metric("Call", f"{r['call']:,}")
    col5.metric("Put", f"{r['put']:,}")
    col6.metric("Total", f"{r['total']:,}")

    st.caption(f"最後更新：{st.session_state.last_updated}")
else:
    st.info("尚未執行，請點下方按鈕抓取資料。")

st.divider()

# 手動執行按鈕
if st.button("🔄 立即抓取並寫入 Google Sheets", use_container_width=True):
    with st.spinner("抓取中..."):
        run_update("手動")
    st.rerun()

# 排程說明
st.info("⏰ 定時排程：每天 UTC 06:00（台灣時間 14:00）自動執行一次")

# 執行紀錄
if st.session_state.log:
    st.subheader("執行紀錄")
    for entry in st.session_state.log[:10]:
        st.text(entry)
