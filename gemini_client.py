"""
Gemini連携モジュール
日本語の仕入れ商品情報 → eBay英語タイトル・説明文・コンディション を自動生成
"""
import os
import warnings
warnings.filterwarnings('ignore')

from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai

def _get_model():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が .env に設定されていません")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.0-flash-lite")


def generate_ebay_listing(
    japanese_title: str,
    japanese_description: str,
    buy_price_jpy: int,
    ebay_price_usd: float,
) -> dict:
    """
    日本語の商品情報からeBay出品情報を丸ごと生成する

    戻り値: {
        "ebay_title": str,         # eBayタイトル（80文字以内）
        "ebay_description": str,   # eBay商品説明（HTML）
        "condition": str,          # Used - Like New / Very Good / Good
        "condition_note": str,     # コンディション判定の根拠
        "keywords": [str],         # SEOキーワード候補
    }
    """
    model = _get_model()

    prompt = f"""
あなたはeBay出品の専門家です。以下の日本語の中古品情報を分析して、
eBayで売れる英語の出品情報を生成してください。

【仕入れ元情報（日本語）】
商品名: {japanese_title}
説明文: {japanese_description}
仕入価格: {buy_price_jpy:,}円
想定eBay価格: ${ebay_price_usd}

【出力形式】必ず以下のJSON形式で返してください:
{{
  "ebay_title": "eBayタイトル（英語・80文字以内・ブランド名/モデル/状態を含む）",
  "ebay_description": "eBay商品説明（英語・HTMLタグ使用可・傷や汚れを正直に記載）",
  "condition": "Used - Like New または Used - Very Good または Used - Good のいずれか",
  "condition_note": "コンディション判定の根拠（日本語で簡潔に）",
  "keywords": ["SEOキーワード1", "キーワード2", "キーワード3"]
}}

【重要ルール】
- コンディションは「Used - Good」以上のみ対象。それ以下なら condition_note に「出品非推奨」と記載
- 傷・汚れは必ず英語説明文に正直に記載すること（eBayのNot as described対策）
- タイトルにはブランド名・モデル名・色・素材を優先的に含める
- 説明文は箇条書きを使い、バイヤーが安心できる内容にする
"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()

        # JSON部分を抽出
        import json, re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"error": "JSON解析失敗", "raw": text}
    except Exception as e:
        return {"error": str(e)}


def judge_condition_only(japanese_description: str) -> str:
    """
    日本語の説明文からeBayコンディションだけを素早く判定する
    """
    model = _get_model()
    prompt = f"""
以下の日本語の中古品説明文を読んで、eBayのコンディション区分を判定してください。

説明文: {japanese_description}

以下の4択から1つだけ答えてください:
- Used - Like New（ほぼ未使用、傷なし）
- Used - Very Good（使用感わずか、小さな傷のみ）
- Used - Good（使用感あり、目立つ傷や汚れあり）
- 出品非推奨（状態が悪すぎてeBayでのクレームリスクが高い）

判定結果のみ1行で答えてください。
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"判定エラー: {e}"


def translate_to_english(japanese_text: str) -> str:
    """シンプルな日英翻訳"""
    model = _get_model()
    prompt = f"以下を自然な英語に翻訳してください（eBay出品用）:\n{japanese_text}"
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"翻訳エラー: {e}"


if __name__ == "__main__":
    # 動作テスト
    print("===== Gemini連携テスト =====\n")

    test_title = "ルイヴィトン モノグラム ポルトフォイユ・サラ 長財布 M62235"
    test_desc  = "購入から3年使用。全体的に使用感あり。内側に少し汚れあり。ファスナーは問題なく動作します。カード入れ8箇所。外側角に擦れあり。"

    print(f"商品名: {test_title}")
    print(f"説明文: {test_desc}\n")
    print("Gemini処理中...\n")

    result = generate_ebay_listing(
        japanese_title=test_title,
        japanese_description=test_desc,
        buy_price_jpy=8000,
        ebay_price_usd=120.0,
    )

    if "error" in result:
        print(f"エラー: {result['error']}")
    else:
        print(f"eBayタイトル:\n  {result.get('ebay_title', '')}\n")
        print(f"コンディション: {result.get('condition', '')}")
        print(f"判定根拠: {result.get('condition_note', '')}\n")
        print(f"SEOキーワード: {', '.join(result.get('keywords', []))}\n")
        print(f"eBay説明文:\n{result.get('ebay_description', '')}")

    print("\n===== テスト完了 =====")
