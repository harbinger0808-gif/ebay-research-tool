"""
eBay落札相場リサーチモジュール
eBay完了リスト（Sold Items）から実際の落札価格を取得する
APIキー不要・ブラウザスクレイピング方式
"""
import time
import warnings
warnings.filterwarnings('ignore')

from playwright.sync_api import sync_playwright


def get_ebay_sold_prices(keyword: str, max_items: int = 10) -> dict:
    """
    eBayで過去に売れた価格を取得する
    戻り値: {
        "keyword": str,
        "prices_usd": [float],
        "average_usd": float,
        "median_usd": float,
        "min_usd": float,
        "max_usd": float,
        "sample_count": int,
    }
    """
    prices = []
    encoded = keyword.replace(" ", "+")
    url = (
        f"https://www.ebay.com/sch/i.html"
        f"?_nkw={encoded}&LH_Complete=1&LH_Sold=1&_sop=13"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        try:
            page.goto(url, timeout=30000)
            page.wait_for_timeout(2000)

            items = page.query_selector_all(".s-item")
            for item in items[:max_items + 5]:  # 少し多めに取得してフィルタ
                price_el = item.query_selector(".s-item__price")
                if not price_el:
                    continue
                price_text = price_el.inner_text().strip()
                # "$1,234.56" → 1234.56
                try:
                    price = float(
                        price_text.replace("$", "").replace(",", "").split()[0]
                    )
                    if price > 0:
                        prices.append(price)
                except ValueError:
                    continue
                if len(prices) >= max_items:
                    break
        except Exception as e:
            print(f"  eBay価格取得エラー: {e}")
        finally:
            browser.close()

    if not prices:
        return {"keyword": keyword, "prices_usd": [], "average_usd": 0,
                "median_usd": 0, "min_usd": 0, "max_usd": 0, "sample_count": 0}

    sorted_prices = sorted(prices)
    mid = len(sorted_prices) // 2
    median = (
        (sorted_prices[mid - 1] + sorted_prices[mid]) / 2
        if len(sorted_prices) % 2 == 0
        else sorted_prices[mid]
    )

    return {
        "keyword": keyword,
        "prices_usd": sorted_prices,
        "average_usd": round(sum(prices) / len(prices), 2),
        "median_usd": round(median, 2),
        "min_usd": sorted_prices[0],
        "max_usd": sorted_prices[-1],
        "sample_count": len(prices),
    }


def print_price_report(result: dict):
    if result["sample_count"] == 0:
        print(f"  「{result['keyword']}」: 価格データなし")
        return
    print(f"\n  【{result['keyword']}】eBay落札相場（直近{result['sample_count']}件）")
    print(f"  平均: ${result['average_usd']}")
    print(f"  中央: ${result['median_usd']}  ← 出品価格の参考値として最適")
    print(f"  最安: ${result['min_usd']}  /  最高: ${result['max_usd']}")
    prices_str = "  ".join([f"${p}" for p in result["prices_usd"]])
    print(f"  内訳: {prices_str}")


if __name__ == "__main__":
    keywords = [
        "Louis Vuitton wallet used",
        "Gucci bag used",
        "Rolex watch used",
    ]
    print("===== eBay落札相場リサーチ =====")
    for kw in keywords:
        print(f"\n検索中: {kw}")
        result = get_ebay_sold_prices(kw, max_items=8)
        print_price_report(result)
        time.sleep(3)
    print("\n===== 完了 =====")
