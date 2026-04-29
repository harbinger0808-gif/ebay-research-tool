"""
商品手動追加ツール
仕入先URLと日本語情報を入力すると、Geminiが英語タイトル・説明文・コンディションを自動生成する

Usage:
    python add_item.py
"""
import warnings
warnings.filterwarnings('ignore')

import os
from dotenv import load_dotenv
load_dotenv()

from research import calc_profit
from sheets_client import add_candidate


def input_item():
    print("\n===== 商品追加 =====")
    print("（Ctrl+C で終了）\n")

    url        = input("仕入先URL: ").strip()
    jp_title   = input("商品名（日本語）: ").strip()
    jp_desc    = input("商品説明（日本語・コピペOK）: ").strip()

    try:
        buy_price = int(input("仕入価格（円）: ").strip())
    except ValueError:
        print("数字を入力してください")
        return

    try:
        ebay_price = float(input("eBay落札相場（USD）: ").strip())
    except ValueError:
        print("数字を入力してください")
        return

    # ── 利益計算 ──
    profit_result = calc_profit(buy_price, ebay_price, verbose=True)

    if not profit_result["is_target"]:
        skip = input("利益率が30%未満です。それでも追加しますか？ (y/n): ").strip().lower()
        if skip != "y":
            print("スキップしました")
            return

    # ── Gemini自動生成 ──
    gemini_result = None
    if os.getenv("GEMINI_API_KEY"):
        use_ai = input("\nGeminiでeBay出品情報を自動生成しますか？ (y/n): ").strip().lower()
        if use_ai == "y":
            print("Gemini処理中...")
            from gemini_client import generate_ebay_listing
            gemini_result = generate_ebay_listing(jp_title, jp_desc, buy_price, ebay_price)

            if "error" in gemini_result:
                print(f"Geminiエラー: {gemini_result['error']}")
                gemini_result = None
            else:
                print(f"\n--- Gemini生成結果 ---")
                print(f"eBayタイトル : {gemini_result.get('ebay_title', '')}")
                print(f"コンディション: {gemini_result.get('condition', '')}")
                print(f"判定根拠     : {gemini_result.get('condition_note', '')}")
                print(f"キーワード   : {', '.join(gemini_result.get('keywords', []))}")
                print(f"\neBay説明文:\n{gemini_result.get('ebay_description', '')}")

                if "出品非推奨" in str(gemini_result.get("condition_note", "")):
                    print("\n警告: Geminiが「出品非推奨」と判定しました。コンディション不良のリスクがあります。")
                    proceed = input("それでも追加しますか？ (y/n): ").strip().lower()
                    if proceed != "y":
                        print("スキップしました")
                        return

    # ── 最終コンディション決定 ──
    if gemini_result and "condition" in gemini_result:
        condition    = gemini_result["condition"]
        ebay_title   = gemini_result.get("ebay_title", jp_title)
        ebay_desc    = gemini_result.get("ebay_description", "")
    else:
        print("\nコンディション選択:")
        print("  1: Used - Like New（ほぼ新品）")
        print("  2: Used - Very Good（非常に良い）")
        print("  3: Used - Good（良い）★推奨最低ライン")
        cond_map = {"1": "Used - Like New", "2": "Used - Very Good", "3": "Used - Good"}
        condition  = cond_map.get(input("番号を入力: ").strip(), "Used - Good")
        ebay_title = jp_title
        ebay_desc  = ""

    # ── シートに追加 ──
    confirm = input("\nシートに追加しますか？ (y/n): ").strip().lower()
    if confirm == "y":
        add_candidate({
            "url":           url,
            "title":         ebay_title,
            "buy_price":     buy_price,
            "ebay_price_usd": ebay_price,
            "profit":        profit_result["profit"],
            "profit_rate":   profit_result["profit_rate"],
            "condition":     condition,
        })
        if ebay_desc:
            print(f"\neBay説明文（出品時にコピペ）:\n{ebay_desc}")
        print("\n追加完了！")
    else:
        print("キャンセルしました")


if __name__ == "__main__":
    try:
        while True:
            input_item()
            again = input("\n続けて追加しますか？ (y/n): ").strip().lower()
            if again != "y":
                break
    except KeyboardInterrupt:
        print("\n終了します")
