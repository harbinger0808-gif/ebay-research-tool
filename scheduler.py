"""
スケジューラー — macOS LaunchAgent用エントリーポイント
毎朝9:00にリサーチ、30分ごとに在庫監視を実行する
"""
import schedule
import time
import warnings
import logging
import os
warnings.filterwarnings('ignore')

from dotenv import load_dotenv
load_dotenv()

# ログ設定
log_path = os.path.join(os.path.dirname(__file__), "logs", "ebay_tool.log")
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


def monitoring_job():
    logging.info("在庫監視ジョブ開始")
    try:
        from sheets_client import get_active_listings, update_status
        from monitor import monitor_all_listings
        from ebay_client import end_item

        listings = get_active_listings()
        if not listings:
            logging.info("出品済み商品なし")
            return

        sold_items = monitor_all_listings(listings)
        for item in sold_items:
            ebay_id = item.get("ebay_item_id", "")
            if ebay_id and not ebay_id.startswith("DUMMY"):
                end_item(ebay_id)
            update_status(item["sheet_row"], "取下済（要確認）")

        logging.info(f"監視完了: {len(sold_items)}件取り下げ")
    except Exception as e:
        logging.error(f"監視エラー: {e}")


def research_job():
    logging.info("リサーチジョブ開始")
    try:
        from research import run_research
        run_research()
        logging.info("リサーチ完了")
    except Exception as e:
        logging.error(f"リサーチエラー: {e}")


# スケジュール登録
schedule.every(30).minutes.do(monitoring_job)
schedule.every().day.at("09:00").do(research_job)

if __name__ == "__main__":
    logging.info("スケジューラー起動")
    print("スケジューラー起動 — Ctrl+C で停止")
    monitoring_job()  # 起動時即実行
    while True:
        schedule.run_pending()
        time.sleep(60)
