# Options decision system — working notes

Phase 1 options paper-trading system that informs real bullish/bearish trades.
Data is daily OHLCV via yfinance (HTTP fallback in `_price_history_direct`). No
live options chain — premiums are Black-Scholes priced with realized vol as an IV
proxy, so all dollar figures are **ballpark, not quotes**.

## Scanners

- `scan_watchlist.py` — swing entries, 35-45 DTE, IVR-gated (hard ceiling 70),
  buy dips / mean-reversion. `--direction bullish|bearish`.
- `scan_momentum.py` — weekly/day-trade mode, nearest-Friday weekly (~4 DTE),
  IVR ignored, buy strength (breakouts/breakdowns). `--dte`, `--direction`, `--top`.

## User's trading style — premium trading (frame ALL analysis this way)

The user **profits from premium appreciation and sells before expiry** — they do NOT
need the stock to cross the strike. Consequences that must shape every recommendation:

- **Calls at HIGH IVR are poor vehicles.** On a rally, IV compresses — vega works
  *against* you and eats the delta gain. A stock can go up while the call premium stays
  flat or falls. Prefer LOW IVR for call premium buys (room for vol to expand).
- **Puts benefit on a drop:** delta AND vega (vol expands as price falls) both work for
  you, so IVR level matters less for puts.
- **Harvest strength.** When a losing position bounces back into green and the greeks
  turn against further gains (high IVR + accelerating theta), TAKE the premium — don't
  hold hoping the bounce becomes a trend.
- **Theta:** ≤21 DTE bleeds fast; a flat day can cost several %/day on an OTM contract.
- **Earnings/IV timing:** the pre-earnings IV ramp only lifts options that EXPIRE AFTER
  the report. An option expiring *before* earnings gets zero earnings vega — never hold
  it for a catalyst it won't survive to see. To play earnings as a premium trader, buy a
  post-earnings expiry ~1-2 weeks out and SELL BEFORE the print (capture the ramp, dodge
  the crush).

## Paper-trading account (operating mode, as of 2026-06-30)

Claude runs a **paper book** to build a labeled track record. The user has paused
real-money trading until the record proves the decisions out. Rules:

- **Quality over quantity.** Take only setups Claude is genuinely confident in (the
  highest-conviction the system surfaces, with entry discipline satisfied). NEVER
  force trades to hit a target count — forcing corrupts the experiment and is itself
  a failure mode.
- **Entry discipline applies** (see momentum lesson): confirmed trigger only, flag
  mean-reversion risk, size tiny, 1σ strike on weeklies.
- **Honest pricing caveat.** No live chain — paper fills are Black-Scholes at the
  realized-vol proxy, with NO slippage or spread. A paper edge must be robust enough
  to survive real friction; paper validates direction/timing, not exact premium.
