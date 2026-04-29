"""
日次レポート生成モジュール
Sheetsの状態を集計して、ターミナルとログに出力する
"""
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime
from dotenv import load_dotenv
load_dotenv()


def generate_report():
    from sheets_client import get_sheet

    sheet = get_sheet()
    records = sheet.get_all_records()

    total      = len(records)
    listing    = sum(1 for r in records if r.get("監視ステータス") == "出品済")
    candidates = sum(1 for r in records if r.get("監視ステータス") == "候補")
    delisted   = sum(1 for r in records if "取下済" in str(r.get("監視ステータス", "")))

    # 推定利益合計（出品済のもの）
    profit_total = sum(
        int(str(r.get("推定利益(円)", 0)).replace(",", "") or 0)
        for r in records
        if r.get("監視ステータス") == "出品済"
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = f"""
{'='*50}
 eBayツール 日次レポート  {now}
{'='*50}
 総登録商品数  : {total:>4} 件
 出品中        : {listing:>4} 件
 候補（未出品）: {candidates:>4} 件
 取り下げ済み  : {delisted:>4} 件
{'─'*50}
 出品中の推定利益合計: {profit_total:>10,} 円
{'='*50}
"""
    print(report)
    return {
        "total": total, "listing": listing,
        "candidates": candidates, "delisted": delisted,
        "profit_total": profit_total,
    }


if __name__ == "__main__":
    generate_report()
