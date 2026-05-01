"""
eBayリサーチ・スコアリングモジュール
ジャンル別TOP5（有在庫4ジャンル・無在庫4ジャンル）
※ Finding API廃止済み → Browse API + スクレイピングで完全代替
"""
import os
import time
import base64
import requests
from typing import Optional
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
APP_ID = os.getenv("EBAY_APP_ID", "")

# スコアリング条件（Browse API専用・sold count不要）
MIN_PROFIT_RATE  = 30.0   # 利益率30%以上
MAX_COMPETITION  = 500    # 全世界競合500件以下（Browse APIは全世界なので緩め）
MIN_EBAY_PRICE   = 15.0   # eBay売値$15以上
MIN_JP_COUNT     = 3      # 日本セラー3件以上（需要確認）

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

def _kw_cache_get(keyword: str) -> Optional[dict]:
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
    "オーラルケア（消耗品）": [
        "kiseki no haburashi miracle toothbrush japan",
        "miracle toothbrush japan ultra fine bristle 3 pack",
        "KISS YOU ionic toothbrush japan",
        "ion toothbrush japan ionpa",
        "apagard premio toothpaste japan hydroxyapatite",
        "apagard nano hydroxyapatite whitening toothpaste japan",
        "GC tooth mousse recaldent japan",
        "lion systema toothbrush japan 10 pack",
        "lion dent EX systema toothbrush japan",
        "sunstar ora2 toothpaste japan stain clear",
        "ebisu premium toothbrush japan 7 line",
        "japanese whitening toothpaste hydroxyapatite bulk",
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
    "オーラルケア家電（無在庫）": [
        "panasonic doltz sonic toothbrush japan EW-DP37",
        "panasonic doltz electric toothbrush japan import",
        "panasonic EW-DP52 sonic toothbrush japan",
        "panasonic jet washer doltz EW-DJ55 japan",
        "panasonic water flosser oral irrigator japan",
        "panasonic EW-DJ65 cordless water flosser japan",
        "omron mediclean sonic toothbrush japan HT-B322",
        "omron oral irrigator water flosser japan",
    ],
    "カメラ・レンズ": [
        "fujinon vintage lens japan", "super takumar lens japan",
        "canon fd lens japan vintage", "minolta lens japan vintage",
        "japan camera strap leather handmade", "olympus zuiko lens japan",
    ],
}

