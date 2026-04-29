import gspread
from google.oauth2.service_account import Credentials
import os
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# スプレッドシートの列定義
COL_SOURCE_URL   = 1  # A: 仕入先URL
COL_TITLE        = 2  # B: 商品名
COL_BUY_PRICE    = 3  # C: 仕入価格(円)
COL_EBAY_PRICE   = 4  # D: eBay落札相場(USD)
COL_PROFIT       = 5  # E: 推定利益(円)
COL_PROFIT_RATE  = 6  # F: 利益率(%)
COL_CONDITION    = 7  # G: コンディション
COL_STATUS       = 8  # H: 監視ステータス
COL_EBAY_ITEM_ID = 9  # I: eBay ItemID


def get_sheet():
    creds = Credentials.from_service_account_file(
        os.path.join(os.path.dirname(__file__), "service_account.json"),
        scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.getenv("GOOGLE_SHEETS_ID")).sheet1


def get_active_listings() -> list:
    """ステータスが「出品済」の商品一覧を取得"""
    sheet = get_sheet()
    records = sheet.get_all_records()
    result = []
    for i, r in enumerate(records):
        if r.get("監視ステータス") == "出品済":
            result.append({
                "url": r.get("仕入先URL", ""),
                "ebay_item_id": str(r.get("eBay ItemID", "")),
                "title": r.get("商品名", ""),
                "sheet_row": i + 2  # ヘッダー行分+1
            })
    return result


def update_status(row: int, status: str):
    """指定行のステータスを更新"""
    sheet = get_sheet()
    sheet.update_cell(row, COL_STATUS, status)
    print(f"  Sheets更新: 行{row} → {status}")


def add_candidate(data: dict):
    """
    新規候補商品をシートに追加
    data = {
        "url": str, "title": str, "buy_price": int,
        "ebay_price_usd": float, "profit": int,
        "profit_rate": float, "condition": str
    }
    """
    sheet = get_sheet()
    sheet.append_row([
        data.get("url", ""),
        data.get("title", ""),
        data.get("buy_price", 0),
        data.get("ebay_price_usd", 0),
        data.get("profit", 0),
        round(data.get("profit_rate", 0), 1),
        data.get("condition", ""),
        "候補",  # 初期ステータス
        ""       # eBay ItemID（出品後に記入）
    ])
    print(f"  候補追加: {data.get('title', '')}")
