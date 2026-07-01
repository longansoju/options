#!/usr/bin/env bash
# Live scan runner for a VPS. Uses real OpenD data when MARKET_DATA_PROVIDER=moomoo.
# Called by cron:  run_scans.sh morning   |   run_scans.sh close
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
# activate venv + load .env (MARKET_DATA_PROVIDER, MOOMOO_*, TELEGRAM_*)
[ -f .venv/bin/activate ] && source .venv/bin/activate
[ -f .env ] && set -a && . ./.env && set +a

MODE="${1:-close}"
STAMP="$(date +'%Y-%m-%d %H:%M %Z')"

if [ "$MODE" = "morning" ]; then
    OUT="$(python scan_momentum.py --top 10)"
    echo "$OUT" > data/morning_momentum.txt
else
    python scan_watchlist.py --direction bullish || true
    python scan_watchlist.py --direction bearish || true
    OUT="$(python scan_momentum.py --top 10)"
    echo "$OUT" > data/momentum_close.txt
fi

python export_scan_history.py || true

# back up data to git (optional; harmless if no remote/changes)
git add data/ && git commit -q -m "VPS $MODE snapshot $(date -u +'%Y-%m-%d %H:%MZ')" && git push || true

# push a short summary to Telegram (skips cleanly if secrets unset)
printf '📊 %s scan — %s\n\n%s' "$MODE" "$STAMP" "$(printf '%s' "$OUT" | sed -n '1,16p')" \
    | python deploy/notify_telegram.py
