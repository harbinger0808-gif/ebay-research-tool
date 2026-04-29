"""
通知モジュール
売り切れ検出・エラー発生時にmacOSデスクトップ通知を送る
"""
import subprocess
import os
from datetime import datetime


def notify(title: str, message: str, sound: bool = True):
    """macOSデスクトップ通知を送る"""
    sound_opt = "default" if sound else ""
    script = f'''
    display notification "{message}" with title "{title}" sound name "{sound_opt}"
    '''
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    except Exception as e:
        print(f"通知送信失敗: {e}")


def notify_sold_out(item_title: str, platform: str):
    notify(
        title="売り切れ検出 — eBay取り下げ完了",
        message=f"{platform}: {item_title[:40]}"
    )


def notify_error(error_msg: str):
    notify(
        title="eBayツール エラー",
        message=error_msg[:80],
        sound=True
    )


def notify_daily_report(total: int, sold: int, profit_est: int):
    notify(
        title="eBayツール 日次レポート",
        message=f"監視中: {total}件 / 今日の取り下げ: {sold}件 / 推定利益: {profit_est:,}円"
    )


if __name__ == "__main__":
    notify("eBayツール", "通知テスト — 正常動作しています")
    print("通知を送信しました。画面右上を確認してください。")