# ===== 日本語キーワードマップ（仕入れサイト検索用）=====
# eBay検索用の英語キーワード → 日本の仕入れサイト用日本語キーワード
JP_KEYWORD_MAP = {
    # ── レトロゲーム ──
    "famicom dragon quest japan":               "ファミコン ドラゴンクエスト",
    "super famicom final fantasy japan":        "スーパーファミコン ファイナルファンタジー",
    "game boy pokemon japan cartridge":         "ゲームボーイ ポケモン",
    "sega saturn japan lot":                    "セガサターン",
    "pc engine japan rare":                     "PCエンジン",
    "famicom lot japan complete":               "ファミコン ソフト まとめ",
    "nintendo 64 japan game cartridge":         "Nintendo64 ゲームソフト",
    "gameboy advance japan limited":            "ゲームボーイアドバンス",

    # ── フィギュア・アニメグッズ ──
    "nendoroid japan exclusive limited":        "ねんどろいど 限定",
    "figma japan limited edition":              "figma 限定",
    "gundam model kit japan limited":           "ガンプラ 限定",
    "dragon ball z figure japan vintage":       "ドラゴンボール フィギュア",
    "one piece figure japan exclusive":         "ワンピース フィギュア",
    "evangelion figure japan limited":          "エヴァンゲリオン フィギュア",
    "sailor moon figure japan vintage":         "セーラームーン フィギュア",
    "demon slayer figure japan limited":        "鬼滅の刃 フィギュア",

    # ── 日本限定レゴ・玩具 ──
    "lego japan limited set exclusive":         "レゴ 日本限定",
    "lego ninjago japan limited":               "レゴ ニンジャゴー",
    "lego creator japan exclusive":             "レゴ クリエイター",
    "lego technic japan limited":               "レゴ テクニック",
    "pokemon toy japan limited exclusive":      "ポケモン おもちゃ 限定",
    "japan exclusive toy limited":              "日本限定 おもちゃ",
    "bandai kamen rider japan limited":         "バンダイ 仮面ライダー",
    "tomica japan limited diecast":             "トミカ 限定",

    # ── チェキカメラ ──
    "fujifilm instax mini japan limited":       "チェキ instax mini 限定",
    "fujifilm instax square japan":             "チェキ instax スクエア",
    "fujifilm instax wide japan limited":       "チェキ instax wide 限定",
    "instax mini liplay japan":                 "チェキ mini liplay",
    "fujifilm instax mini 99 japan":            "チェキ mini 99",
    "instax mini evo japan limited":            "チェキ evo 限定",

    # ── 消耗品（リピート買い）──
    "fujifilm instax mini film japan":          "チェキ フィルム ミニ",
    "instax square film japan":                 "チェキ フィルム スクエア",
    "japanese skincare mask sheet bulk":        "フェイスマスク スキンケア まとめ",
    "japan beauty serum collagen":              "美容液 コラーゲン",
    "japanese pet snack treat bulk":            "ペット おやつ まとめ",
    "japan dog treat freeze dried":             "犬 おやつ フリーズドライ",
    "japanese cat food premium bulk":           "猫 フード プレミアム",
    "japan dental care pet bulk":               "ペット デンタルケア",

    # ── Tシャツ・アパレル ──
    "uniqlo japan limited ut tshirt":           "ユニクロ UT 限定 Tシャツ",
    "japan anime tshirt limited edition":       "アニメ Tシャツ 限定",
    "pokemon center japan tshirt exclusive":    "ポケモンセンター Tシャツ",
    "dragon ball z japan shirt limited":        "ドラゴンボール シャツ 限定",
    "studio ghibli japan tshirt official":      "スタジオジブリ Tシャツ",
    "naruto japan limited shirt":               "ナルト シャツ 限定",

    # ── 古物・ヴィンテージ ──
    "japanese vintage kimono silk obi":         "着物 帯 シルク",
    "japan vintage tin toy showa":              "ブリキ おもちゃ 昭和",
    "japanese antique porcelain meiji":         "明治 陶磁器 アンティーク",
    "japan vintage whisky bottle unopened":     "ウイスキー 未開封",
    "japanese vintage camera film showa":       "フィルムカメラ 昭和",
    "japan vintage magazine anime rare":        "アニメ 雑誌 レア",
    "japanese vintage poster showa retro":      "昭和 ポスター レトロ",
    "japan vintage playing cards rare":         "トランプ カード レア",

    # ── 伝統工芸・職人品 ──
    "japanese magewappa bento box handmade":    "曲げわっぱ 弁当箱",
    "japanese lacquer box vintage":             "漆器 箱",
    "japanese pottery tea bowl handmade":       "陶器 茶碗",
    "japanese bamboo basket woven":             "竹 かご",
    "japanese kokeshi doll vintage":            "こけし 人形",
    "japanese cedar tray handmade":             "杉 トレー",
    "japanese indigo dyeing fabric":            "藍染め 布",
    "japanese washi paper handmade":            "和紙",

    # ── オーラルケア（消耗品）──
    "kiseki no haburashi miracle toothbrush japan":           "奇跡の歯ブラシ",
    "miracle toothbrush japan ultra fine bristle 3 pack":     "奇跡の歯ブラシ 3本",
    "KISS YOU ionic toothbrush japan":                        "KISS YOU イオン歯ブラシ",
    "ion toothbrush japan ionpa":                             "イオン歯ブラシ ionpa",
    "apagard premio toothpaste japan hydroxyapatite":         "アパガード プレミオ",
    "apagard nano hydroxyapatite whitening toothpaste japan": "アパガード ナノ",
    "GC tooth mousse recaldent japan":                        "GC トゥースムース リカルデント",
    "lion systema toothbrush japan 10 pack":                  "ライオン システマ 歯ブラシ 10本",
    "lion dent EX systema toothbrush japan":                  "ライオン デント EX システマ",
    "sunstar ora2 toothpaste japan stain clear":              "サンスター オーラツー ステインクリア",
    "ebisu premium toothbrush japan 7 line":                  "エビス プレミアムケア 歯ブラシ",
    "japanese whitening toothpaste hydroxyapatite bulk":      "ホワイトニング 歯磨き粉",

    # ── 美容家電（無在庫）──
    "panasonic face steamer japan nano":        "パナソニック スチーマー ナノケア",
    "hitachi face steamer japan":               "日立 スチーマー",
    "panasonic hair dryer japan nano":          "パナソニック ナノケア ドライヤー",
    "yamazen facial massager japan":            "山善 フェイシャルマッサージャー",
    "mtg refa carat japan face roller":         "MTG リファ カラット",
    "japan led face mask beauty":               "LED フェイスマスク 美顔器",
    "panasonic epilator japan ladies":          "パナソニック 脱毛器",
    "omron tens unit japan":                    "オムロン 低周波治療器",

    # ── ペット用品（無在庫）──
    "japan automatic cat feeder wifi":          "猫 自動給餌器 wifi",
    "japan dog water fountain filter":          "犬 自動給水器",
    "japanese cat tree tower premium":          "キャットタワー",
    "japan pet grooming glove":                 "ペット グルーミング グローブ",
    "japan interactive cat toy laser":          "猫 おもちゃ レーザー",
    "japanese dog carrier bag premium":         "犬 キャリーバッグ",

    # ── チェキカメラ（無在庫）──
    "fujifilm instax mini 12 japan":            "チェキ instax mini 12",
    "fujifilm instax mini 40 japan":            "チェキ instax mini 40",
    "fujifilm instax link wide japan":          "チェキ link wide",
    "fujifilm instax mini liplay japan":        "チェキ mini liplay",
    "instax mini hello kitty japan":            "チェキ ハローキティ",
    "instax square sq6 japan":                  "チェキ スクエア SQ6",

    # ── 健康器具・マッサージ ──
    "japan shiatsu neck massager":              "指圧 ネックマッサージャー",
    "japanese foot massager electric":          "電動 フットマッサージャー",
    "japan EMS face lift device":               "EMS フェイスリフト 美顔器",
    "japanese steam eye mask bulk":             "蒸気でホットアイマスク めぐりズム",
    "japan back stretcher lumbar":              "バックストレッチャー 腰",
    "omron blood pressure monitor japan":       "オムロン 血圧計",

    # ── オーラルケア家電（無在庫）──
    "panasonic doltz sonic toothbrush japan EW-DP37":    "パナソニック ドルツ EW-DP37",
    "panasonic doltz electric toothbrush japan import":  "パナソニック ドルツ 電動歯ブラシ",
    "panasonic EW-DP52 sonic toothbrush japan":          "パナソニック EW-DP52",
    "panasonic jet washer doltz EW-DJ55 japan":          "パナソニック ジェットウォッシャー EW-DJ55",
    "panasonic water flosser oral irrigator japan":      "パナソニック ジェットウォッシャー",
    "panasonic EW-DJ65 cordless water flosser japan":    "パナソニック EW-DJ65",
    "omron mediclean sonic toothbrush japan HT-B322":    "オムロン メディクリーン HT-B322",
    "omron oral irrigator water flosser japan":          "オムロン 口腔洗浄器",

    # ── カメラ・レンズ ──
    "fujinon vintage lens japan":               "フジノン レンズ",
    "super takumar lens japan":                 "スーパータクマー レンズ",
    "canon fd lens japan vintage":              "キヤノン FD レンズ",
    "minolta lens japan vintage":               "ミノルタ レンズ",
    "japan camera strap leather handmade":      "カメラストラップ レザー",
    "olympus zuiko lens japan":                 "オリンパス ズイコー レンズ",
}

