"""
eBayリサーチ・スコアリングモジュール
ジャンル別TOP5（有在庫4ジャンル・無在庫4ジャンル）
"""
import os
import time
import base64
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from research import calc_profit

load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OAUTH_URL      = "https://api.ebay.com/identity/v1/oauth2/token"
FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"
APP_ID = os.getenv("EBAY_APP_ID", "")

# スコアリング条件
MIN_PROFIT_RATE  = 30.0   # 利益率30%以上
MIN_SELL_THROUGH = 20.0   # 売れ率20%以上
MAX_COMPETITION  = 100    # 日本セラーに絞るとライバル100件以下が現実的
MIN_EBAY_PRICE   = 30.0   # eBay売値$30以上
MIN_SOLD_COUNT   = 5      # 日本セラー絞り込み後は5件以上で判定

# トークンキャッシュ
_ebay_token = ""
_ebay_token_expiry = 0.0

# キーワード単位キャッシュ（7日間・メモリ + ファイル）
import json as _json
from datetime import datetime as _dt, timedelta as _td

KW_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".kw_cache.json")
KW_CACHE_TTL  = 7  # 日

def _load_kw_cache() -> dict:
    try:
        with open(KW_CACHE_FILE) as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_kw_cache(cache: dict):
    try:
        with open(KW_CACHE_FILE, "w") as f:
            _json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass

def _kw_cache_get(keyword: str) -> dict | None:
    cache = _load_kw_cache()
    entry = cache.get(keyword)
    if not entry:
        return None
    saved_at = _dt.fromisoformat(entry["saved_at"])
    if _dt.now() - saved_at > _td(days=KW_CACHE_TTL):
        return None
    print(f"  [Cache HIT] {keyword[:35]}")
    return entry["data"]

def _kw_cache_set(keyword: str, data: dict):
    cache = _load_kw_cache()
    cache[keyword] = {"saved_at": _dt.now().isoformat(), "data": data}
    # 古いエントリを掃除
    cutoff = _dt.now() - _td(days=KW_CACHE_TTL + 1)
    cache = {k: v for k, v in cache.items()
             if _dt.fromisoformat(v["saved_at"]) > cutoff}
    _save_kw_cache(cache)


# ===== ジャンル定義 =====

STOCKED_GENRES = {
    "レトロゲーム": [
        "famicom dragon quest japan", "super famicom final fantasy japan",
        "game boy pokemon japan cartridge", "sega saturn japan lot",
        "pc engine japan rare", "famicom lot japan complete",
        "nintendo 64 japan game cartridge", "gameboy advance japan limited",
    ],
    "フィギュア・アニメグッズ": [
        "nendoroid japan exclusive limited", "figma japan limited edition",
        "gundam model kit japan limited", "dragon ball z figure japan vintage",
        "one piece figure japan exclusive", "evangelion figure japan limited",
        "sailor moon figure japan vintage", "demon slayer figure japan limited",
    ],
    "日本限定レゴ・玩具": [
        "lego japan limited set exclusive", "lego ninjago japan limited",
        "lego creator japan exclusive", "lego technic japan limited",
        "pokemon toy japan limited exclusive", "japan exclusive toy limited",
        "bandai kamen rider japan limited", "tomica japan limited diecast",
    ],
    "チェキカメラ": [
        "fujifilm instax mini japan limited", "fujifilm instax square japan",
        "fujifilm instax wide japan limited", "instax mini liplay japan",
        "fujifilm instax mini 99 japan", "instax mini evo japan limited",
    ],
    "消耗品（リピート買い）": [
        "fujifilm instax mini film japan", "instax square film japan",
        "japanese skincare mask sheet bulk", "japan beauty serum collagen",
        "japanese pet snack treat bulk", "japan dog treat freeze dried",
        "japanese cat food premium bulk", "japan dental care pet bulk",
    ],
    "Tシャツ・アパレル（日本限定）": [
        "uniqlo japan limited ut tshirt", "japan anime tshirt limited edition",
        "pokemon center japan tshirt exclusive", "dragon ball z japan shirt limited",
        "studio ghibli japan tshirt official", "naruto japan limited shirt",
    ],
    "古物・ヴィンテージ": [
        "japanese vintage kimono silk obi", "japan vintage tin toy showa",
        "japanese antique porcelain meiji", "japan vintage whisky bottle unopened",
        "japanese vintage camera film showa", "japan vintage magazine anime rare",
        "japanese vintage poster showa retro", "japan vintage playing cards rare",
    ],
    "伝統工芸・職人品": [
        "japanese magewappa bento box handmade", "japanese lacquer box vintage",
        "japanese pottery tea bowl handmade", "japanese bamboo basket woven",
        "japanese kokeshi doll vintage", "japanese cedar tray handmade",
        "japanese indigo dyeing fabric", "japanese washi paper handmade",
    ],
}

