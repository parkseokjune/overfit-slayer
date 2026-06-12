"""알림 단일 진입점 (DESIGN_NEXT #5) — 채널은 환경변수로 활성화.

기본: results/notifications.log + stdout. TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID
설정 시 텔레그램 푸시 (코드 수정 0줄). 알림 실패가 매매를 막지 않도록 전부 무해화.
"""
import os
import time

from .backtest import RESULTS_DIR

LOG = RESULTS_DIR / "notifications.log"


def notify(level: str, msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {msg}"
    print(line, flush=True)
    try:
        RESULTS_DIR.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            import requests
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": f"[{level}] {msg}"}, timeout=10)
        except Exception:
            pass