def _jp_keyword(en_kw: str) -> str:
    """英語キーワードを日本の仕入れサイト用の日本語キーワードに変換"""
    return JP_KEYWORD_MAP.get(en_kw, en_kw)


STOCKED_SOURCES  = [
    "ヤフオク", "エコリング", "ハードオフ", "駿河屋",
    "ブックオフ", "セカンドストリート", "ゲオ", "じゃんぱら", "Amazon",
]
DROPSHIP_SOURCES = [
    "Amazon", "キタムラ", "ヨドバシ", "ビックカメラ",
]

SOURCE_URL_MAP = {
    "ヤフオク":           lambda e: f"https://auctions.yahoo.co.jp/search/search?p={e}&istatus=1&s1=cbids&o1=a",
    "エコリング":         lambda e: f"https://www.eco-ring.com/products/search?keyword={e}",
    "ハードオフ":         lambda e: f"https://hardoff.co.jp/search/?q={e}&sort=price_asc",
    "駿河屋":             lambda e: f"https://www.suruga-ya.jp/search?category=0&search_word={e}&soldout=1&order=price_asc",
    "Amazon":             lambda e: f"https://www.amazon.co.jp/s?k={e}&sort=price-asc-rank",
    "キタムラ":           lambda e: f"https://www.kitamura.jp/search/index.php?q={e}&sort=price_asc",
    "ヨドバシ":           lambda e: f"https://www.yodobashi.com/?word={e}",
    "ブックオフ":         lambda e: f"https://shopping.bookoff.co.jp/search/keyword/{e}?sort=price&order=asc",
    "セカンドストリート": lambda e: f"https://www.2ndstreet.jp/search/results/?search_word={e}&sort=price_asc",
    "ゲオ":               lambda e: f"https://ec.geo-online.co.jp/shop/search?search_text={e}&sort=price_asc",
    "ビックカメラ":       lambda e: f"https://www.biccamera.com/bc/category/?q={e}&sort=cheap",
    "じゃんぱら":         lambda e: f"https://www.janpara.co.jp/sale/search/?KEYWORDS={e}&SORT=4",
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



def get_ebay_data(keyword: str) -> dict:
    """
    Browse APIで現在出品データを取得（Finding API廃止・スクレイピング403のため）。
    - avg_usd    : 日本セラー上位50件の平均価格
    - jp_count   : 日本セラーの出品数（需要の代理指標）
    - competition: 全世界の出品総数
    - sell_through: jp_count / competition * 100（市場占有率）
    - url        : 代表商品URL
    """
    cached = _kw_cache_get(keyword)
    if cached:
        return cached

    token = get_ebay_token()
    if not token:
        return {"avg_usd": 0, "count": 0, "competition": 9999,
                "sell_through": 0.0, "url": "", "source": "browse"}
    try:
        # ① 日本セラー出品（価格・URL取得）
        res_jp = requests.get(
            BROWSE_API_URL,
            params={
                "q": keyword, "limit": 50, "sort": "bestMatch",
                "filter": "itemLocationCountry:JP,buyingOptions:{FIXED_PRICE}",
            },
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            timeout=8,
        )
        jp_data   = res_jp.json()
        jp_total  = jp_data.get("total", 0)
        items     = jp_data.get("itemSummaries", [])
        prices, top_url = [], ""
        for item in items:
            val = item.get("price", {}).get("value")
            if val:
                try:
                    p = float(val)
                    if 0.5 <= p <= 10000:
                        prices.append(p)
                        if not top_url:
                            top_url = item.get("itemWebUrl", "")
                except Exception:
                    pass
        avg = round(sum(prices) / len(prices), 2) if prices else 0

        # ② 全世界の競合数
        res_all = requests.get(
            BROWSE_API_URL,
            params={"q": keyword, "limit": 1,
                    "filter": "buyingOptions:{FIXED_PRICE}"},
            headers={**HEADERS, "Authorization": f"Bearer {token}"},
            timeout=8,
        )
        competition = res_all.json().get("total", 9999)

        # 日本セラー比率（市場占有率）を sell_through の代理指標に
        sell_through = round(jp_total / max(competition, 1) * 100, 1)

        enc = requests.utils.quote(keyword)
        result = {
            "avg_usd":      avg,
            "count":        jp_total,   # 日本セラー出品数（需要代理）
            "competition":  competition,
            "sell_through": sell_through,
            "url":          top_url or f"https://www.ebay.com/sch/i.html?_nkw={enc}&LH_BIN=1",
            "source":       "browse",
        }
        print(f"  [Browse] {keyword[:30]}... → avg${avg:.2f} / JP{jp_total}件 / 全{competition}件")
        if result["avg_usd"] > 0:
            _kw_cache_set(keyword, result)
        return result
    except Exception as e:
        print(f"  [Browse失敗] {keyword}: {e}")
        return {"avg_usd": 0, "count": 0, "competition": 9999,
                "sell_through": 0.0, "url": "", "source": "browse"}


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

def get_bookoff_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://shopping.bookoff.co.jp/search/keyword/{enc}?sort=price&order=asc"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".product-price, [class*='price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_2ndstreet_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.2ndstreet.jp/search/results/?search_word={enc}&sort=price_asc"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select("[class*='price'], [class*='Price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_geo_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://ec.geo-online.co.jp/shop/search?search_text={enc}&sort=price_asc"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select("[class*='price'], [class*='Price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_biccamera_price(keyword: str) -> int:
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.biccamera.com/bc/category/?q={enc}&sort=cheap"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".bc-price, [class*='price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 1000000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_janpara_price(keyword: str) -> int:
    """じゃんぱら（中古PC・家電専門）"""
    try:
        enc = requests.utils.quote(keyword)
        url = f"https://www.janpara.co.jp/sale/search/?KEYWORDS={enc}&SORT=4"
        soup = BeautifulSoup(requests.get(url, headers=HEADERS, timeout=5).text, "html.parser")
        prices = []
        for el in soup.select(".item_price, [class*='price']"):
            digits = "".join(filter(str.isdigit, el.get_text(strip=True).replace(",", "")))
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))
        return sorted(prices)[0] if prices else 0
    except Exception:
        return 0