DROPSHIP_GENRES = {
    "美容家電（無在庫）": [
        "panasonic face steamer japan nano", "hitachi face steamer japan",
        "panasonic hair dryer japan nano", "yamazen facial massager japan",
        "mtg refa carat japan face roller", "japan led face mask beauty",
        "panasonic epilator japan ladies", "omron tens unit japan",
    ],
    "ペット用品（無在庫）": [
        "japan automatic cat feeder wifi", "japan dog water fountain filter",
        "japanese cat tree tower premium", "japan pet grooming glove",
        "japan interactive cat toy laser", "japanese dog carrier bag premium",
    ],
    "チェキカメラ（無在庫）": [
        "fujifilm instax mini 12 japan", "fujifilm instax mini 40 japan",
        "fujifilm instax link wide japan", "fujifilm instax mini liplay japan",
        "instax mini hello kitty japan", "instax square sq6 japan",
    ],
    "健康器具・マッサージ": [
        "japan shiatsu neck massager", "japanese foot massager electric",
        "japan EMS face lift device", "japanese steam eye mask bulk",
        "japan back stretcher lumbar", "omron blood pressure monitor japan",
    ],
    "カメラ・レンズ": [
        "fujinon vintage lens japan", "super takumar lens japan",
        "canon fd lens japan vintage", "minolta lens japan vintage",
        "japan camera strap leather handmade", "olympus zuiko lens japan",
    ],
}

STOCKED_SOURCES  = ["ヤフオク", "エコリング", "ハードオフ", "駿河屋", "Amazon"]
DROPSHIP_SOURCES = ["Amazon", "キタムラ", "ヨドバシ"]

SOURCE_URL_MAP = {
    "ヤフオク":   lambda e: f"https://auctions.yahoo.co.jp/search/search?p={e}&istatus=1&s1=cbids&o1=a",
    "エコリング": lambda e: f"https://www.eco-ring.com/products/search?keyword={e}",
    "ハードオフ": lambda e: f"https://hardoff.co.jp/search/?q={e}&sort=price_asc",
    "駿河屋":     lambda e: f"https://www.suruga-ya.jp/search?category=0&search_word={e}&soldout=1&order=price_asc",
    "Amazon":     lambda e: f"https://www.amazon.co.jp/s?k={e}&sort=price-asc-rank",
    "キタムラ":   lambda e: f"https://www.kitamura.jp/search/index.php?q={e}&sort=price_asc",
    "ヨドバシ":   lambda e: f"https://www.yodobashi.com/?word={e}",
}


# ===== OAuth =====

