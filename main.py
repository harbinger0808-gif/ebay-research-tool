"""
eBay無在庫転売ツール - メイン実行ファイル
Usage:
    python main.py monitor   # 在庫監視（売り切れ検出→Sheets更新 / eBay取り下げ）
    python main.py test      # 動作確認（APIキー不要）
    python main.py schedule  # スケジューラー起動（常時稼働）
"""
import sys
import time
import warnings
import schedule
warnings.filterwarnings('ignore')

from dotenv import load_dotenv
load_dotenv()


def run_monitor():
    """在庫監視ジョブ"""
    print("\n===== 在庫監視開始 =====")
    try:
        from sheets_client import get_active_listings, update_status
        from monitor import monitor_all_listings

        listings = get_active_listings()
        if not listings:
            print("出品済み商品なし。スキップ。")
            return

        sold_items = monitor_all_listings(listings)

        for item in sold_items:
            # eBay APIキーがあれば取り下げ、なければSheetsのステータスのみ更新
            ebay_id = item.get("ebay_item_id", "")
            if ebay_id and not ebay_id.startswith("DUMMY"):
                from ebay_client import end_item
                end_item(ebay_id)

            update_status(item["sheet_row"], "取下済（要確認）")
            print(f"  → Sheets更新完了: {item.get('title','')[:30]}")

        print(f"\n監視完了: {len(sold_items)}件が売り切れ検出")
    except Exception as e:
        print(f"監視エラー: {e}")
    print("===== 在庫監視完了 =====\n")


def run_test():
    """APIキーなしで動作確認するテストモード"""
    print("\n===== テストモード =====")
    from monitor import check_url
    test_cases = [
        ("https://httpbin.org/status/200", "在庫あり"),
        ("https://httpbin.org/status/404", "売り切れ"),
    ]
    for url, expected in test_cases:
        result = check_url(url)
        status = "在庫あり" if result else "売り切れ/削除"
        mark = "OK" if status == expected else "NG"
        print(f"  [{mark}] {expected} → {status}")
    print("===== テスト完了 =====\n")


def run_schedule():
    """スケジューラーモード（常時稼働）"""
    print("スケジューラー起動")
    print("  - 在庫監視: 30分ごと")
    print("  - Ctrl+C で停止\n")
    schedule.every(30).minutes.do(run_monitor)
    run_monitor()
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "test"
    if command == "monitor":
        run_monitor()
    elif command == "schedule":
        run_schedule()
    else:
        run_test()
