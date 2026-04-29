"""
リサーチモジュール
メルカリ・ヤフオク・エコリングから利益商品候補を抽出してSheetsに追加する
"""
import requests
import time
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# コスト設定（実態に合わせて変更してください）
# ============================================================

# 為替レート（円/USD）— 定期更新推奨
USD_TO_JPY = 149.0

# 目標利益率（%）
TARGET_PROFIT_RATE = 30.0

# --- eBay側コスト ---
EBAY_FEE_RATE       = 0.1325  # eBay最終落札手数料 13.25%（カテゴリで変動あり）
PAYPAL_FEE_RATE     = 0.029   # Payoneer/PayPal受取手数料 2.9%
EXCHANGE_SPREAD     = 0.015   # 為替スプレッド 1.5%（円転時のロス）

# --- 送料コスト ---
SHIPPING_COST       = 3750    # 国際送料目安（円）3,500〜4,000円の中間値
PACKAGING_COST      = 300     # 梱包資材費（箱・エアパッキン等）

# --- 仕入れ側コスト ---
MERCARI_BUY_FEE     = 0       # メルカリ購入手数料（購入者負担なし）
YAHOOAUCTION_BUY_FEE = 0      # ヤフオク落札手数料（落札者負担なし）

# --- その他リスクバッファ ---
RETURN_RISK_RATE    = 0.03    # 返品リスク引当 3%（eBayはバイヤー優先）

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def calc_profit(buy_price_jpy: int, ebay_sold_usd: float, verbose: bool = False, usd_jpy: float = None) -> dict:
    """
    詳細利益計算
    buy_price_jpy : 仕入価格（円）
    ebay_sold_usd : eBay落札相場（USD）
    verbose       : Trueで内訳を表示
    usd_jpy       : 為替レート（Noneの場合はデフォルト値を使用）
    """
    rate = usd_jpy if usd_jpy else USD_TO_JPY
    # ① 売上を円換算
    gross_jpy = ebay_sold_usd * rate

    # ② eBay側コストを差し引く
    ebay_fee      = gross_jpy * EBAY_FEE_RATE       # eBay手数料
    paypal_fee    = gross_jpy * PAYPAL_FEE_RATE      # 決済手数料
    fx_loss       = gross_jpy * EXCHANGE_SPREAD      # 為替スプレッド
    return_risk   = gross_jpy * RETURN_RISK_RATE     # 返品リスク引当

    # ③ 手元に残る金額
    net_jpy = gross_jpy - ebay_fee - paypal_fee - fx_loss - return_risk

    # ④ 仕入れ・発送コストを差し引く
    total_cost = buy_price_jpy + SHIPPING_COST + PACKAGING_COST

    # ⑤ 最終利益
    profit = net_jpy - total_cost
    profit_rate = (profit / total_cost) * 100

    if verbose:
        print(f"\n  {'─'*40}")
        print(f"  eBay売値      :  ${ebay_sold_usd:.2f} = {gross_jpy:>8,.0f}円")
        print(f"  eBay手数料    : -{ebay_fee:>8,.0f}円  ({EBAY_FEE_RATE*100:.2f}%)")
        print(f"  決済手数料    : -{paypal_fee:>8,.0f}円  ({PAYPAL_FEE_RATE*100:.1f}%)")
        print(f"  為替スプレッド: -{fx_loss:>8,.0f}円  ({EXCHANGE_SPREAD*100:.1f}%)")
        print(f"  返品リスク引当: -{return_risk:>8,.0f}円  ({RETURN_RISK_RATE*100:.1f}%)")
        print(f"  {'─'*40}")
        print(f"  手元売上      :  {net_jpy:>8,.0f}円")
        print(f"  {'─'*40}")
        print(f"  仕入価格      : -{buy_price_jpy:>8,.0f}円")
        print(f"  国際送料      : -{SHIPPING_COST:>8,.0f}円")
        print(f"  梱包資材      : -{PACKAGING_COST:>8,.0f}円")
        print(f"  {'─'*40}")
        print(f"  純利益        :  {profit:>8,.0f}円  (利益率 {profit_rate:.1f}%)")
        print(f"  判定          :  {'★ 目標達成（30%以上）' if profit_rate >= TARGET_PROFIT_RATE else '× 利益率不足'}")
        print(f"  {'─'*40}\n")

    return {
        "gross_jpy":    int(gross_jpy),
        "ebay_fee":     int(ebay_fee),
        "paypal_fee":   int(paypal_fee),
        "fx_loss":      int(fx_loss),
        "return_risk":  int(return_risk),
        "shipping":     SHIPPING_COST,
        "packaging":    PACKAGING_COST,
        "total_cost":   int(total_cost),
        "profit":       int(profit),
        "profit_rate":  round(profit_rate, 1),
        "is_target":    profit_rate >= TARGET_PROFIT_RATE,
    }


def search_mercari_manual(keyword: str) -> list:
    """
    メルカリ検索URL生成（手動確認用）
    ※ メルカリはBot対策が強いため、URLを生成してブラウザで確認する方式
    """
    encoded = requests.utils.quote(keyword)
    url = f"https://jp.mercari.com/search?keyword={encoded}&status=on_sale&sort=price&order=asc"
    return [{
        "platform": "メルカリ",
        "search_url": url,
        "note": "ブラウザで確認し、候補商品のURLをシートに手動入力してください"
    }]


def search_yahooauction(keyword: str, max_price: int = 10000) -> list:
    """
    ヤフオクの現在出品を検索（公式APIなしのため検索URL生成）
    """
    encoded = requests.utils.quote(keyword)
    url = (
        f"https://auctions.yahoo.co.jp/search/search"
        f"?p={encoded}&max={max_price}&istatus=1&s1=cbids&o1=d"
    )
    return [{
        "platform": "ヤフオク",
        "search_url": url,
        "note": "ブラウザで確認し、候補商品のURLをシートに手動入力してください"
    }]


def search_ecoring(keyword: str) -> list:
    """
    エコリング検索URL生成
    """
    encoded = requests.utils.quote(keyword)
    url = f"https://www.eco-ring.com/products/search?keyword={encoded}"
    return [{
        "platform": "エコリング",
        "search_url": url,
        "note": "ブラウザで確認し、候補商品のURLをシートに手動入力してください"
    }]


def run_research(keywords: list = None):
    """
    リサーチ実行 — 検索URLを生成してログ出力
    実際の商品追加はシートへの手動入力 or 将来の自動化で対応
    """
    if keywords is None:
        keywords = [
            "ヴィトン 財布",
            "グッチ バッグ",
            "ロレックス",
            "シャネル",
            "ヘルメス",
        ]

    print("\n===== リサーチ開始 =====")
    for kw in keywords:
        print(f"\n【{kw}】")
        for result in search_mercari_manual(kw):
            print(f"  {result['platform']}: {result['search_url']}")
        for result in search_yahooauction(kw):
            print(f"  {result['platform']}: {result['search_url']}")
        for result in search_ecoring(kw):
            print(f"  {result['platform']}: {result['search_url']}")
        time.sleep(0.5)

    print("\n利益計算例（詳細）:")
    examples = [
        (3000,  45.0,  "財布（低単価）"),
        (8000,  120.0, "バッグ（中単価）"),
        (15000, 250.0, "時計（高単価）"),
    ]
    for buy, sell_usd, name in examples:
        print(f"\n【{name}】仕入:{buy:,}円 / eBay:${sell_usd}")
        calc_profit(buy, sell_usd, verbose=True)

    print("===== リサーチ完了 =====\n")


if __name__ == "__main__":
    run_research()
