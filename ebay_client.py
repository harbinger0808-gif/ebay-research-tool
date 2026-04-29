import os
import time
from dotenv import load_dotenv

load_dotenv()

# ebaysdkのインポート（APIキー設定後に有効化）
try:
    from ebaysdk.trading import Connection as Trading
    EBAY_SDK_AVAILABLE = True
except ImportError:
    EBAY_SDK_AVAILABLE = False

# Sandbox/Production切り替え（.envに EBAY_SANDBOX=true で開発モード）
IS_SANDBOX = os.getenv("EBAY_SANDBOX", "false").lower() == "true"
IS_READ_ONLY = os.getenv("EBAY_READ_ONLY", "true").lower() == "true"

# レート制限：リクエスト間隔（秒）
_RATE_LIMIT_INTERVAL = 0.5
_last_request_time = 0.0


def _wait_rate_limit():
    """レート制限：前回リクエストから一定時間待つ"""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _RATE_LIMIT_INTERVAL:
        time.sleep(_RATE_LIMIT_INTERVAL - elapsed)
    _last_request_time = time.time()


def _get_api():
    if IS_SANDBOX:
        domain = "api.sandbox.ebay.com"
        app_id = os.getenv("EBAY_SANDBOX_APP_ID", os.getenv("EBAY_APP_ID"))
        cert_id = os.getenv("EBAY_SANDBOX_CERT_ID", os.getenv("EBAY_CERT_ID"))
        dev_id = os.getenv("EBAY_SANDBOX_DEV_ID", os.getenv("EBAY_DEV_ID"))
        token = os.getenv("EBAY_SANDBOX_USER_TOKEN", os.getenv("EBAY_USER_TOKEN"))
        print("[SANDBOX MODE]")
    else:
        domain = "api.ebay.com"
        app_id = os.getenv("EBAY_APP_ID")
        cert_id = os.getenv("EBAY_CERT_ID")
        dev_id = os.getenv("EBAY_DEV_ID")
        token = os.getenv("EBAY_USER_TOKEN")

    return Trading(
        domain=domain,
        appid=app_id,
        certid=cert_id,
        devid=dev_id,
        token=token,
        config_file=None,
        siteid="0"  # 0=US, 3=UK, 15=AU
    )


def end_item(item_id: str) -> bool:
    """
    eBay出品を即時取り下げ。
    戻り値: True=成功, False=失敗
    """
    if IS_READ_ONLY:
        print(f"  [READ_ONLY] 取り下げをブロック: {item_id} (.envのEBAY_READ_ONLY=falseで解除)")
        return False

    if not EBAY_SDK_AVAILABLE:
        print(f"  [SKIP] ebaysdk未インストール: {item_id}")
        return False

    if not os.getenv("EBAY_USER_TOKEN") and not os.getenv("EBAY_SANDBOX_USER_TOKEN"):
        print(f"  [SKIP] EBAY_USER_TOKEN未設定: {item_id}")
        return False

    try:
        _wait_rate_limit()
        api = _get_api()
        response = api.execute("EndItem", {
            "ItemID": item_id,
            "EndingReason": "NotAvailableAnymore"
        })
        print(f"  eBay取り下げ完了: ItemID={item_id}")
        return True
    except Exception as e:
        print(f"  eBay取り下げ失敗 ItemID={item_id}: {e}")
        return False


def get_active_item_ids() -> list:
    """現在出品中のeBay ItemIDを取得"""
    if not os.getenv("EBAY_USER_TOKEN") and not os.getenv("EBAY_SANDBOX_USER_TOKEN"):
        print("[SKIP] EBAY_USER_TOKEN未設定")
        return []

    try:
        _wait_rate_limit()
        api = _get_api()
        response = api.execute("GetMyeBaySelling", {
            "ActiveList": {
                "Include": True,
                "Pagination": {"EntriesPerPage": 200, "PageNumber": 1}
            }
        })
        items = response.reply.ActiveList.ItemArray.Item
        return [item.ItemID for item in items]
    except Exception as e:
        print(f"出品一覧取得失敗: {e}")
        return []
