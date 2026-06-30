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

### Violent-vol names price badly for weekly premium buying
Names with extreme realized vol (e.g. MRVL, WDC, SMCI, STX at RV 90-160%) make
weekly OTM strikes near-worthless coin flips and ATM strikes very expensive — poor
risk/reward for a premium buyer. Prefer a LEAPS structure for these, not 4-DTE.
