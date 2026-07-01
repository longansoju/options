#!/usr/bin/env python3
"""
Send a message to Telegram via the Bot API.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment. No-ops (exit 0)
if they aren't set, so it never breaks a scheduled run.

    echo "text" | python deploy/notify_telegram.py
    python deploy/notify_telegram.py "text"
"""
import os
import sys
import urllib.parse
import urllib.request


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    if not token or not chat:
        print("telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping")
        return
    text = (text or "(empty)")[:4000]
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
            print("telegram: sent", r.status)
    except Exception as e:
        print("telegram error:", e)


if __name__ == "__main__":
    main()