def get_ebay_token() -> str:
    global _ebay_token, _ebay_token_expiry
    if time.time() < _ebay_token_expiry - 60:
        return _ebay_token
    cert_id = os.getenv("EBAY_CERT_ID", "")
    credentials = base64.b64encode(f"{APP_ID}:{cert_id}".encode()).decode()
    try:
        res = requests.post(
            OAUTH_URL,
            headers={"Authorization": f"Basic {credentials}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope",
            timeout=10,
        )
        result = res.json()
        _ebay_token = result.get("access_token", "")
        _ebay_token_expiry = time.time() + result.get("expires_in", 7200)
        print(f"  [OAuth] {'成功' if _ebay_token else '失敗: ' + str(result)}")
        return _ebay_token
    except Exception as e:
        print(f"  [OAuth失敗] {e}")
        return ""


# ===== 為替 =====

def get_usd_to_jpy() -> float:
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        rate = res.json()["rates"]["JPY"]
        print(f"  [為替] 1USD = {rate:.2f}円")
        return rate
    except Exception:
        print("  [為替] 取得失敗 → 150円で代替")
        return 150.0


# ===== eBay データ取得 =====

def _scrape_ebay_sold(keyword: str) -> dict:
    """
    eBay落札済みページを直接スクレイピングして本物の落札データを取得。
    Finding APIの代替として使用。
    """
    enc = requests.utils.quote(keyword)
    # 落札済み + 日本セラーに絞る
    url = (
        f"https://www.ebay.com/sch/i.html"
        f"?_nkw={enc}&LH_Complete=1&LH_Sold=1"
        f"&_sacat=0&LH_ItemCondition=1000&_ipg=60"
    )
    headers = {
        **HEADERS,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select(".s-item")
        prices, top_url = [], ""
        for item in items:
            # "Shop on eBay" などのダミーアイテムを除外
            title_el = item.select_one(".s-item__title")
            if not title_el or "Shop on eBay" in title_el.text:
                continue
            price_el = item.select_one(".s-item__price")
            if not price_el:
                continue
            raw = price_el.get_text(strip=True).replace(",", "").replace("$", "")
            # 範囲表示（例: $10.00 to $20.00）は中間値を使う
            parts = [p for p in raw.split() if p.replace(".", "").isdigit()]
            if not parts:
                continue
            try:
                p = sum(float(x) for x in parts) / len(parts)
                if 0.5 <= p <= 10000:
                    prices.append(p)
                    if not top_url:
                        a = item.select_one(".s-item__link")
                        if a:
                            top_url = a.get("href", "")
            except Exception:
                continue
        if not prices:
            return {"avg_usd": 0, "count": 0, "url": url, "source": "scrape"}
        avg = sum(prices) / len(prices)
        print(f"  [Scrape] {keyword[:30]}... → ${avg:.2f} ({len(prices)}件)")
        return {"avg_usd": round(avg, 2), "count": len(prices), "url": top_url or url, "source": "scrape"}
    except Exception as e:
        print(f"  [Scrape失敗] {keyword}: {e}")
        return {"avg_usd": 0, "count": 0, "url": "", "source": "scrape"}


def get_ebay_sold(keyword: str) -> dict:
    """
    落札データ取得。Finding API → スクレイピングの順で試みる。
    Browse APIの推定値は使わない（精度が低いため）。
    """
    # まずFinding APIを試す
    params = {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "",
        "keywords": keyword,
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "ListingType",
        "itemFilter(1).value": "FixedPrice",
        "itemFilter(2).name": "LocatedIn",
        "itemFilter(2).value": "JP",
        "paginationInput.entriesPerPage": "60",
        "sortOrder": "EndTimeSoonest",
    }
    try:
        res = requests.get(FINDING_API_URL, params=params, headers=HEADERS, timeout=8)
        data = res.json()
        error_id = (
            data.get("errorMessage", [{}])[0]
                .get("error", [{}])[0]
                .get("errorId", [""])[0]
        )
        if error_id:
            print(f"  [Finding API] エラー{error_id} → スクレイピングで代替")
            return _scrape_ebay_sold(keyword)
        items = (
            data.get("findCompletedItemsResponse", [{}])[0]
               .get("searchResult", [{}])[0]
               .get("item", [])
        )
        if not items:
            print(f"  [Finding API] 結果なし → スクレイピングで代替")
            return _scrape_ebay_sold(keyword)
        prices, top_url = [], ""
        for item in items:
            try:
                p = float(item["sellingStatus"][0]["convertedCurrentPrice"][0]["__value__"])
                if 0.5 <= p <= 10000:
                    prices.append(p)
                if not top_url:
                    top_url = item.get("viewItemURL", [""])[0]
            except Exception:
                continue
        avg = sum(prices) / len(prices) if prices else 0
        print(f"  [Finding API] {keyword[:30]}... → ${avg:.2f} ({len(prices)}件)")
        return {"avg_usd": round(avg, 2), "count": len(prices), "url": top_url, "source": "api"}
    except Exception as e:
        print(f"  [Finding API失敗] {keyword}: {e} → スクレイピングで代替")
        return _scrape_ebay_sold(keyword)


def get_ebay_competition(keyword: str) -> int:
    token = get_ebay_token()
    if not token:
        return 9999
    try:
        res = requests.get(
            BROWSE_API_URL,
            params={"q": keyword, "limit": 1, "filter": "buyingOptions:{FIXED_PRICE},itemLocationCountry:JP"},
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            timeout=8,
        )
        return res.json().get("total", 9999)
    except Exception:
        return 9999


def get_ebay_data(keyword: str) -> dict:
    # キャッシュ確認（7日間有効）
    cached = _kw_cache_get(keyword)
    if cached:
        return cached

    sold = get_ebay_sold(keyword)
    competition = get_ebay_competition(keyword)
    sell_through = round(
        sold["count"] / (sold["count"] + competition) * 100, 1
    ) if (sold["count"] + competition) > 0 else 0.0
    result = {**sold, "competition": competition, "sell_through": sell_through}

    # 有効なデータのみキャッシュ保存
    if result["avg_usd"] > 0:
        _kw_cache_set(keyword, result)
    return result


# ===== 仕入れ価格取得 =====

def get_yahooauction_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://auctions.yahoo.co.jp/search/search?p={enc}&istatus=1&s1=cbids&o1=a"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".Product__price"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_ecoring_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.eco-ring.com/products/search?keyword={enc}"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".price, .item-price, [class*='price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and len(digits) <= 7:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_hardoff_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://hardoff.co.jp/search/?q={enc}&sort=price_asc"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select("[class*='price'], [class*='Price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_surugaya_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.suruga-ya.jp/search?category=0&search_word={enc}&soldout=1&order=price_asc"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".item_price, .price, [class*='price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_amazon_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.amazon.co.jp/s?k={enc}&sort=price-asc-rank"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".a-price-whole"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_kitamura_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.kitamura.jp/search/index.php?q={enc}&sort=price_asc"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".price, [class*='price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_yodobashi_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.yodobashi.com/?word={enc}"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        el = soup.select_one(".priceTax")
        if el:
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits:
                return int(digits)
        return 0
    except Exception:
        return 0

PRICE_FN_MAP = {
    "ヤフオク":   get_yahooauction_price,
    "エコリング": get_ecoring_price,
    "ハードオフ": get_hardoff_price,
    "駿河屋":     get_surugaya_price,
    "Amazon":     get_amazon_price,
    "キタムラ":   get_kitamura_price,
    "ヨドバシ":   get_yodobashi_price,
}


# ===== スコアリング =====

def score_product(sold_count: int, competition: int, profit_rate: float) -> float:
    return round((sold_count * max(profit_rate, 0)) / max(competition, 1), 3)


def meets_conditions(r: dict) -> bool:
    return (
        r["profit_rate"]  >= MIN_PROFIT_RATE and
        r["sell_through"] >= MIN_SELL_THROUGH and
        r["competition"]  <= MAX_COMPETITION and
        r["avg_sold_usd"] >= MIN_EBAY_PRICE and
        r["sold_count"]   >= MIN_SOLD_COUNT
    )


# ===== リサーチ実行 =====

def _research_genres(genres: dict, source_names: list,
                     result_type: str, fallback_rate: float) -> dict:
    usd_jpy = get_usd_to_jpy()
    get_ebay_token()  # トークンを事前取得

    result = {}
    for genre, keywords in genres.items():
        print(f"\n[{result_type}] {genre}")

        # eBayデータを並列取得
        ebay_cache = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(get_ebay_data, kw): kw for kw in keywords}
            for f in as_completed(futures):
                kw = futures[f]
                ebay_cache[kw] = f.result()

        # 仕入れ価格を並列取得（全ソースを試して最安値を採用）
        def fetch_best_price(keyword):
            best_price, best_source = 0, ""
            for src in source_names:
                p = PRICE_FN_MAP[src](keyword)
                if p > 0 and (best_price == 0 or p < best_price):
                    best_price, best_source = p, src
            return keyword, best_price, best_source

        price_results = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch_best_price, kw): kw for kw in keywords}
            for f in as_completed(futures):
                kw, bp, bs = f.result()
                price_results[kw] = (bp, bs)

        items = []
        for keyword in keywords:
            ebay = ebay_cache.get(keyword, {})
            if not ebay or ebay["avg_usd"] == 0:
                continue
            buy_price, buy_source = price_results.get(keyword, (0, ""))
            if buy_price == 0:
                buy_price = int(ebay["avg_usd"] * usd_jpy * fallback_rate)
                buy_source = "相場推定"

            profit = calc_profit(buy_price, ebay["avg_usd"], usd_jpy=usd_jpy)
            sc = score_product(ebay["count"], ebay["competition"], profit["profit_rate"])
            enc = requests.utils.quote(keyword)
            source_fn = SOURCE_URL_MAP.get(buy_source)

            items.append({
                "type":         result_type,
                "genre":        genre,
                "keyword":      keyword,
                "avg_sold_usd": ebay["avg_usd"],
                "sold_count":   ebay["count"],
                "competition":  ebay["competition"],
                "sell_through": ebay["sell_through"],
                "buy_price":    buy_price,
                "buy_source":   buy_source,
                "profit":       profit["profit"],
                "profit_rate":  profit["profit_rate"],
                "score":        sc,
                "is_target":    profit["is_target"],
                "meets_all":    False,  # 後で設定
                "ebay_url":     ebay["url"],
                "ebay_sell_url": f"https://www.ebay.com/sch/i.html?_nkw={enc}&LH_BIN=1",
                "source_url":   source_fn(enc) if source_fn else "",
            })

        items.sort(key=lambda x: x["score"], reverse=True)
        for item in items:
            item["meets_all"] = meets_conditions(item)
        result[genre] = items[:5]

    return result


def research_stocked() -> dict:
    """有在庫リサーチ：ジャンル別TOP5"""
    return _research_genres(STOCKED_GENRES, STOCKED_SOURCES, "有在庫", 0.5)


def research_dropship() -> dict:
    """無在庫リサーチ：ジャンル別TOP5"""
    return _research_genres(DROPSHIP_GENRES, DROPSHIP_SOURCES, "無在庫", 0.6)