- **Book separation.** `recommendations.book` = `real` (user's actual fills) |
  `paper` (Claude's trades) | `watch` (pending-trigger candidates).
- **Exit rules.** Swing: +75% target / −50% stop / exit by 21 DTE. Momentum: +50%
  target / −50% stop / exit by 2 DTE or end of day. Every exit → a labeled outcome.
- **Track record:** `ResearchLog.paper_stats()` and `review_positions.py`.

## Parked — Moomoo OpenD real-data setup (user will configure later)

User trades on **moomoo (Singapore)** and wants real option chains/quotes to replace
the Black-Scholes-on-realized-vol estimates. Integration is **already built** and
committed; only local configuration remains, which the user will do when free.

- Code: `data_ingestion/moomoo_provider.py` (quote-context only, data-only — never
  handles the trade password) + `data_ingestion/factory.py` (`MARKET_DATA_PROVIDER=moomoo`).
- Steps + security notes: `docs/moomoo_setup.md`. OpenD runs on the USER's machine
  (127.0.0.1:11111); this cloud session cannot host it.
- **Unverified** — first local run with OpenD up must sanity-check `options_chain()`
  field names against the moomoo app; fix the mapping if the SDK version differs.
- Until then paper fills are model-priced; **the MAR paper trade is on hold pending a
  real quote** (or void it).

When the user asks about OpenD, resume from `docs/moomoo_setup.md`.

## Deployment & automation

- **GitHub Action** (`.github/workflows/daily-snapshot.yml`): morning momentum
  confirmation (~15:00 UTC / 10-11am ET) + post-close full snapshot (~21:15 UTC /
  4-5pm ET), weekdays. Appends to `data/scan_history.csv` — the durable dataset. Only
  fires from the DEFAULT branch.
- **Canonical branch = default** (`claude/planning-session-ipr02p`): the cron commits
  the dataset there. Pull before working so book + data stay in one place; the working
  branch is kept fast-forwarded to it.
- **VPS (the "proper" live setup, `deploy/vps_setup.md`):** run OpenD + scanners +
  system cron on a VPS for REAL data + Telegram push. `deploy/run_scans.sh` (morning|
  close) → scans, export, git backup, Telegram summary via `deploy/notify_telegram.py`
  (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`). Disable the GitHub Action once the VPS is
  live so estimate data doesn't overwrite real data.
- **This cloud session and the VPS communicate ONLY through the git repo** (async, no
  direct link). Telegram (from the VPS) is the user's real-time channel.
- **Phase 2 (calibration), the goal:** once ~20-30 closed paper outcomes exist, measure
  which features (entry_score, near_hl, IVR regime) actually predicted winners and
  re-weight from real results — first hypothesis: "entered at the level" vs "entered
  after break-and-hold."

## Output format (always)

Every recommendation must (1) state which **strategy** it belongs to — SWING
(`scan_watchlist`, 35-45 DTE, IVR-gated) or MOMENTUM (`scan_momentum`, weekly
~4 DTE) — (2) end with a short **summary**, and (3) give the **actual OCC option
contract code**, not just "BKNG C192.5".

OCC format: `{ROOT}{YYMMDD}{C|P}{strike×1000, zero-padded to 8 digits}`.
Example: BKNG $192.50 call expiring 2026-07-03 → `BKNG260703C00192500`.

## Session routine (always)

Before giving new analysis, **review the standing positions / prior
recommendations** and report how each has moved (fresh price, IVR, trend, DTE,
in/out of the money, thesis-still-valid?). Open positions to track are kept in
the `recommendations` / `positions` journal (see `journal/`). Never give new
picks without first re-checking the old ones.

**Book persistence.** The journal DB is gitignored and ephemeral; the durable book
is `data/recommendations.csv`. On session start, restore it:
`python -c "from journal.research_log import ResearchLog as R; R().import_recommendations()"`.
After ANY book change (open/close a trade), re-export and commit it:
`python -c "from journal.research_log import ResearchLog as R; R().export_recommendations()"`.
The daily cron must NOT export this file (its DB is fresh and would clobber the book).

**Timezone.** User is in Singapore (GMT+8). Precise timestamps (`scan_ts`, `entry_ts`,
`exit_ts`) are recorded in **SGT with an explicit `+08:00` offset**. Date-key fields
(`scan_date`, `created_date`, `exit_date`) stay on the **UTC calendar date** (≈ the US
trading date for US-session scans), so a post-close scan can read e.g. `scan_date=06-30`
with `scan_ts=07-01T06:47+08:00` — same US session, shown in local time.

## Trading lessons (do not repeat)

### A momentum-scan candidate is NOT an entry signal
The momentum scanner's "ignition score" ranks a name's **capacity to move**
(volatility, volume, recent momentum, proximity to a level) — it does **not** mean
"buy now." Presenting a ranked candidate as if it were an actionable entry is a
mistake that loses money.

**What went wrong (2026-06-29):** flagged AVGO P335 and NVDA P182.5 (4-DTE puts)
off the morning momentum scan. Both were puts surfaced *after* a down-move. Within
the same session both stocks ticked back up — entering either would have been
**buying a short-dated put into a bounce**, an immediate loss. AVGO's ignition had
already decayed 8→6 and its 5-day return improved -6%→-4.3% (momentum rolling off).

**The rule going forward:**
1. Separate **watch candidate** from **entry trigger fired**. Never blur them.
2. For a momentum/weekly trade, the entry trigger is the level actually breaking
   *with* momentum on the live tape (new 20d high/low taken out, not hovering near
   it). If the move hasn't confirmed, say "not yet — wait for the break," not "enter."
3. Chasing a directional short-dated option *after* an extended move in that
   direction = buying into likely mean reversion. Flag this risk explicitly.
4. Short-dated (≤7 DTE) options bleed theta hard and must be confirmed + exited
   fast + sized tiny. Default to the 1σ strike, never the 2σ "lotto" strike.

### Output discipline — never let a scan line become a verb
**What went wrong (2026-06-30):** off the momentum scan I wrote "the only two I'd
act on are BKNG and NUE… both broke their level with volume, neither is
over-extended." The user entered AAPL P270 ($31) and BKNG C192.5 ($40) on that
framing; both reverted to ~-75% at 3 DTE. Three errors in that one sentence:
- "broke their level" — they were *sitting at* the 20d high/low, not broken-and-held.
  "At the level + above-average volume" is NOT a confirmed trigger.
- "neither over-extended" — BKNG was RSI 70 going into a breakout (extended).
- AAPL (sitting at a low, oversold-leaning RSI, ignition only 4) was a mean-reversion
  *risk* but got grouped with the green-lit names.

**The rule going forward:**
5. Never use endorsing verbs — "I'd act on / recommend / cleanest entry / buy" — for
   anything off a daily scan. Daily-scan output gets ONE label: **watch — pending
   trigger.** An entry is only called an entry once the level breaks *and holds* on
   the live tape (or the 10am confirmation scan shows it holding).
6. "At the level + volume" ≠ "broke and held." State which one it actually is.
7. A short-dated put into an oversold low (or call into RSI ≥70) is flagged as
   mean-reversion risk explicitly — never listed as "confirmed."

### Violent-vol names price badly for weekly premium buying
Names with extreme realized vol (e.g. MRVL, WDC, SMCI, STX at RV 90-160%) make
weekly OTM strikes near-worthless coin flips and ATM strikes very expensive — poor
risk/reward for a premium buyer. Prefer a LEAPS structure for these, not 4-DTE.
