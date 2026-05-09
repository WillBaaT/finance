"""
CBOE Equity Put/Call Ratio → Google Sheets
執行環境: Claude Code (Python)
需求: pip install requests gspread google-auth google-auth-oauthlib
"""

import requests
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import csv
import io
from datetime import datetime

# ── 設定區 ────────────────────────────────────────────────────────

# OAuth 憑證檔案路徑（從 Google Cloud Console 下載的 client_secret.json）
CLIENT_SECRET_FILE = "client_secret.json"

# Token 快取檔（第一次執行後自動產生，之後免重新登入）
TOKEN_FILE = "token.json"

# Google Sheets 試算表 ID（從網址取得）
# 例: https://docs.google.com/spreadsheets/d/【這裡】/edit
SPREADSHEET_ID = "16ozK0pwZVBP_0Of4XEz0MjVrNP9Ro6nUQhC2fhJVZrU"

# 工作表名稱
SHEET_NAME = "CBOE_PutCall"

# CBOE CSV URL
CSV_URL = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv"

# 要寫入的欄位標題（第一次執行時自動建立）
HEADERS = ["Date", "Call", "Put", "Total", "P/C Ratio", "Signal", "Updated"]

# ── Google Sheets 認證 ────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_gspread_client():
    creds = None

    # 讀取已快取的 token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # token 不存在或已過期 → 重新認證
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # 儲存 token 供下次使用
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


# ── 抓 CBOE CSV ───────────────────────────────────────────────────

def fetch_cboe_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/csv,text/plain,*/*",
    }
    resp = requests.get(CSV_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_csv(text):
    """解析 CBOE CSV，回傳最新一筆資料"""
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        if len(row) < 5:
            continue
        date_str = row[0].strip()
        # 格式: MM/DD/YYYY
        if not date_str or not date_str[0].isdigit():
            continue
        try:
            datetime.strptime(date_str, "%m/%d/%Y")
            call  = int(row[1].strip().replace(",", ""))
            put   = int(row[2].strip().replace(",", ""))
            total = int(row[3].strip().replace(",", ""))
            ratio = float(row[4].strip())
            rows.append({
                "date":  date_str,
                "call":  call,
                "put":   put,
                "total": total,
                "ratio": ratio,
            })
        except (ValueError, IndexError):
            continue

    if not rows:
        raise ValueError("CSV 解析失敗，無有效資料")

    # 按日期排序，回傳最新一筆
    rows.sort(key=lambda r: datetime.strptime(r["date"], "%m/%d/%Y"))
    return rows[-1], rows  # (最新一筆, 全部)


def get_signal(ratio):
    if ratio < 0.6:  return "⚠️ 極度偏多"
    if ratio < 0.8:  return "📈 偏多"
    if ratio < 1.1:  return "✅ 中性"
    return                  "📉 偏空"


# ── 寫入 Google Sheets ────────────────────────────────────────────

def ensure_header(sheet):
    """確保第一行是標題"""
    try:
        first = sheet.row_values(1)
    except Exception:
        first = []

    if first != HEADERS:
        sheet.insert_row(HEADERS, index=1)
        print("✓ 已建立標題列")


def date_already_exists(sheet, date_str):
    """檢查該日期是否已寫入（避免重複）"""
    col_a = sheet.col_values(1)  # Date 欄
    return date_str in col_a


def append_row(sheet, latest):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    row = [
        latest["date"],
        latest["call"],
        latest["put"],
        latest["total"],
        latest["ratio"],
        get_signal(latest["ratio"]),
        now,
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")


# ── 主流程 ────────────────────────────────────────────────────────

def main():
    print("=== CBOE Equity Put/Call Ratio Updater ===")

    # 1. 抓資料
    print(f"抓取 {CSV_URL} ...")
    raw = fetch_cboe_data()
    latest, all_rows = parse_csv(raw)
    print(f"最新資料: {latest['date']} | P/C Ratio: {latest['ratio']} | {get_signal(latest['ratio'])}")

    # 2. 連接 Google Sheets
    print("連接 Google Sheets ...")
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    # 取得或建立工作表
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        print(f"✓ 已建立工作表: {SHEET_NAME}")

    # 3. 確保標題列存在
    ensure_header(ws)

    # 4. 檢查是否重複
    if date_already_exists(ws, latest["date"]):
        print(f"⚠️  {latest['date']} 已存在，跳過寫入")
    else:
        append_row(ws, latest)
        print(f"✓ 已寫入: {latest['date']} P/C={latest['ratio']}")

    print("=== 完成 ===")
    return latest


if __name__ == "__main__":
    result = main()
    print(f"\n今日 Equity P/C Ratio: {result['ratio']} → {get_signal(result['ratio'])}")
