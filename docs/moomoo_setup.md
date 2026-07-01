# Real option data via Moomoo OpenD

The scanners default to yfinance + Black-Scholes estimates (works anywhere, but the
premiums are modeled, not quoted). To use **real option chains/quotes**, run Moomoo
OpenD on your own machine and point the system at it.

## Why it must run on your machine
OpenD is a local gateway tied to *your* moomoo login (SG account, 2FA). Data is
encrypted and transmitted locally — no third party. Claude's ephemeral cloud session
cannot host your authenticated gateway, so the live-data workflow runs where OpenD
runs. **Security:** the trade-unlock password is entered manually in OpenD and is
never shared with or auto-filled by any AI agent. This integration uses the **quote
context only** (market data) — no automated order placement.

## One-time setup (your machine)
1. **Install + run OpenD.** Follow moomoo's one-click steps:
   <https://openapi.moomoo.com/moomoo-api-doc/en/intro/ai.html>
   Log in, leave it listening on `127.0.0.1:11111`.
2. **(Optional) install the moomoo Claude skills** for local Claude Code use:
   download `opend-skills.zip`, extract, copy into `~/.claude/skills/` (global) or
   `<repo>/.claude/skills/` (project). Verifies as `install-moomoo-opend` + `moomooapi`.
3. **Install the SDK:** `pip install moomoo-api`

## Point the scanners at moomoo
```bash
export MARKET_DATA_PROVIDER=moomoo      # default is yfinance
export MOOMOO_OPEND_HOST=127.0.0.1      # defaults shown
export MOOMOO_OPEND_PORT=11111
export MOOMOO_MARKET=US                 # underlying market prefix (US.AAPL …)

python scan_momentum.py                 # now uses real chains/quotes
python scan_watchlist.py --direction bullish
```
Unset the variable (or leave it) to fall back to yfinance.

## Status
`data_ingestion/moomoo_provider.py` is written against moomoo-api v10.x but **not yet
verified end-to-end** (needs OpenD running). First run it locally with OpenD up and
sanity-check one option chain (`options_chain("AAPL")`) against the moomoo app before
trusting paper-trade fills. Report any field-name mismatches and I'll fix the mapping.
