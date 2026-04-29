import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

# 売り切れを示すキーワード（メルカリ・ヤフオク・エコリング共通）
SOLD_KEYWORDS = [
    "売り切れ",
    "SOLD",
    "売却済",
    "商品は売り切れました",
    "この商品は現在購入できません",
    "購入できません",
    "item not found",
    "Page Not Found",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def check_url(url: str) -> bool:
    """
    在庫確認。True=在庫あり、False=売り切れ/削除済
    エラー時は安全側（False=取り下げ方向）を返す
    """
    proxy_url = os.getenv("PROXY_URL")
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    try:
        r = requests.get(url, headers=HEADERS, proxies=proxies, timeout=15)
        if r.status_code == 404:
            print(f"  404検出: {url[:60]}...")
            return False
        for kw in SOLD_KEYWORDS:
            if kw in r.text:
                print(f"  売り切れキーワード「{kw}」検出: {url[:60]}...")
                return False
        return True
    except requests.exceptions.Timeout:
        print(f"  タイムアウト（安全側で取り下げ対象）: {url[:60]}...")
        return False
    except Exception as e:
        print(f"  チェックエラー: {e}")
        return False


def monitor_all_listings(listings: list) -> list:
    """
    全出品中商品のURL監視。
    戻り値: 売り切れが検出されたアイテムのリスト
    """
    sold_items = []
    total = len(listings)
    print(f"監視対象: {total}件")

    for idx, item in enumerate(listings, 1):
        print(f"[{idx}/{total}] チェック中: {item.get('title', '')[:30]}")
        in_stock = check_url(item["url"])

        if not in_stock:
            sold_items.append(item)
            print(f"  → 売り切れ検出！eBay取り下げ対象に追加")
        else:
            print(f"  → 在庫あり")

        time.sleep(2)  # サーバー負荷軽減

    return sold_items
