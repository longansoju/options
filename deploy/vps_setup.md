# Run the system live on a VPS (real data + Telegram push)

Moves the pipeline off the GitHub cloud container onto a VPS you control, so OpenD
runs 24/7 and the scanners use **real moomoo quotes** instead of estimates. The VPS
runs the plain Python scanners on a system cron; Claude Code is still invoked
on-demand for development/analysis — it does not need to run here continuously.

## What runs where
- **VPS (always on):** Moomoo OpenD + the Python scanners + system cron + Telegram push.
- **You (on-demand):** SSH in, or talk to Claude Code, to change/analyze things.

---

## Step by step

### 1. Get a VPS
Any Ubuntu 22.04+ box (1–2 vCPU, 2 GB RAM is plenty). SSH in.

### 2. Install prerequisites
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
```

### 3. Clone the repo + Python deps
```bash
git clone <your-repo-url> options && cd options
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt moomoo-api
```

### 4. Install & run Moomoo OpenD on the VPS
1. Download the **Linux** OpenD from moomoo (see docs/moomoo_setup.md link).
2. Start it and log in with your moomoo account. The **first login from a new
   server may trigger a phone/email verification code** — enter it when prompted.
3. Leave it listening on `127.0.0.1:11111`. Keep it alive with `tmux`/`screen` or a
   systemd service. **Security:** this is data-only; do not store your *trade-unlock*
   password anywhere or give it to any agent.

### 5. Configure environment
```bash
cp .env.example .env
nano .env      # set MARKET_DATA_PROVIDER=moomoo, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

### 6. Verify real data flows
```bash
source .venv/bin/activate && set -a && . ./.env && set +a
python -c "from data_ingestion.moomoo_provider import MoomooProvider as M; c=M().options_chain('AAPL'); print(c.spot_price, len(c.contracts), c.contracts[:2])"
```
Sanity-check the strikes/prices against the moomoo app. If a field name is off,
send me the error and I'll fix the mapping.

### 7. Schedule the scans (system cron)
`crontab -e` — times are **UTC** (set `CRON_TZ=UTC` or keep the VPS on UTC):
```
CRON_TZ=UTC
0 15 * * 1-5  /home/USER/options/deploy/run_scans.sh morning >> /home/USER/options/cron.log 2>&1
15 21 * * 1-5 /home/USER/options/deploy/run_scans.sh close   >> /home/USER/options/cron.log 2>&1
```
```bash
chmod +x deploy/run_scans.sh
```
`run_scans.sh` runs the scans, updates `scan_history.csv`, git-pushes a backup, and
sends a Telegram summary.

### 8. Turn off the GitHub Action
Once the VPS is live, disable the GitHub `Daily scan snapshot` workflow (Actions tab
→ ⋯ → Disable) so it doesn't double-run and overwrite real data with estimates.

---

## Notes
- The VPS disk is persistent, so the journal DB survives between runs (no more
  ephemeral-container caveat) — the CSVs remain the git-backed source of record.
- Telegram summary is best-effort; if the secrets are unset it just skips.
- To also run Claude Code on the VPS for on-box analysis, install its CLI separately —
  it's optional and unrelated to the data pipeline above.