def get_mercari_link_price(keyword: str) -> int:
    """メルカリ（リンクのみ・価格取得不可のため0返却）"""
    return 0

PRICE_FN_MAP = {
    "ヤフオク":       get_yahooauction_price,
    "エコリング":     get_ecoring_price,
    "ハードオフ":     get_hardoff_price,
    "駿河屋":         get_surugaya_price,
    "Amazon":         get_amazon_price,
    "キタムラ":       get_kitamura_price,
    "ヨドバシ":       get_yodobashi_price,
    "ブックオフ":     get_bookoff_price,
    "セカンドストリート": get_2ndstreet_price,
    "ゲオ":           get_geo_price,
    "ビックカメラ":   get_biccamera_price,
    "じゃんぱら":     get_janpara_price,
}


# ===== スコアリング =====

def score_product(jp_count: int, competition: int, profit_rate: float, avg_price: float) -> float:
    """利益率 × 価格 ÷ 競合数 でスコアリング（売れ筋 × 高単価 × ブルーオーシャンを優遇）"""
    return round((max(profit_rate, 0) * avg_price * max(jp_count, 1)) / max(competition, 1), 3)


def meets_conditions(r: dict) -> bool:
    return (
        r["profit_rate"]  >= MIN_PROFIT_RATE and
        r["competition"]  <= MAX_COMPETITION and
        r["avg_sold_usd"] >= MIN_EBAY_PRICE and
        r["sold_count"]   >= MIN_JP_COUNT
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
        # 日本の仕入れサイトには日本語キーワードを使用
        def fetch_best_price(keyword):
            jp_kw = _jp_keyword(keyword)
            best_price, best_source = 0, ""
            for src in source_names:
                p = PRICE_FN_MAP[src](jp_kw)
                if p > 0 and (best_price == 0 or p < best_price):
                    best_price, best_source = p, src
            return keyword, best_price, best_source, jp_kw

        price_results = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch_best_price, kw): kw for kw in keywords}
            for f in as_completed(futures):
                kw, bp, bs, jp_kw = f.result()
                price_results[kw] = (bp, bs, jp_kw)

        items = []
        for keyword in keywords:
            ebay = ebay_cache.get(keyword, {})
            if not ebay or ebay["avg_usd"] == 0:
                continue
            buy_price, buy_source, jp_kw = price_results.get(keyword, (0, "", _jp_keyword(keyword)))
            if buy_price == 0:
                buy_price = int(ebay["avg_usd"] * usd_jpy * fallback_rate)
                buy_source = "相場推定"

            profit = calc_profit(buy_price, ebay["avg_usd"], usd_jpy=usd_jpy)
            sc = score_product(ebay["count"], ebay["competition"], profit["profit_rate"], ebay["avg_usd"])
            enc_en = requests.utils.quote(keyword)
            enc_jp = requests.utils.quote(jp_kw)
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
                "ebay_sell_url": f"https://www.ebay.com/sch/i.html?_nkw={enc_en}&LH_BIN=1",
                # 仕入れサイトURLは日本語キーワードで生成
                "source_url":   source_fn(enc_jp) if source_fn else "",
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
