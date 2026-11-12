# Options decision system — working notes

Phase 1 options paper-trading system that informs real bullish/bearish trades.
Data is daily OHLCV via yfinance (HTTP fallback in `_price_history_direct`). **From
2026-11-04 the live engines fill at REAL Yahoo option quotes** (ask in, bid out, ~15 min
delayed; `analysis/option_quotes.py`, see "REAL FILLS" below). Backtests and any row
flagged `price_source=model (no quote)` are still Black-Scholes at realized vol — those
dollar figures are **ballpark, not quotes**.

## Scanners

- `scan_watchlist.py` — swing entries, 35-45 DTE, IVR-gated (hard ceiling 70),
  buy dips / mean-reversion. `--direction bullish|bearish`.
- `scan_momentum.py` — weekly/day-trade mode, nearest-Friday weekly (~4 DTE),
  IVR ignored, buy strength (breakouts/breakdowns). `--dte`, `--direction`, `--top`.
- `scan_events.py` — event & volatility radar (`analysis/event_radar.py`). Forecasts
  WHEN a big move is likely, never which way. `--mode open` pre-market (09:15-09:28
  ET = 21:15-21:28 SGT): P(0.3σ weekly call / put touches +50% in the first hour).
  `--mode close`: P(next open gaps > 1 gap-sd up / down) + FOMC-night flag.
  `--refit` re-fits (weekly is plenty). Output is always "watch — volatility radar".
  See the lesson "Timing is forecastable, direction is not".

**Scan scope (as of 2026-07-16):** for interactive "market analysis" / breadth-scan
requests, default to **`--focus`** on both scanners — scans only
`config.FOCUS_AI_SEMI_IT` (21 tickers: AI compute, semiconductor complex, mega-cap
IT) instead of the full ~47-name watchlist. Faster, fewer yfinance calls, and
matches the user's stated sector interest. Do NOT add `--focus` to the automated
GitHub Action cron — it must keep scanning the full watchlist so `scan_history.csv`
stays a complete dataset for Phase 2 calibration. `--focus` is for on-demand chat
analysis only.

**Earnings-calendar check — mandatory before EVERY new entry, no exceptions.**
This has already broken two positions: SMCI was opened without checking (caught by
the user after the fact — earnings landed inside the holding window); AMZN was
opened hours before its Q2 report and the thesis was destroyed overnight (a
blowout AWS beat moved the stock 22%+ away from a bearish strike). Before logging
ANY `add_recommendation` call: check whether the underlying reports earnings
before the position's expiry. If yes — either skip the entry, or explicitly plan
to exit before the print (see the existing earnings/IV-timing rule below) and say
so in the thesis. Never let this be a reactive catch; check it every time,
proactively, as part of building the entry.

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
  mean-reversion risk, size tiny, **0.3-0.6σ strike** (NOT 1σ — see the strike-
  distance lesson; >1σ is 0-for-10 in the book).
- **Honest pricing caveat.** Until 2026-11-03 every paper fill was Black-Scholes at the
  realized-vol proxy with NO slippage or spread. From 11-04 the engines buy at the real
  (delayed) ask and sell at the real bid; only no-quote rows are model-priced, and are
  flagged. Rows that span the change (model entry, real exit) are tagged so — their %
  P&L overstates real-world results. Intraday stops/targets are still checked on a model
  path (at the entry quote's bid IV), so a fast resting-limit fill is plausible, not proven.
- **Book separation.** `recommendations.book` = `real` (user's actual fills) |
  `paper` (Claude's trades) | `watch` (pending-trigger candidates).
- **Exit rules — CHANGED 2026-10-15 (user: "adopt it, let's see how it works").**
  Swing + momentum: **−50% stop; once the premium has been +50%, TRAIL — exit when
  its value falls 30% from the peak value** (peak +100% → out at +40%); swing still
  exits by 21 DTE, momentum by 2 DTE. The fixed +50% first-touch target and the
  day-2 red cut are retired for these two strategies (the grid was tested without a
  day-2 cut, and that cut is exactly what kills slow multi-day flips). Evidence:
  "The exit is the issue" lesson below. `analysis/harvest.py:trailing_exit`,
  `config.TRAIL_*`. On the broker: a resting −50% stop at entry, switched to a
  trailing stop once +50% prints. Day-trade exits are unchanged (±20/120m/15:45).
  Review the live result at n≥10 trailing exits. Previous rule, for the record:
  +50% target on FIRST TOUCH / −50% stop / cut on day 2 if red (2026-09-14).
  Every exit → a labeled outcome. The +50% target replaced swing's old +75%:
  backtested, +75% gives back more than it captures (−29.1% vs −24.6% avg).
  Because the user is GMT+8 and the US session runs overnight, the harvest must
  be a **resting limit order**, not a discretionary decision made in real time.
- **Track record:** `ResearchLog.paper_stats()` and `review_positions.py`.
- **Autonomous paper mode (authorized by the user 2026-09-29).** During monitored
  sessions Claude takes paper trades on its OWN rules without asking — confirmed
  trigger (20d level held ≥10 consecutive 1m closes, right side of VWAP, day relvol
  ≥1.0x same-clock-time), all gates pass (whipsaw, counter-trend, RSI, earnings before
  expiry), nearest-Friday weekly at 0.3-0.6σ, 1 contract, model premium ≤ $1,000 (the
  user's budget, so the paper book stays relevant to what they can trade). Exits are
  the standard rules above. A live engine emits PAPER ENTRY / PAPER EXIT signals;
  every book write still follows the Session-routine protocol. Still never forced:
  a quiet tape produces no trades, and that is the correct outcome.
- **Learning loop.** Every live forecast is scored against the realized outcome and
  logged (next-5m range/direction, session-close estimates). Measured so far: 5-min
  DIRECTION is a coin flip (OOS hit 51.0-51.2% on 31k bars; adding SMH lead-lag and
  relative strength changed nothing, AUC 0.512); the 5-min RANGE is forecastable
  (raw band covered 72.7% vs 68% target → scaled 0.91, then self-calibrates live).
  Findings that hold up get written into the lessons below; ones that don't, don't.

- **Day-trade practice mode (requested by the user 2026-10-05).** Paper only,
  `strategy=daytrade`, flat by the close, kept separate from swing/momentum stats.
  Engine: `daytrade_engine.py` (scratchpad). Rule: 30-min opening-range break held
  ≥10 consecutive 1m closes (10:00-15:00 ET), right side of VWAP, relvol ≥1.0x
  same-clock, all gates (whipsaw, counter-trend, RSI, earnings before expiry);
  vehicle = NEXT week's Friday at 0.3-0.6σ, 1 contract, ≤ $1,000; exits **+30% /
  −30% / 15:45 ET**; max 3 entries per day, one per name. **The backtest says this
  loses** (60 sessions, 21 names, 5m bars, BS at RV30):

  | variant (gated) | n | win | avg | after 4% spread |
  |---|---|---|---|---|
  | 20d break, weekly, ±50% | 56 | 29% | −16.1% | −20.1% |
  | OR break, weekly, ±50% | 127 | 26% | −16.4% | −20.4% |
  | OR break, weekly, ±30% | 127 | 34% | −7.7% | −11.7% |
  | **OR break, next-week expiry, ±30% (chosen)** | 127 | 31% | **−6.9%** | −10.9% |

  Two separate causes. (1) **The underlying has no continuation edge intraday:**
  entry→15:45 in the break direction averaged −0.18% (OR, t −1.2) and −0.25% (20d,
  t −0.9); breakouts mildly mean-revert into the close, not significantly. (2)
  **Theta:** the same entries priced on the following week's expiry lose roughly
  half as much (−8.4% vs −16.4% at ±50%). Do NOT flip to a "fade the breakout" rule
  on that t-stat after testing a dozen variants — that is data-mining. This mode is
  a forward test to collect labelled intraday trades and to compare against the real
  moomoo chain later, not a claimed edge. Re-evaluate at n≥30 day trades.

  **Pen-test 2026-10-06 (`research/pentest_dt.py`) — rules changed.** 31 one-at-a-
  time variants + gate ablations, sessions split 20 in-sample / 20 out-of-sample
  (from 09-08), all after a 4% spread. ADOPT only if better in BOTH halves.
  Baseline −13.3% IS / −9.6% OOS. Passed: closer strike (0.0σ −10.8/−7.2), 2-week
  expiry (−10.3/−6.8), ±20% exits (−8.3/−7.6). **Gates confirmed on intraday data:**
  removing whipsaw (−14.2/−10.7), counter-trend (−12.9/−12.2) or all gates
  (−12.6/−12.0) is worse OOS; 5d counter-trend no better than 3d; RSI gate neutral.
  No entry filter helped (hold length, OR length, relvol, VWAP, entry window).
  Combined (0-0.4σ, 2-week expiry, ±20%, max hold 120m): −6.3% IS / −5.7% OOS,
  **−1.9% before spread.** **New day-trade rules:** strike nearest 0.2σ within
  0-0.4σ and ≤ $1,000; Friday two weeks out; **+20% / −20% / 120-min max hold /
  15:45**; gates unchanged.

  **What the pen-test actually says — read before claiming progress:** every
  improvement came from REDUCING EXPOSURE (less theta, shorter holds, smaller
  targets), and the loss shrinks toward −spread as exposure shrinks (60-min max hold:
  −1.1% before spread). That is the signature of NO ENTRY EDGE: the best rule is the
  one that holds least. Losing less is not winning. Also: a 12:30 clock time-stop
  with entries until 15:00 looked good only because late entries were closed one bar
  later — a test artifact; caught and replaced with a max-hold rule. Check every
  "improvement" for this kind of leak before adopting it.

  **Universe expansion (user request 2026-10-06: "slowly").** Day-trade universe =
  focus 21 + `config.DAYTRADE_EXPANSION`, added in batches of ~5. Admission is
  STRUCTURAL only: 20d avg dollar volume ≥ $1.5B, a 0-0.4σ two-week strike fits
  $1,000, prefer sectors outside AI/semis (10-06 showed three entries in 11 minutes
  that were one correlated tech bet). Never admit or drop a name on its own backtest
  P&L — ~5 trades per name is noise. Expansion names need a verified date in
  `config.DAYTRADE_EARNINGS` or they are not traded. Batch 1 (10-06): GOOGL, PLTR,
  JPM, XOM, V. Next batch only after batch 1 has traded for a week without data or
  gate problems. Candidates screened and waiting: QCOM, NFLX, KLAC, MA, UBER, AXP.
  Failed the budget screen (2-week 0.2σ call > $1,000): TSLA, AMD, AMAT, LRCX, LLY,
  GS, CAT, COIN, ARM, CEG.
  **Ambiguous-date rule (2026-10-28, VRT):** config had VRT 10-21 ("10-21 or 10-28", took the earlier).
  10-21 passed with no report, nobody re-checked, and on 10-28 — the real report day (BMO, +16% gap,
  4.3x volume) — the engine fired a VRT call that the report-day block should have stopped. VOIDED
  before booking (rule fails on clean data). When the earlier of two candidate dates passes without a
  print, re-verify THAT DAY and switch to the later date — same failure as XOM 10-09.
  Bug fixed the same day: the earnings gate blocked any date ≤ expiry, including
  dates already PAST (JPM would have stayed blocked after its 10-13 report). Now
  blocks only `today ≤ earnings ≤ expiry`.

  **Daily cap removed (user decision 2026-10-07): unlimited day trades**, still one
  per name per day, $1,000 max premium each. The old 3/day cap was never tested;
  the uncapped backtest averaged ~3 trades/session, so the cap only bound on busy
  one-direction days (10-06: three correlated tech calls in 11 minutes). Watch for:
  total open premium on busy days, and several entries that are really one sector
  bet. Report daily open-premium exposure in every end-of-day summary.

  **Stale-signal rule (2026-10-07, late start at 10:55 ET):** a break that
  confirmed more than ~10 minutes before the engine sees it (held > 20 consecutive
  1m closes) is reported as MISSED and not traded. The backtest enters AT
  confirmation; 10-05's late entries (VRT 28m, AMZN 51m after) were the worst
  trades. Start the engine before 09:30 ET (21:30 SGT) to avoid missing the morning.
  **Extended 2026-11-04:** the engine only checked breaks it had NOT seen (late start).
  A break it saw while both slots were full slipped through when a slot freed — SMCI put
  entered 14 min after confirmation (−13%), then TSM 39 min after (voided before
  booking). Now ANY break held > 20 closes is MISSED, whatever the reason.
  **Corrected 2026-11-06:** "held > 20 closes" over-blocked — GOOGL was marked stale at "held 29m" although its
  volume/VWAP conditions only confirmed later, the moment the backtest would enter. Age now runs from the first minute
  ALL conditions held (break ≥ 10 closes + VWAP side + relvol ≥ 1.0); MISSED if that was > 10 min ago (slots full),
  or, for a break first seen already > 20 closes old while the engine was not watching, as before. A failed break
  (price back inside the range) resets it, so a later re-break is a fresh signal.

  **Volume data-quality guard (2026-10-07):** NVDA printed 242M shares by 11:34 ET
  (6.2x same-clock) — 40-65M per 15 min from 10:15 — on a ~1% day range with no
  matching news (SpaceX chip-financing talk, ATH the day before; nothing intraday).
  Either a feed error or unexplained block flow. A breakout "confirmed" by that
  volume is not confirmed. Rule: relvol ≥ 4x on a day range < 1.5% → reject as
  `volume suspect` until explained.
  **Widened to range < 2.0% the same day (GOOGL):** the engine fired a GOOGL call at
  13:47 ET on "4.52x" relvol, but the volume was one 31M-share burst at 11:30-12:00
  (48% of the day's 65M) on a 0.6% move, while the actual breakout bars traded
  ~0.7M per 30 min — i.e. the break itself was on THIN volume. Day range 1.52%, just
  past the 1.5% line. Voided before booking (not in the book); the news (Waymo
  debt raise, Unity partnership, lawsuits) does not explain a one-bar burst.
  Same feed pattern as NVDA that morning — suspect the data, not the market.
  **Post-open burst cap (2026-10-09):** the bursts are common, not rare — single
  1m bars of 1.5-25M shares appeared after the open on NVDA, AMZN, V and MSFT the
  same morning (NVDA 25.0M at 10:51 vs a 0.22M median). Relvol now caps every bar
  after 09:35 at 10x that day's post-open median 1m volume; the 09:30-09:35 opening
  auction is left untouched (it is real volume and is in the 20-session baseline).
  Lesson from applying it: an NVDA put was voided on suspicion, then RESTORED when
  the capped relvol (1.02x) still met the rule — voiding a signal needs the rule to
  fail on clean data, not just suspicious-looking data.

  **Debit spreads for over-budget names — tested 2026-10-07, REJECTED.** Question:
  MU (and other names where no 0-0.4σ two-week single fits $1,000) — trade a debit
  spread instead? `research/spread_bt.py`, same v2 rules, 60 sessions:

  | vehicle | friction | n | win | avg after friction | before |
  |---|---|---|---|---|---|
  | single, ≤ $1,000 (current) | 4% | 57 | 30% | **−5.4%** | −1.4% |
  | spread, all names | 6% | 124 | 19% | −7.8% | −1.8% |
  | spread, only over-budget names | 6% | 67 | 15% | −8.2% | −2.2% |
  | same at 8% (two legs, wider opening spreads) | 8% | 67 | 12% | −10.2% | −2.2% |

  Same pre-friction result, but a spread pays two bid-ask spreads and moves too
  slowly to reach ±20% inside a 120-minute hold (12-19% win). **MU stays out of the
  day-trade book under the $1,000 budget.** Raising the budget is the user's call,
  not a rule change. Scheduled routine `trig_01PSuTJLW2EMoWSkDA6tmQqz` (moved to the
  11-04 session; the old `trig_01UPqtkR5VGDTgz9Ebo6Y5aa` is disabled, not deleted) starts
  the engine at 09:15 ET weekdays (CRON_TZ America/New_York, so it follows US DST:
  22:15 SGT since US clocks changed 11-01).

### 2026-10-08 losing day (−$195): the intuitive lessons were tested and FAILED
Midday reversal (oil spike; SMH −3%): two calls bought into the turn (AVGO 12:26,
V 13:22) hit −20% stops; ~14 put signals were all blocked, mostly by the 3-day
counter-trend gate. Three tempting conclusions, each checked before writing:

| hypothesis | test | result |
|---|---|---|
| "the gate cost us the puts" | simulate today's in-budget puts blocked only by counter-trend | MSFT +20, AMZN +20, ANET −20, PLTR −10.5 → avg +2.4%: a coin flip, gate cost ~nothing |
| "only trade with the market" | require SMH on the right side of its VWAP at entry, 60 sessions | **worse** in both halves (IS −2.8→−5.5%, OOS −7.0→−8.5%) — rejected |
| "don't enter after noon" | entries after 12:00 vs before, same data | after-noon entries did **better** (−3.4% vs −6.8%) — rejected |

The honest lesson: today was ordinary variance inside a strategy with no measured
edge (live day trades +$9 on $7,686 before costs ≈ −4%/trade after a 4% spread,
tracking the backtest's −5.7%). A losing day is not evidence for a rule change;
each "obvious fix" above would have made the backtest worse. Still being tracked
(n too small): size of the 3-day run at entry (MSFT 10-06 and AVGO 10-08 lost
after +3%/+6% runs; ANET 10-07 won after +5.3%).

### 30-day-trade checkpoint (2026-10-16) — the live result is the regime, not an edge
Live v2 day trades 10-05 → 10-16: **30 trades, 21 wins (70%), +$727 on $15,253, +6.3%/trade
before costs** (+2.3% after a 4% spread). Backtest expectation was ~31% win, −1.9% before
spread. `research/live_vs_bt.py` re-ran the SAME v2 rules on 5m bars over the same window:

| window | n | win | avg (pre-spread) |
|---|---|---|---|
| backtest, prior month 09-01..10-02 | 70 | 43% | −1.9% |
| **backtest, live window 10-05..10-14** | 32 | **62%** | **+3.5%** |
| live engine, 10-05..10-14 | 24 | 71% | +6.3% |

The backtest ALSO wins in the live window — October's trending, macro-driven tape (CPI
selloff, tech-to-banks rotation; puts +7.6% bt / +10.3% live) suits breakouts, September's
did not. The live engine's extra ~3 points over the same-window backtest is 1m vs 5m bars
and n=24 noise. **Verdict: no change of view — the strategy still has no demonstrated edge
across regimes; it did well in a favorable month.** Keep forward-testing; re-check at n=60
and compare against a choppy month before claiming anything. Real chain still required.

### Review of PASSED signals, 10-15 + 10-16 (user: "did you check the passed trades for mistakes?")
`research/passed_review.py`: every rejected signal priced as if taken (v2 rules, 1m bars).
31 passed; 22 in budget went 68% win, +5.9% avg, +$449 — the same as the trades taken,
i.e. the October regime lifted everything. By gate (in budget):
- **counter-trend only:** n=6, 50% win, −2.2% — a coin flip, the gate cost nothing (again).
- **whipsaw involved:** n=7, 86% win, +11.6% — but the 60-session pen-test says removing it
  is worse OOS; one favorable week is not evidence (the 10-08 lesson). Kept.
- **earnings only:** n=4, 100% win, +17.9% (META, MSFT, AMZN, V). **This one is a real rule
  error, not variance:** the day-trade earnings gate was inherited from the multi-day rules
  and was NEVER in the pen-test. A day trade is flat by 15:45, so it never holds through the
  print — CLAUDE.md's own earnings rule allows an entry that "explicitly plans to exit
  before the print". Proposed 10-17: for daytrade only, block just the report day itself
  and the session before an after-close/pre-market print; caveat — real IV on an expiry
  spanning earnings is above RV, so model premiums on those names are least reliable.
  **ADOPTED 2026-10-20** (user: "your rule doesn't have to be so strict"): day-trade
  engine blocks only `today <= earnings <= next session`. Multi-day strategies (swing,
  momentum, strangle) keep the strict before-expiry/before-exit check.
- **budget:** MU/ASML puts would have made +$334/+$69 — budget is the user's call.

### 2026-10-21 losses (NVDA −$68, GOOGL −$108 stops; ANET +$24) — what was checked
Both stops were 10:19-10:20 opening-range breakdowns that reversed within the hour (NVDA
closed +1.4% on the day). NVDA's entry was marginal on both readings flagged at entry
(relvol 1.00x, 3d −0.3%); GOOGL's was not (1.72x, −2.6%) — so "weak confirmation" explains
one loss, not two. Tested on the v2 backtest entries (`research/margin_bt.py`, 122 entries
08-26 → 10-21, current exits, 4% spread):

| entry reading | n | win | avg | IS | OOS |
|---|---|---|---|---|---|
| all | 122 | 39% | −3.9% | −3.1% | −4.5% |
| relvol < 1.10x | 49 | 39% | −4.6% | −1.9% | −5.8% |
| relvol ≥ 1.50x | 32 | 34% | −4.8% | −3.6% | −5.9% |
| **3-day move < 1% in the trade's direction** | 33 | 33% | **−7.2%** | −4.8% | −8.4% |
| 3-day move ≥ 1% | 89 | 42% | −2.7% | −2.6% | −2.8% |

Volume strength does NOT separate winners (stronger volume was no better). A marginal
3-day reading DOES, in both halves: requiring ≥ 1% (not just > 0%) would have cut
−3.1/−4.5% to −2.6/−2.8%. Caveats: IS n=11, the hypothesis came from one live loss, and the
live book is 3-of-5 winners in that bucket (JPM +0.1% won, JPM +0.3% and NVDA −0.3% lost).
Proposed 10-22: day-trade counter-trend gate threshold 0% → 1%. **ADOPTED 2026-10-23**
(user: "try your proposed strategies and see how we do"): calls need 3d ≥ +1%, puts ≤ −1%.
Not a lesson: the earnings relaxation (neither loss was earnings-related) or the SMH filter
(already rejected 10-08). Two stops in a strategy with a ~39% backtest win rate is normal.

### 2026-10-26 review (user: "review last night's trades") — `research/passed_review.py` list for 10-26
1 taken (AAPL call −20%, −$70), 11 passed. Passed signals priced as if taken: in budget
n=7, 43% win, −3.4% avg, −$21 → the gates cost nothing (counter-trend-only n=4: +0.1%).
Best misses: NBIS call +20% (+$181, blocked 3d −7.4%) — offset by NVDA −20% and AVGO −5%
blocked the same way; WDC call +20% (+$344) and COHR +12% were OVER BUDGET ($1,721 / $1,512).
No signal was blocked only by the new 1% threshold. Watch item (n=1, not a lesson): AAPL at
RV 15% stopped on a 0.5% underlying move — track whether low-RV names stop out more.

### PEER-REPORT NIGHTS — the MU 960C (10-27 → 10-28) and the first REAL implied-vol reading
User screenshot (moomoo): `MU261028C00960000` closed 10-27 at **$2.43** (day low $1.38) with MU
$929.16; SK Hynix (now US-listed) reported record Q3 after the US close and its ADR rose 6%
after hours; MU traded $969 pre-market (+4.35%) → the call opens near $9+ (~3.7x).
**Real IV from that quote: 0.51 = 1.00x RV30** (1 trading day to expiry) — the market did NOT
price a premium for the peer event. First real-chain data point the system has had.
`research/peer_event.py`: MU/WDC/STX/SNDK, 10y, peer report days inferred from SK Hynix /
Samsung volume spikes in their usual windows (approximate ±1 day), 1-DTE ~1 daily-σ OTM
legs bought at the close, sold at the next open, overnight-variance pricing, 10% friction:

| | n | mean abs gap (gap-sd) | big gap > 1 sd | strangle IV=RV (IS / OOS) | strangle IV=1.3x |
|---|---|---|---|---|---|
| all nights | 7,720 | 0.72 | 22% | −10.3% (−11.8 / −8.9) | −59.6% |
| **peer-report nights** | 231 | **0.97** | **32%** | **+30.0% (+42.6 / +17.7)** | −39.3% |

Peer nights gap ~35% bigger and the strangle is positive in BOTH halves **if** the options
are priced at RV — which the one real quote says they were. At 1.3x RV it loses. Calls alone
fail the halves test (−16.9 / +27.9); direction is still a coin flip (SK Hynix's net income
MISSED and MU still popped). Proposed 10-28 (pending user OK): paper-trade a 1-DTE ~1σ
strangle on MU (≤ $1,000; this one was ~$243 + a ~$2-3 put) at the close before each
scheduled memory-peer report (SK Hynix quarterly, after the US close; Samsung preliminary,
~7th-8th of Jan/Apr/Jul/Oct, Korean morning = US evening), sold at the next open — and get a
real quote screenshot each time to log the implied vol. ~8 events/year; n will stay small.
**Robustness check 10-28 (`research/peer_event2.py`) — NOT adopted as a paper strategy.** Per event
(73 events; the 4 names on one night are one bet): +30.8% at IV=RV but t +1.1, win 32%, median −41%
— it is a few fat-tail nights (MU 2026-04-08 +563%). Break-even IV ≈ 1.08x RV (1.10x: −2.0%; OOS
already −11.0%). **MU alone is negative even at IV=RV (−12.6%).** By peer: SK Hynix nights +65% at
RV / +9.5% at 1.15x (n=37); Samsung prelim nights −4.4% / −37.9%. Dating is unreliable: report days
are inferred from Korean volume spikes, and the 10-27 event itself landed on the pre-report run-up
day (Korean 10-27), not the report (Korean 10-28) — so the sample mixes real and wrong nights.
Direction: the Korean peer's own reaction is known before the US open (Seoul closes 02:30 ET);
corr with MU open→close +0.32, peer < −3%: MU open→close −1.30% (n=11), peer > +3%: +1.09% but only
53% up (n=17) — too small to be a rule. Decision: log SK Hynix report nights as `watch` with a
real-quote IV reading; re-test with VERIFIED historical report dates before any paper rule.
**"But MU had already risen 2-3 days straight" (10-28) — `research/streak_bt.py`:** MU closed up
10-23/26/27 (3d +8.4%) on FALLING volume (0.71x/0.76x/0.61x), 16% under its 20d high. Up-streaks
predict nothing: next-open up 52-53% at streak ≥2/3/4 vs 53% on any day; a 0.2σ call bought at the
streak close and sold next close −0.4% / −1.5% / −2.5% (OOS −2.2/−3.5/−3.7%). The MU-like case
(streak ≥3 below the 20d MA) was WORSE: gap −0.30%, call −7.1% (IS −5.5 / OOS −8.2), n=219. MU-only
+3.0% is +11.8 IS / −12.6 OOS (n=69) — noise. The streak was not the signal; the scheduled peer
report was.

### REAL FILLS — from 2026-11-04 (user: "buy at the ASK, sell at the BID")
`analysis/option_quotes.py`, used by all four engines (day trade incl. Z0, lottery, strangle, trend-hold).
- Source: yfinance `option_chain()` (needs fc.yahoo.com). Quotes are **~15 min delayed**. Yahoo's own
  `impliedVolatility` column is garbage (0.00001 on liquid puts) — IV is solved from bid/ask against the spot
  at QUOTE time (1m close ~15 min earlier), then re-priced to the live spot: buy = BS(spot, IV_ask), sell =
  BS(spot, IV_bid). A quote below intrinsic (stale vs spot) is floored at intrinsic − spread.
- Entry caps are checked against the real ask. Day-trade / Z0 positions are then marked minute by minute at
  the entry quote's BID IV (a 15-min-old bid cannot drive a 1-minute stop). Fixed-time exits (1-day ticket at
  the open, strangle at the close) take the real bid; run 1-day exits at **≥ 09:46 ET** so the delayed chain
  shows opening quotes.
- **Yahoo rate-limits this container (HTTP 429) on and off** — on 11-04 about a third of fills fell back to
  the model (NBIS day trade, the AAPL 1-day pair at the close). Fixes 11-05: failed fetches cached 60 s (no
  retry storm); a cached chain up to 10 min old is used before the model (IV solved against the spot at that
  older time); the day-trade engine pre-fetches the 2-week chain for the 2 names within 1% of their opening-
  range level each minute; the 15:50 engines retry for ~60 s. No-quote rows: `price_source=model (no quote)`.
- **Real IV / RV30 readings, 11-04** (first full day): 1-day AAPL tickets 1.63-1.9x; 2-week MSFT 1.33-1.36x,
  NVDA 1.34-1.39x, NVTS 1.22x, SMCI 1.11x, AAPL 1.01x, GOOGL 0.73x; same-day GOOGL 0.78x. The model was badly
  cheap on 1-day tickets, NOT uniformly cheap at 2 weeks.
- **Strike-grid bug (found 11-05):** every engine built strikes from a fixed price-step table, but real listed
  grids are coarser (NBIS 11-20: 125/130/135; NVDA ~$195: 2.5s; SMCI 1s). NVDA 194, NBIS 131/133, SMCI 27.5 do
  not exist — NBIS261120P00133000 (11-04) was a contract that could never fill, and that, not the rate limit,
  is why it had no quote. All engines now snap to LISTED strikes (`oq.snap`, nearest; OTM side for tickets).
  A persistent "no quote" on one contract while others quote = suspect the strike, not Yahoo.

- **Expiry-calendar bug (found 11-12):** the same-day and 1-day ticket engines assumed DAILY expiries for NVDA/AAPL/MSFT/
  AMZN/META/GOOGL/MU. Yahoo lists **Mon/Wed/Fri only** (11-13, 11-16, 11-18, 11-20). On Thu 11-12 the Z0 slot fired
  `NVDA261112C00170000` - a contract that does not exist ("NO QUOTE", model $19); VOIDED before booking. Both engines now
  require a Mon/Wed/Fri expiry (`ZDAYS` in daytrade_engine.py, `exp_ok` in lottery_engine.py). Same night the NVDA 1-day
  pair (172.5C/160P 11-13) had no quote at the engine's fetch (Yahoo 429), model $71; a re-fetch gave real asks
  $60 + $147 = **$207 (2.9x the model)**, over the ~$123 cap -> NOT booked. Rule: a no-quote LT/Z0 entry is re-fetched
  before booking; if the real ask is over the cap, or the contract is not listed, it is void.

### 11-04 review (user: "what could you have done better") — `research/review_1104.py`, `research/sector_cap.py`
Day: tech/banks rallied (AAPL +5.7%, MSFT, JPM, V up), chips broke down 10:45-11:00. Taken: NBIS put −5%
(model, no quote), NVTS put −20% (stop on a $0.02 move — the 20% bid-ask spread did it), SMCI put −13% (late
entry) = −$68; GOOGL same-day call +94% booked (+61% if the limit did not fill); AAPL 1-day pair +$472 real.
All 24 signals replayed (v2 exits, 1m bars; "real" = 1.25x RV − 4%): taken 0/3, −13.2%; counter-trend-blocked
calls +6.6% at RV but −2.8% real (n=6) — the gate again cost ~nothing; slot-full blocked (mostly chip puts)
−6.7% — the 2-open cap saved money. Calls won, puts lost: ONE rotation day, not a rule.
- **Tested and REJECTED: max 1 open day trade per sector group** (pre-specified groups: 17 chip/AI-hardware
  names, 5 mega-caps, PLTR/JPM/XOM/V alone; 40 sessions 09-10 → 11-04, 102 gate-passing signals, slot-by-slot
  replay, 4% spread): current max-2 −3.1% (IS −6.9 / OOS +1.3); sector cap −3.4% (IS −6.3 / OOS −0.0), worse in
  P2 and P3. The 14 second-same-sector positions it would remove averaged +3.2%. "Three chip puts were one
  bet" was a bad day, not a pattern. No change.
- **Pending: spread filter** (e.g. skip if real spread > ~10% of mid, the NVTS case). Needs ~20 sessions of
  logged quotes (every real fill now logs bid/ask) before it can be tested — do not adopt on one trade.
  **11-11: a 25% DATA-QUALITY guard added** (`MAX_SPREAD` in daytrade_engine.py, DT + Z0): COHR261127C00270000 was
  bought at 3.80/7.50 (65% spread, vol 6, OI 75) — −45% at entry, stopped 1 min later with COHR UP, −$374 booked at
  the real bid. A > 25% spread is not a market, same class as the 10-07 volume-suspect guard. Wide-spread record so far:
  NVTS 20% −20% (11-04), MU Z0 36% −50% (11-09), MSFT 19% −20% in 1 min (11-10), MU Z0 35% +100% (11-11), COHR 65%
  −44% (11-11). A tighter 15% cap is the USER's decision (proposed 11-10); test the threshold on `data/quote_log.csv`.
  Exits on wide-spread fills are booked at the REAL bid, not the −20% rule level, so the book does not hide the spread.
- Process misses (fixed or noted): a META put rejection at 14:25 was never relayed (monitor re-arm failed while
  the permission check was down — "nothing fired" was a gap, not silence); the stale-signal hole above; the
  pre-market read said only an NVDA put could fire and missed the post-earnings names (NBIS, NVTS, SMCI) that
  produced every entry.

### 11-09 review (user: "review last night's trades") — `research/review_1109.py`
Day 3 after the 11-05 crash: a broad chip relief bounce (SMH ~+3.5%, COHR/CRDO/VRT/MRVL/AVGO +7-11%) while mega-caps
faded; NVDA −4.7% on the Huang probe. Taken: 0 day trades; MU same-day call −$15 (MU flat — a 36% spread plus same-day
theta); NVDA watch strangle −9% over the weekend. All 17 signals replayed (v2 exits, 1m bars, "real" = 1.25x RV − 4%):
**counter-trend-blocked bounce calls n=15: +4.6% at RV, −1.6% real** — the gate cost ~nothing once friction is in, as
in every earlier review. The +20% winners (COHR, MPWR, AVGO) were also over the ~$1,000 cap ($1.0-5.4k); the in-budget
blocked signals averaged ~−4% real. No change. Process: Yahoo printed NVDA volume as 3.5B shares (feed error — the 8.5x
relvol on the NVDA signal was not real); trend-hold crashed on a whipsaw_stats key (`down5`, fixed); MRVL's earnings
date was an estimate (fixed to the verified 12-01).

### MU 261111 800C "$1.01 → $23.20" (user screenshot 11-11: "research harder so you can get signs for these bounces")
MU gapped +7.2% (725 → 777), dipped to 763.05 at 09:36 (the 800C's $1.01 low), then ran to 822 by 11:00 (+13%). The
engine DID see it: MU broke its OR high at 10:11 with gates PASSING (3d +10%); the 2-week call was over the $884 cap;
the Z0 slot bought `MU261111C00845000` at $33 and sold the +100% cap at 10:28 ($65) — the option was ~$200+ by 11:00.
Real IV from the screenshot: $22.37 at MU 820.5 → **IV 0.47 = 0.6x RV30** (deep ITM, 5h left).
Two pre-specified tests (`research/bounce_signs.py`, `research/z0_exit_test.py`):
- **Signs at the open (5y daily, 28 names, 32,666 name-days):** names in a ≥ 20% drawdown are twice as volatile
  intraday (≥ +3% open→close 23% of days, ≤ −3% 21%) but directionless (51% up). **A gap UP in a drawdown name FADES on
  average:** gap ≥ +2%: o→c −0.19% (45% up, IS −0.26 / OOS −0.16); gap ≥ +4%: −0.83% (39% up, −0.56 / −0.86); with SMH
  also gapping up −0.36%; after an up day −0.70%. A 0.2σ 2-week call bought at the open lost −7% to −13% in every
  gap-up cut. MU today was the 23%-of-days right tail of a setup that loses on average — not a detectable sign.
- **Letting the Z0 winner run:** 40 first-of-day signals (40 sessions): +100% cap −22.5% (OOS +0.0%); trail 30% −23.5%
  (OOS −4.8%); trail 50% −23.9%; half-off −35.0%; no target −36.0% (best +901%, 2% win). The cap is the best exit
  tested; today's give-up is the cost of a rule that is right on average. No change.
What remains untested and plausible: option-flow / IV-skew signals (need the moomoo chain), which price/volume lacks.

### SAME-DAY TICKET SLOT — funded from 2026-11-03 (user: "be slightly more open to such trades" → chose "fund a tiny slot")
Chosen knowingly over "track only": the screen above says ~−32% per ticket, so the expected cost is roughly
$7/day (~$140/month) of the November book. Rules (`research/daytrade_engine.py`, `ZDAILY`, `z_pick`): the FIRST
confirmed opening-range break of the day (held ≥10 1m closes, VWAP side, relvol ≥ 1.0x) on a daily-expiry
name (NVDA, AAPL, MSFT, AMZN, META, GOOGL, MU — assumed, confirm on moomoo) buys ONE same-day option ~1.0-1.5
remaining-session σ OTM, premium ≤ 2% of November equity (`bankroll.CAP['zerodte']`, ~$23 now), gates NOT
applied (the MU 840P case was whipsaw-blocked), earnings day / day before still blocked. Exits +100% / −50% /
15:45 ET. Engine prints `Z0 ENTRY` / `Z0 EXIT`; book as `strategy=zerodte`, `book=paper`. Note: MU itself rarely
fits — the 840P was ~$143 (model) at the 11:18 signal, so the slot mostly lands on the cheaper names. Review
at 20 tickets against real quotes (the model's 0DTE prices are the weakest link); stop if the record matches
the backtest.
**Third REAL implied-vol reading (11-03, first one on an ordinary non-event day):** user screenshot of
`MSFT261104C00525000` (next-day expiry, 1.86 sessions left) at $1.50 with MSFT 514.45 → **IV 0.286 = 1.30x RV30
(22%)**; the model at RV priced it $0.73, i.e. HALF the real price. At that IV the same-day 525C booked as Z0 ticket
#1 is ~$48, not the model $14 — over the ~$24 cap. So: (1) short-dated OTM calls trade well above RV even with no
event, unlike the two post-event readings (1.00x, 1.05x); (2) 1.30x sits just under the 1-day tickets' ~1.4x
break-even; (3) model-priced Z0 / LT fills are probably 2-3x too cheap, and a 2%-of-equity cap may not buy a real
same-day ticket at all. One reading — keep collecting before changing a rule.
**Fourth/fifth REAL readings (11-03 close, the AAPL 1-day ticket pair, user screenshots):** `AAPL261104C00337500`
last $0.65 (model $0.11) and `AAPL261104P00327500` last $1.05 (model $0.38), AAPL 331.85, RV30 18%, the day after
AAPL's report → **IV 1.67x (call) / 1.80x (put) RV30**; the real pair cost ~$170 vs the model $49 (3.5x) and over the
~$118 cap. Both are ABOVE the 1-day tickets' ~1.4x break-even. Caveats: last trades after the close (not mids), and
a post-earnings night. Short-dated readings so far: MSFT 1.30x, AAPL 1.67/1.80x — the model's LT/Z0 fills are 2-6x
too cheap and the LT gains in the book are not real-world gains. Proposed 11-04 (pending user): price LT/Z0 entries
at IV = 1.5x RV30 (call) / 1.7x (put) so the paper book stops overstating them, and decide at 20 nights whether to stop.

### MU 261102 840P "$0.04 → $10.48" (user screenshot 11-03) — what we saw, and the same-day-option test
MU fell 884.89 → 833.59 on 11-02 (−5.8%, a steady slide all session). The day-trade engine DID flag the
breakdown: MU put at 11:18 ET, 869.48 (below the 870.77 opening-range low) — REJECTED by the whipsaw gate
(2 up / 3 down big days); the 2-week 0.2σ vehicle would also have cost ~$3,600 (7x the November $500 cap).
Priced as if taken it would have hit +20% at 12:35. The screenshot's $0.04 was the 0DTE put at the open
(MU ~885, ~1.5 daily σ OTM) — a direction bet on the whole day, the parked "0DTE lottery" idea.
**Tested the obvious fix — buy a SAME-DAY option at the confirmed break instead** (`research/zerodte_bt.py`,
175 month_review ORB signals on the 7 daily-expiry names, 0.5/1.0/1.5 remaining-session σ, BS at RV30, +100% /
−50% / 15:45, 10% friction): **−32% to −33% avg, 18% win, negative in every period (P1 −47%, P2 −35%, P3
−21%)**; signals that pass today's gates were worse (−50%, n=46); without the stop −59% to −63%. Same-day theta
eats a confirmed break that the 2-week vehicle survives. Not adopted. (Model screen; real 0DTE quotes would
be the decisive test, but the gap is too wide for pricing error to close.)

### SNDK 261106 1120P "$1.96 → $40" (user screenshot 11-02) — why nothing flagged it
Reconstructed (`daily_frame('SNDK')`, BS at RV): the ~$2 low was **10-28** (SNDK $1,404 after a +11.8% 3-day
bounce, the put **1.9σ OTM**, 7 sessions left), the day before **SanDisk's FQ1 report (10-29 after the close)**;
10-30 SNDK −13.5% on 2.8x volume → put ~$33, then ~$40 on 11-02 (SNDK $1,134). It was an earnings-direction
ticket. Every rule blocks it: SNDK is not in any trading universe (backtests only), earnings inside the hold,
strike > 1σ (the 0-for-10 bucket), and a put into a 3-day bounce (counter-trend). Which way an earnings print
breaks is the coin flip the event radar cannot call; the same ticket had SanDisk rallied 13% was worth $0.
**Second REAL implied-vol reading:** $40.30 at 10:32 ET with SNDK $1,134, 4.2 sessions left → **IV 0.75 = 1.05x
RV30 (0.72)** — after the event, near RV, like the MU 960C (1.00x). Logged for the IV-vs-RV question.

### Data accuracy check 11-02 (user: "is your data even accurate, since when was nvda 202.90")
Audited every 15:50-ET entry (strangles, 1-day tickets) against 5m/1m bars at the entry minute: 10-19 → 10-29
within ±0.1-0.26% of the true print, but on **10-30 the 5m-rebuilt daily bar was ~25-30 min stale** — NVDA ticket
logged 202.90 vs 204.91 live (−1.0%), NVDA strangle 202.72 vs 203.45, AMZN/MSFT −0.2/−0.3%. For a 1-DTE ticket a
1% spot error is ~0.5 daily σ: the NVDA pair was booked at $50 instead of ~$73 (+168% → **+84%** corrected).
Fixed: the 10 rows repriced (contracts kept, premium re-marked at the true spot, notes appended); all three
15:50 engines now price entries off `er.live_price()` (latest 1m print) and print its age. Separately, on 11-02
**Yahoo's own feed ran ~11 min behind** (meta regularMarketTime 09:59 at 10:10) — nothing in our pipeline; the
day-trade engine heartbeat now shows `feed lag`. Paper fills on a lagged feed are at the bar's price (no
lookahead), but a live trader acting on the alert would be that many minutes late.

### Loss audit of the whole record (user 11-02: "was there a way to prevent them?") — `research/loss_audit.py`
74 closed swing / momentum / day trades (paper, real and the 09-14 watch basket) re-scored at entry with TODAY's
rules; winners scored the same way so a rule only counts if it removes more losing than winning dollars.
- **Today's entry rules would have blocked 30 trades: 25 losers (−$16,551) and 5 winners (+$3,477).** The 44 that
  pass: 15 losers (−$1,461), 29 winners (+$4,457) → +$2,996. All 5 REAL-money losers (BKNG, AAPL, VST, MRVL, NVO,
  −$642) would have been blocked (strikes 1.1-1.6σ, VST also counter-trend, NVO RSI 73).
- By rule (a trade can carry several): **position size > $1,000 — 9 trades, −$14,123 of losses vs +$3,221 of wins**
  (MU $8,410 call alone −$4,781; DELL/ASML/MPWR/LLY $1.6-3.0k each) — the single biggest cause, and it is the rule
  the user just tightened; strike > 0.6σ 21 trades (−$7,824 vs +$256); counter-trend 11 (−$6,539, zero winners);
  whipsaw 7 (−$6,832 vs +$173); earnings not checked 4 (−$2,050, zero winners).
- **Exits:** the 35 multi-day trades booked −$10,945; re-run with a resting −50% stop + the trailing exit, −$257
  (model path). Several stops were executed late at −76% to −85%, and big peaks round-tripped.
- **The 15 losses no rule catches (−$1,461)** are mostly −20% day-trade stops — the normal cost of a ~40%-win
  strategy; two (JPM 10-16, NVDA 10-21) are caught by the newer 1% gate.
- **Hindsight caveat:** most of these rules were DERIVED from these very trades, so this shows they fit the past,
  not that they predict. The forward evidence is what came after they were adopted (October day trades, the
  5-year trend tests) — positive, but regime-dependent.

### NOVEMBER $1,000 BOOK (user 11-01: "be stricter with the budget. we will only use $1000 to trade for the month. make sure to make the most out of it")
Read as a $1,000 CASH account for November (`analysis/bankroll.py`, START 2026-11-02): every funded paper trade
(book=paper, created ≥ START) is paid from it, proceeds return on close, so wins compound and losses shrink the
next trade. Caps are fractions of current EQUITY, always within available cash:
- **day trade ≤ 50% of equity, max 2 open** (−20% stop = ≤ 10% of equity per trade). The engine re-reads the book
  each signal (`dt_budget`); a $500 cap pushes some strikes toward 0.4σ or skips them. Checked first: in-budget
  ≤ $500 signals did no worse than $500-1,000 ones (−3.4% vs −3.2%, month_review signals).
- **1-day ticket pair ≤ 10% of equity, max 2 pairs/night** (the premium can go to zero). Exits at the open are
  booked at ~09:35 ET (`lottery_engine.py exits`) so the cash is back before the 10:00 day-trade window.
- **trend-hold ≤ 50% of equity, max 1 open** (−50% stop = ≤ 25%) — the best-evidenced strategy, dormant while SMH
  is under its 50-day MA.
- **strangles NOT funded** — negative expectation at realistic IV (backtest −7%/night at 1.15x; live +$697 was the
  October volatility). Still logged nightly as book=watch so the 20-night forward test keeps collecting data.
Why fractions, not "spend it on the best trade": nothing here has a demonstrated edge after costs, so the way to
"make the most" of a fixed $1,000 is to stay in the game for the month — no single trade can lose more than 10-25%
of equity, and wins enlarge the next position. `bankroll.summary()` also shows an after-spread estimate (4% day
trade / trend-hold, 10% tickets) next to the model-priced equity. The 10-30 strangles and tickets are October's
book and are excluded.

### 2-3 week options in the CURRENT tape (user 11-02: "don't only follow the day trade engine ... 2-3 weeks dte")
`research/swing_now.py`: 5 years daily (incl. 2022's bear market), 26 names, 1,342 gated 20d closing-break
signals, 0.2σ, trailing exit, 4% friction, IS/OOS split 2024-06-11. Four PRE-SPECIFIED cuts (no sweep):

| cut | n | 2-wk @1.0x RV | 2-wk @1.15x (IS / OOS) | 3-wk @1.15x (IS / OOS) |
|---|---|---|---|---|
| all signals | 1,342 | −2.5% | −6.1% (−8.5 / −3.4) | −8.9% |
| **A calls, SMH > 50d, vol ≥ 1.5x (live trend-hold)** | 156 | +10.1% | **+7.9% (+4.6 / +12.0)** | +0.9% (+2.8 / −1.5) |
| B puts, SMH < 50d, vol ≥ 1.5x (its mirror) | 112 | +4.4% | +1.1% (+6.1 / **−4.5**) | −6.0% |
| C calls, QQQ > 50d, vol ≥ 1.5x, non-semis | 64 | +5.4% | −3.1% (**−17.9** / +10.8) | −8.3% |
| D puts, QQQ < 50d, vol ≥ 1.5x, non-semis | 45 | +10.4% | +11.4% (+0.4 / +24.0) | +0.4% |

Verdict: **A stays the only multi-week entry, and 2 weeks beats 3** (the extra week is theta without extra
edge). The downtrend versions fail: B is negative OOS (positive only in 2022), D is n=45 with years
swinging −33% to +25%. Today (10-30 close) SMH 523 < 50d 573 and QQQ 691 < 50d 725 — so there is NO
validated 2-3 week trade to put the $1,000 into right now; forcing one would be the failure mode this
book warns about. Capital priority when signals compete: trend-hold (best evidence, ≤ 50% of equity) →
1-day tickets (≤ 10% per pair) → day trades (cash left intraday; flat by 15:45, so they never block an
overnight entry); strangles unfunded. Max overnight commitment is 70% of equity (50% + 2 × 10%).

### Month review 11-01 (user: "losses that could've been avoided, wins we could've taken — improve") — NO rule change
`research/month_review.py` (every ORB signal 08-26 → 10-30 rebuilt on 5m bars, gates RECORDED not applied,
617 signals, 99 pass today's rules; 4% spread; split into halves AND thirds P1 08-26..09-16 / P2 09-17..10-08
/ P3 10-09..10-30) + `research/regime_test.py`. Market: SMH 553 → 631 (10-02) → 523 (−17% in four weeks).
- **The result is the regime, again.** Taken set: P1 +0.2%, **P2 −8.0%** (the choppy late-Sep rally), P3 +1.2%
  (the October selloff; puts +4.7%). Live day trades (38, +$809 before spread) track P3. A pre-specified
  regime filter (SMH 10-day efficiency ratio, IS-median threshold) FAILED — trending days were worse IS.
- **Passed signals were right to pass:** blocked only by the 3-day gate n=215, −5.6% (negative in all three
  periods); RSI n=13 −6.8%; whipsaw-only n=14 −0.1%; over budget n=55 −3.4% (P3 +2.5% only) — a bigger
  budget adds volume, not edge.
- **No entry filter is robust** (≈25 cuts, so a few will look good by chance): gap against the trade (31,
  −6.1%), opening range < 1% (19, −5.8%), RV30 < 25% (34, −6.9%) and entries after 13:00 (21, −7.2%, worse
  in all three periods but contradicts the 10-08 after-noon test) each fail at least one period or are
  cutoff-shopping. Tracked as watch items, re-test at n=60 live.
- **Exits:** 9 variants; none beats the current +20/−20/120m in every period (trail arm +15 / give back
  30%: −3.1% vs −3.3% overall, worse in P1). No change.
- **Live audit of the 1% gate (adopted 10-23):** of the live day trades it would have blocked 2 losers
  (JPM 10-16, NVDA 10-21: −$136) and 3 winners (AAPL 10-08, JPM 10-14, NVDA 10-14: +$277) — net −$141 live,
  against the backtest's −7.2% for that bucket (n=33). Kept; this is the first live counter-evidence.
- **Strangles (24 over 9 nights, +$697):** P&L is the realized move (corr 0.95 with |move| in sd): ≥ 1-sd
  moves +24% (10), < 1 sd −7.3% (14). Higher model scores did WORSE live (≥0.20: +2.7%, <0.20: +9.5%) — no
  sign yet the ranking works; a volatility bet that paid in a volatile month. Review at 20 nights as planned.
- What did improve this week was data hygiene, not rules: VRT/NBIS earnings dates were wrong, COHR/NVTS/
  MPWR/DELL had none (both kinds blocked or mis-allowed signals), and the 1-day-ticket strike grid bug.

### "Hold 1-2 weeks to maximize profit" / "$700 on $15k — could anything net more?" (10-20)
`research/hold_bt.py`: the SAME v2 day-trade entries (121 in budget, 08-24 → 10-19, 5m bars
continuous across days, 4% spread), only the exit varied:

| exit | win | avg | IS | OOS | $ on $69.6k premium | avg hold |
|---|---|---|---|---|---|---|
| **current same-day +20/−20/120m/15:45** | 39% | **−3.7%** | −3.3% | −3.9% | −$2,635 | 0.1d |
| same-day +20/−20 to 15:45 | 37% | −4.2% | −5.0% | −3.6% | −$2,988 | 0.1d |
| same-day +50/−30 | 35% | −4.4% | −6.6% | −3.0% | −$3,080 | 0.2d |
| hold ≤5d, −50 stop, trail 30% after +50 | 39% | −13.3% | −28.3% | −3.8% | −$7,132 | 3.6d |
| hold to 2 DTE, same trail | 40% | −12.5% | −29.4% | −1.7% | −$5,990 | 3.8d |
| hold ≤5d, −30 stop, trail 25% after +30 | 30% | −6.4% | −16.2% | −0.1% | −$3,748 | 1.9d |

**Holding these entries longer loses MORE, not less** — the 10-15 exit-grid result was for
20-day closing-break entries, not intraday opening-range breaks; an intraday break has no
multi-day follow-through to ride (median −54% when held). The current same-day exit is the
best of every variant, and over the full 40 sessions (September included) it is −3.7%/trade
after spread: the live +$727 is October's tape, not a pattern that "nets more". Note the
denominator: $15k is premium turnover over 30 trades; peak capital at risk was ~$1.6k.
No change to day-trade exits.

### "What entry works for holding longer?" (10-20) — `research/hold_entry.py`
20d closing-break signals (all gates, 27 names, 2y), exit FIXED = the adopted trailing exit,
split by what was known at the entry close; IS/OOS by date; 4% friction.

| entry (2-week 0.2σ) | n | IV = RV: avg (IS / OOS) | IV = 1.15 RV: avg (IS / OOS) |
|---|---|---|---|
| all signals | 477 | −1.5% (+4.4 / −7.3) | −3.3% (+3.3 / −10.0) |
| **puts** | 181 | **−21.4%** (−15.3 / −26.9) | −20.2% |
| calls | 296 | +10.7% (+15.6 / +5.6) | +6.9% (+14.0 / −0.5) |
| with sector trend (call & SMH > 50d MA, or put & below) | 342 | +4.1% (+9.2 / −1.8) | +0.9% |
| against sector trend | 135 | −15.6% | −14.1% |
| **calls, SMH > 50d MA, volume ≥ 1.5x** | 55 | **+23.9%** (+39.5 / +3.7) | **+20.3%** (+26.5 / +12.3) |

Held PUTS lose in every cut — never hold a put for weeks. The only cut positive in both
halves at 1.15x RV is a CALL on a 20d closing breakout with SMH above its 50-day MA and
≥ 1.5x volume, 2-week expiry, trailing exit. Caveats: n=55 (31/24), picked from ~40 cuts
(data-mining risk), a 2025-26 chip bull market (calls rode the up-cycle), and the 4-week
version of the same cut is −1.7% at 1.15x. A hypothesis to forward-test, not a rule.
**PAPER-TRADED from 2026-10-23** (user OK): `research/trendhold_engine.py`, run at ~15:50 ET
after the strangle step. `strategy=trendhold`, `book=paper`, kept separate. CALL only: close
> prior 20-session high, SMH > its 50-day MA, volume ≥ 1.5x (scaled to a full day), not chop,
3d ≥ 0, RSI ≤ 70, earnings strictly after expiry, one signal per name per 5 sessions;
0.2σ call 2 Fridays out, ≤ $1,000, max 3/night. Exit = trailing (−50% stop; after +50%,
exit 30% off the peak; 2-DTE close), checked each session on that day's high/low, peak
kept in `research/trendhold_state.json` (commit it). First scan 10-22: SMH 523 vs 50d MA
576 → no entries until the chip complex recovers above its 50-day. Review at 10 exits.

### Paper STRANGLE forward test (user 10-20: "paper trade the strangle model as well")
`research/strangle_engine.py` (+ `strangle_model.json`, refit with `fit`): run at ~15:50 ET
each session. EXIT: yesterday's strangles sold at today's close. ENTER: names scoring above
the model's top-decile line (0.114) → 0.2σ call + 0.2σ put, Friday ≥ 7 days out, both legs
≤ $1,000, max 3/night; blocked if earnings today/next session or no verified date.
`strategy=strangle`, `book=paper`, one row per leg, kept separate from the other stats.
Backtest expectation is NEGATIVE (−7%/night at 1.15x RV): this exists to measure model
fills against the real chain later, not because it is believed to win. First night 10-19
close: AMZN, NVDA, GOOGL (NBIS over budget). Review at 20 nights.
Added to the 09:15 ET scheduled task (step 7).

### Event-night STRANGLE test (user 10-19: "train yourself to catch this") — not adopted
Trigger: calls bought at the 10-16 close on the beaten chip names were +25% to +227% by
10-19 midday (model), puts −23% to −85%; a direction-free strangle was the only version
that did not need hindsight. `research/strangle_bt.py`: 0.2σ call + 0.2σ put, Friday
≥ 7 days out, entry at a close, exit next open / next close / 2 closes; 26 names, 5y daily
(30,193 name-nights), 4% friction, IS/OOS by date; plus a walk-forward logistic model
(refit yearly, test 2024-26, event-radar features) that learns which nights pay.

| condition (exit next close) | IV = RV30 | IV = 1.15 × RV30 |
|---|---|---|
| every night | −2.4% | −18.7% |
| SMH 2-day ≤ −4% (the 10-15/16 type) | −1.1% | −17.7% |
| same AND Friday (the weekend just gone) | −1.0% | −17.6% |
| FOMC nights | +3.6% | −13.7% |
| volume > 1.5x AND range > 2 sd | **+12.8%** (IS +10.9 / OOS +14.4) | −6.0% |
| walk-forward model top 10% (AUC 0.65) | — | −7.3% (vs −18.5% all) |

**The model learns WHEN — AUC 0.61-0.65, its top decile loses a third as much — but no
version is profitable once the options cost more than ~1.03-1.13x realized vol** (break-
even IV: FOMC 1.03-1.08x, big-volume/big-range days 1.10-1.13x). Real IV after a 2-sd,
1.5x-volume day sits well above that, because RV30 lags and the market prices exactly the
volatility the model detects. Same verdict as the 09-27 overnight-straddle note: the
positive rows are the realized-vol pricing proxy, not an edge. The selloff-weekend setup
the user saw (10-16 → 10-19) was a coin flip even at RV pricing. **Decisive test needs
the moomoo chain:** is real IV on the model's top-decile nights below ~1.1x RV30? Until
then: no strangle trades; the model's nightly top names can be logged as `watch`.

### Overnight trend options (user request 2026-10-15) — backtested, NOT adopted
Trigger: the user's real moomoo screenshots on 10-15 — `MU261016P00870000` +201% on the
day ($4.75 → $14.30, high $23.60) and `SNDK261016P01300000` $0.75 → $27.50 over ~a week,
both riding the memory-chip selloff mostly through OVERNIGHT gaps the day-trade rules
never hold. Tested `research/trend_bt.py`: daily bars, 2 years, 27 names (26 + SNDK);
signal = close beyond the prior 20-day low/high, entry at that close, held overnight,
+50% / −50% / 2-DTE exits, IS = first half of signals, OOS = second half.

| variant (after friction) | n | win | IS | OOS | all |
|---|---|---|---|---|---|
| all gates, 1wk, 0.2σ | 495 | 43% | −9.6% | −11.3% | −10.4% |
| all gates, 2wk, 0.2σ | 494 | 44% | −7.8% | −13.1% | −10.5% |
| no RSI gate, 2wk, 0.2σ (best) | 757 | 48% | −3.3% | −9.5% | −6.4% |
| all gates, 1wk, **1.0σ (lottery)** | 495 | 40% | −17.5% | −17.7% | −17.6% |
| all gates, **this-week 1.0σ (lottery)** | 495 | 36% | −23.7% | −23.7% | −23.7% |

**Puts were the worst side** in every variant (−15% to −33%). The far-OTM "lottery"
versions — the shape of the two screenshot winners — were the WORST, consistent with
the book's >1σ 0-for-10. The only positive pocket was the memory names (MU/SNDK/WDC/STX,
+10.8% avg in the best variant) — but that came from CALLS in the 2025-26 memory
up-cycle, memory PUTS were negative (MU puts −14% / −29%), the subset decays from +19.8%
IS to +1.2% OOS, and picking the sector that just made money is hindsight selection.
**Verdict: no general edge; do not build an overnight trend-options strategy on this.**
Honest coverage notes: the rule DID flag SNDK put at the 10-12 close ($1,487) and MU put
at the 10-14 close ($913.91) — both before the screenshot moves — but a 0.2σ MU put was
~$3,000 (over budget) and the actual winners were far-OTM 1-DTE tickets the backtest
says lose on average. Forward-test instead: log trend signals as `watch` rows going
forward so the record builds without risking the paper P&L.

### The 10-15 "missed puts" (NBIS 160P +731%, DELL 450P +1290%, STX 660P +620%, MU 870P +201%, SNDK 1300P) — tested
All were 1-DTE far-OTM PUTS that exploded at the 10-15 open on ONE shared event: a hot
September CPI (3.7%) at 08:30 ET plus AI-funding fears — the whole AI-hardware complex
gapped down 4.6-7.2% at the open (DELL −7.2%, NBIS −5.7%, SNDK −6.4%, WDC −5.7%, MU −4.6%;
SMH −3.3%). Five winners from one correlated gap is one event, not five signals.

Tested the pattern (`research/lottery_overnight2.py`): buy a 1-DTE put 1.0/1.5/2.0σ OTM
at every close, sell at the next OPEN, 27 names × 2 years (~12k name-nights each), 10%
friction. **First version showed +40% to +224% per night — a pricing ARTIFACT** (the
same trap as the overnight-straddle note): Black-Scholes at RV charged no time for the
overnight gap, so every far-OTM ticket looked free. Corrected by charging the measured
overnight share of daily variance (33-59% by name) and a modest put skew:

| strike | sell at next open, avg | ≥ +100% | ≥ +400% | lose > 80% | median |
|---|---|---|---|---|---|
| 1.0σ | −28.4% | 7.3% | 1.7% | 29% | −60% |
| 1.5σ | −31.6% | 6.1% | 1.8% | 39% | −71% |
| 2.0σ | −31.6% | 4.7% | 1.7% | 51% | −81% |

The 5x+ nights happen ~1-2% of the time; on average the ticket loses ~30% a night and the
median loses most of its value. Requiring a prior 3-day decline changes nothing. Only
selling at the exact day's LOW is positive (+96-115%) — perfect hindsight timing. **Do not
trade nightly lottery puts.** The real lesson: these are macro-event gaps (CPI morning);
the event radar can flag *that a big gap is likely* on scheduled release nights, never the
direction. **Lesson about my own process:** a backtest that suddenly shows +90%/night is a
bug until proven otherwise — check the pricing model before believing it.

**Follow-up 10-15 — "how much would we win over the past month?"** (`research/lottery_month.py`,
54 names, $100/ticket, buy 1.5σ-OTM 1-DTE at each close, sell at next open, corrected pricing):

| | tickets | spent | P/L | per ticket | 5x+ hits |
|---|---|---|---|---|---|
| puts, past month (incl. the 10-15 crash) | 1,242 | $124,200 | **−$45,588** | −36.7% | 20 |
| calls, past month | 1,242 | $124,200 | −$38,225 | −30.8% | 15 |

The 10-15 open alone made +$6,931 on the put tickets; without it the month is −$52,519. Over
2 years, puts were profitable in **2 of 23 months** (Jan 2025, the Apr 2025 tariff crash),
calls in 5 of 23. The user's own option charts showed the same thing on their left side:
each winning contract had decayed to $0.01-0.75 on the days before. Caveat: model prices,
not real quotes — the moomoo chain is the only way to confirm.

**Follow-up 10-15 — "do the opposite: buy the bounce after the CPI selloff?"**
(`research/bounce_bt.py`, 27 names, 2y daily). The underlying DOES drift up after
selloffs: after SMH ≤ −3% days (43 events), names averaged +2.9% over 5 days (72% of
events higher) vs +1.5% on any day — but only 51% were higher after 3 days, i.e. the
bounce is slow and choppy, not a snap-back. Calls do not capture it: a 0.2σ 2-week
call bought at the selloff close (+50/−50, 4% friction) averaged −5.6% (median −54%)
vs −3.9% for a call bought on any day; name ≤ −4% days −4.2%. Elevated vol makes the
calls dearer and the −50% stop gets hit on the chop first. Same verdict as the gate
test: no edge either way, so the counter-trend gate stays. The 2y window is a bull
market — the "+2.9%" partly IS the bull market.
Intraday version, same day (`research/bounce_dt.py`, 21 names, 40 sessions of 5m bars,
v2 vehicle/exits, 4% spread) — calls on DOWN-3d names, i.e. the ones the gate blocks:
the gate-blocked ORB breakouts averaged −7.2% (23% win) vs −4.2% for the calls the gate
allows, so the gate is earning its keep. "Anticipating" earlier does not fix it: VWAP
reclaim −4.8%, buy at 10:00 −3.5%; on gap-down mornings buy-at-10:00 was +1.9% IS but
−4.8% OOS (n=46; sector gap-down mornings n=27, +4.2% IS / −5.7% OOS) — fails the
both-halves rule. No bounce entry adopted.
**User pushback: "don't use time, use all the information" — tested (`research/bounce_ml.py`).**
615 bounce-candidate name-days (down 3d or gap ≤ −1%), every 5m bar 10:00-14:30 a decision
point (33,825), 16 features: gap, return from open, distance off the low (σ), range
position, gap-fill room, VWAP distance, last-30m return, relvol, last-30m volume surge,
3d decline, RSI, SMH from open + last 30m, relative strength vs SMH, bars since low,
higher-low count. Label = the actual v2 call trade from that bar. Walk-forward both ways
(train one half of sessions, test the other). **OOS AUC 0.51-0.57; buying the model's
top 10-20% bars averaged −2.7% to −5.3% vs −4.1% for the first bar of every candidate.**
Win rate rose (~29% → ~40%) but P&L did not. Most-used features: SMH from open, gap,
distance off the low — i.e. the sector's own move, which is the thing that is not
predictable. Same result as the 5-min direction work (AUC 0.512): the price/volume data
we have does not contain the bounce. What it lacks, and the moomoo chain would add:
option volume/IV skew, which is the next thing worth testing.

### "The exit is the issue — winners took days to flip" (user, 10-15) — exit grid
`research/exit_grid.py` + `exit_check.py`: entries FIXED (20d close-break trend signals,
all gates, 27 names, 2y daily, ~480 trades), only the exit varied, 5 expiry/strike combos.
**The user's observation is real:** 25-31% of entries peaked ≥ +200% at some point, median
5-19 days after entry (longer expiry → later peak), and **34-49% of those hit −50% first**
— the stop cut a third to a half of the eventual big winners before they flipped.
**But "just hold" is not the lesson.** Hold-to-expiry on 4-week 0.2σ looked like +33.6%,
and all of it is CALLS in the memory/AI up-cycle (memory +273%, top 10 trades = SNDK/MU/
STX/MRVL/NVTS calls at 9-20x); held PUTS lose −45% to −68%, non-memory names +6%, and
without the top 10 trades or with IV = RV × 1.15 (real IV sits above realized) it goes
negative. That is long beta on one sector's bull run, not an exit rule.
**What DID survive — a trailing exit instead of the fixed +50% target:** keep the −50%
stop; once the premium has been up +50%, exit if it falls 30% from its peak value. Better
than "+50% first touch" in BOTH halves in all five combos (1wk 0.2σ −10.7 → −2.8%; 2wk
0.2σ −10.6 → −1.5%; 4wk 0.2σ −6.3 → +7.0%; 1wk 1σ −17.9 → +2.2%; 2wk 1σ −15.2 → −2.1%).
It lets the multi-day flips run while still banking most of a round-trip. Executable from
GMT+8 as a resting trailing-stop order. **ADOPTED for swing/momentum 2026-10-15** on the
user's OK. Daily-bar test, stop checked before the trail — conservative.

### 1-DAY TICKETS on big-volume nights — PAPER-TRADED from 2026-10-29 (user: "they're low cost so they deserve a chance")
`research/lottery_event.py`: 27 names, 2022-26 daily (30,578 name-nights), ~1 daily-σ call + put
bought at the close, overnight-variance pricing + put skew, 10% friction, one bet per night.

| night (sell both at the next OPEN) | IV = RV | 1.15x | 1.3x | 1.5x |
|---|---|---|---|---|
| every night | −16.0% | −27.8% | −34.1% | −38.1% |
| FOMC nights (38) | +49.6% (IS +28.9 / OOS +70.3) | +16.7% (IS +2.2) | −1.4% | −15.0% |
| memory-peer nights (35) | +7.7% (IS −30.6 / OOS +43.9) | −11.3% | −21.7% | −29.3% |
| **volume > 1.5x AND range > 2 sd (561 nights)** | **+69.1%** (+71.7 / +66.4) | **+29.7%** | **+8.3%** | −1.6% |

A resting +100% limit through the next session instead of selling at the open is no better (+4% vs
+8% at 1.3x). Read honestly: break-even ≈ 1.4x RV30; the MEDIAN ticket loses ~47%; without the best
2% of nights the big-volume row is +12% at RV and −20% at 1.3x; calls carry it (2022-26 bull:
calls +131% mean / −64% median, puts +25% / −73%). Real 1-DTE IV after a big day is UNMEASURED and
probably above RV30 (RV lags) — the forward test exists to find out. Engine `research/lottery_engine.py`
(15:50 ET, after trend-hold): trigger = volume > 1.5x AND range > 2 sd (FOMC alone is not a trigger),
1 contract each of the ~1σ call + put expiring NEXT session — DAILY-expiry names (assumed: NVDA,
AAPL, MSFT, AMZN, META, GOOGL, MU — confirm on moomoo) any night, others only Thursday night → Friday;
pair ≤ $300, max 3 names/night, blocked on earnings today/next session; sold at the 09:30 ET open.
`strategy=lottery`, `book=paper`, separate stats. Ask the user for a real quote on each entry.
Review at 20 nights: compare real quoted IV with RV30 — if real IV ≥ ~1.4x RV, stop it.
Note: the backtest's big nights were mostly weekly-only names (CRDO/STX/NVTS/COHR/DELL/SMCI); the
expiry restriction means the live sample is smaller and tilted to mega-caps.

## Parked idea — cheap same-day "lottery" calls (needs a real chain to test)

**2026-10-07, MU:** the user's broker showed the MU 1080 call expiring that day
(`MU261007C01080000`) at **$0.06 near the 09:31 ET low ($1,011.42)**; MU then rallied
+6.9% to $1,080.88 by 12:06 and the contract traded ~**$5 (~80x)**. Base rates from
the last 60 sessions of 5m bars: MU's high after 10:00 was ≥ +4% above its 10:00
price on 7 days (12%), ≥ +5% on 5 days (8%). A daily far-OTM 0DTE ticket that pays
~80x once or twice a month COULD be positive-expectancy — but strike and timing here
are hindsight, the open-direction model is a coin flip (AUC 0.514), and real quotes
on these strikes are often $0.05/$0.10 (a 100% spread). Black-Scholes at RV cannot
price them. **Do not trade it or claim it; test it only with real 0DTE quotes**
(moomoo chain). Needed: historical intraday option prices for far-OTM 0DTE strikes
— if the moomoo API cannot serve history, start logging opening quotes daily from
the VPS and test forward once ~40 sessions exist.

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
- Until then all paper fills are model-priced (Black-Scholes on realized-vol proxy)
  — treat every paper premium as an estimate, not a quote.

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

**Trade reports (user request 2026-10-06):** every entry, exit and book summary
shows the **entry date + stock price + premium** and the **exit date + stock price +
premium**, not just the P&L %. `exit_ts` is the time the RULE fired (e.g. 15:45 ET),
never the time the row was logged.

OCC format: `{ROOT}{YYMMDD}{C|P}{strike×1000, zero-padded to 8 digits}`.
Example: BKNG $192.50 call expiring 2026-07-03 → `BKNG260703C00192500`.

## Session routine (always)

Before giving new analysis, **review the standing positions / prior
recommendations** and report how each has moved (fresh price, IVR, trend, DTE,
in/out of the money, thesis-still-valid?). Open positions to track are kept in
the `recommendations` / `positions` journal (see `journal/`). Never give new
picks without first re-checking the old ones.

**Book persistence.** The journal DB is gitignored and ephemeral; the durable book
is `data/recommendations.csv`. **The container can silently reset mid-conversation**
(this has happened repeatedly — local git state and the local DB both revert to an
old point with no warning). Because of this, treat "session start" as **"immediately
before every single book write, no exceptions"**, not literally once per chat:

1. `git fetch` + `git merge --ff-only` (or resolve conflicts) the working branch
   BEFORE reading or writing the book — confirm the local commit hash actually
   matches origin, don't assume it does. **Then immediately push the merge
   result back**, even though it contains none of your own work:

   ```
   git fetch origin
   git merge --ff-only origin/claude/planning-session-ipr02p
   git push origin claude/available-branches-2999s4      # do NOT skip this
   git rev-parse HEAD origin/claude/available-branches-2999s4 \
       origin/claude/planning-session-ipr02p             # all three must match
   ```

   Why the push is part of the sync and not an afterthought: the cron commits
   its snapshots to the CANONICAL branch only. Merging pulls those into the
   working branch, which leaves the working branch ahead of its own remote by
   commits you did not author — so the Stop hook fires "N unpushed commits" at
   the end of the turn and the sync has to be redone. This recurred on three
   consecutive sessions (2026-09-14, 09-15, 09-16) before being folded in here.
   Finish the sync with all three refs equal, every time.
2. `python -c "from journal.research_log import ResearchLog as R; R().import_recommendations()"`
   — re-run this immediately before EVERY `add_recommendation`/`close_recommendation`
   call, even if you imported earlier in the same reply. A stale local DB will
   silently accept the write and then `export_recommendations()` will overwrite the
   correct CSV with regressed data (lost closures, resurrected "open" positions).
3. After the write: export, `git add`/commit/push to BOTH branches, then verify by
   printing the full CSV/DB row list — don't just trust "N recs exported" as proof
   the state is correct.
4. The daily cron must NOT export this file (its DB is fresh and would clobber the
   book).

**Timezone.** User is in Singapore (GMT+8). Precise timestamps (`scan_ts`, `entry_ts`,
`exit_ts`) are recorded in **SGT with an explicit `+08:00` offset**. Date-key fields
(`scan_date`, `created_date`, `exit_date`) stay on the **UTC calendar date** (≈ the US
trading date for US-session scans), so a post-close scan can read e.g. `scan_date=06-30`
with `scan_ts=07-01T06:47+08:00` — same US session, shown in local time.

## Trading lessons (do not repeat)

### AVGO specifically is a proven whipsaw trap — extra scrutiny required
Two separate paper puts on AVGO have now been stopped out (2026-07-21 at -59%,
2026-08-06 at -85%), both times because AVGO kept climbing right through the
stop despite a technically clean bearish setup on entry. This name has
repeatedly shown conflicting bull/bear signals on the same scan day and a
pattern of recovering hard against whatever position was taken. Before
re-entering AVGO in either direction: require BOTH a decisive score gap
(not a close call) AND confirmation the move has actually started on the
live tape — a clean scan score alone has twice been insufficient here.

### The whipsaw check — run it on EVERY directional entry, before recommending
The AVGO rule above is reactive: AVGO earned a named rule only after two
stop-outs. This check catches the next AVGO *before* the first loss, by
measuring two-way volatility instead of maintaining a list of bad names.

Over the last **30 sessions**, compute for the candidate:
- count of days **> +5%** vs count of days **< -5%**
- average absolute daily move
- how many 5-day windows in the last ~40 sessions contained an **> 8% rally**

**Reject the trade if the up-day and down-day counts are within ~1 of each
other**, regardless of how clean the scan score is. A name with as many big
up days as big down days has no directional edge — a directional premium buy
there is a coin flip with wide dispersion, and the stop gets hit by noise
before the thesis can resolve.

**What it caught (2026-09-14, COHR):** COHR looked like the best bearish swing
put on the board — widest bull/bear score gap (14 vs 0), RSI 44 (genuinely NOT
oversold), 1.84x volume, a real name-specific story (AI-photonics correction
from a $440 high), earnings confirmed clear. Every convergence leg passed. The
whipsaw check killed it: **7 up-days >+5% vs 6 down-days >-5%**, avg |daily|
5.1%, biggest up day +13.4%, and **15 of the last 40 five-day windows contained
an >8% rally**. That is chop, not a downtrend. Withdrawn before entry.

**Threshold (corrected 2026-09-14):** flag as chop only when
`(up5 + down5) >= 4 AND |up5 - down5| <= 1`. The activity floor matters — the
first version omitted it and rejected MSFT/TSM/AMZN/AAPL at 0up/0dn, which are
the *calmest* names on the board, not whipsawing ones. Implemented in
`analysis/harvest.py:whipsaw_stats`.

**Validated against the book:** of 26 closed trades the gate flags 6, and **all
six lost** (avg −64.0%); the 20 survivors won 30% at −7.2% avg. It also lifts
P(ITM)'s discrimination among survivors from AUC 0.767 to **0.833** — the gate
and the metric are complementary, not competing.

Reference readings from that same day, for calibration:

| | up>5% | down>5% | avg abs | verdict |
|---|---|---|---|---|
| COHR | 7 | 6 | 5.1% | reject — coin flip |
| VRT  | 1 | 4 | 3.1% | acceptable — directional |
| MPWR | 0 | 3 | 2.1% | clean trend |

Note the RSI subtlety this surfaced: a name can show a healthy non-oversold RSI
precisely *because* it keeps ripping counter-trend rallies. COHR's RSI 44 was
earned by a +15.5% six-session bounce that it gave back in one day. **A reset
RSI is only bullish for a short if the reset came from time/consolidation, not
from a violent counter-rally** — check which one produced it.

### Strike distance is the biggest single lever — and 1σ was too far
Measure moneyness in SIGMA units, `|ln(K/S)| / (RV·√T)`, never in percent. "2%
OTM" means nothing when RV ranges from 21% (MSFT) to 129% (NBIS) across the
watchlist — the same 2% is a coin flip on one and a lottery ticket on the other.

Every closed trade in the book, bucketed by sigma-moneyness at entry:

| bucket | n | win rate | avg PnL |
|---|---|---|---|
| 0.0-0.4σ | 3 | 33% | **+46.6%** |
| 0.4-0.7σ | 11 | 27% | −7.4% |
| 0.7-1.0σ | 9 | 22% | −45.1% |
| **>1.0σ** | 10 | **0%** | **−79.6%** |

Perfectly monotonic, and **>1σ is 0-for-10.** Winners averaged 0.60σ, losers
0.95σ. Combined with the whipsaw gate (σ<0.7 AND not chop): **n=10, 40% win,
+31.1% avg** — the first positive-expectancy subset found in the whole book,
against −63.2% for everything else.

**This invalidated the old "default to the 1σ strike" rule**, which had been
applied to every weekly list produced this week — i.e. every one of them was
priced in the 0-for-10 bucket. Use **0.3-0.6σ**. It costs 2-4x more per
contract; size down rather than strike out.

**Caveat, stated honestly:** the +31.1% average rests on NBIS +333% and AVGO
+300%; the median of that bucket is still −42.3%. This is a fat-tailed
"a few big winners pay for many small losers" profile, which is what long
premium should look like — and it only works if the +50% harvest is actually
executed as a resting order. Strike selection and exit discipline are the same
trade.

### The counter-trend check — never fade a live bounce (validated 2026-09-18)
Structure and RSI gates are both blind to short-term counter-trend momentum. A
name can be in a clean downtrend, not oversold, not choppy — and still be three
days into a bounce that runs further. Buying a put into that is the 2026-06-29
error, and the whipsaw gate does not catch it.

**The rule:** reject a PUT if the trailing 3 sessions are net POSITIVE; reject a
CALL if net NEGATIVE. Implemented in `analysis/harvest.py:counter_trend`.

**Validated on the 33-trade book:** 3d>0% flags 11 entries and **all eleven
lost** (avg −70.4%). **No winner is flagged at ANY tested threshold** (2d/3d/5d
× 0/1/2/3%) — it is close to a pure loser-filter. Combined with the whipsaw gate:

| | n | win rate | avg PnL |
|---|---|---|---|
| whipsaw gate alone | 27 | 22% | −28.1% |
| **both gates** | 21 | **29%** | **−12.3%** |
| fails either | 12 | **0%** | −73.7% |

**What it caught (2026-09-18, AVGO):** AVGO ranked #1 on the weekly list at
39.7% P(ITM) — passed whipsaw (0up/1dn), passed RSI (43.4), sat −6.4% below
MA50. But it had bounced +4.8% in three sessions off a defended 20-day low at
$335.81, with RSI 44 leaving room to run up. The user asked "why can't Broadcom
climb?" and the answer was: it already was. The put was fading a live bounce.

**The wider catch mattered more than the name.** Re-gating the whole board that
day rejected EVERY put — AVGO, VRT, ASML, NVTS, MPWR, WDC, CRDO, AMZN — because
the entire complex had bounced 2-16% in three days. The top recommendation (VRT,
0up/4dn, the cleanest directional profile measured all week) was +6.41% over
three sessions. An entire recommendation set was fading one market-wide rally
and nothing in the existing gates saw it.

### Exits are worth far more than entry scoring (validated 2026-09-14)
Reconstructed daily premium paths for all 26 closed trades, held every entry
decision fixed, and varied ONLY the exit rule:

| exit rule | avg PnL | win rate | median |
|---|---|---|---|
| what we actually did | −47.3% | 12% | −68.0% |
| +50% on first touch | −24.6% | 31% | −39.1% |
| +75% on first touch | −29.1% | 23% | −47.3% |
| +50% target, cut day 2 if red | −16.4% | 31% | −13.6% |
| +50% target, −50% stop | **−10.5%** | 31% | −39.1% |

**37 percentage points from exits alone, with zero changes to entries.**
**8 of 26 trades touched +50% but only 3 were booked as winners — five
round-trips were handed back.** The "harvest strength" rule already existed and
simply was not being executed. Before spending more effort on entry selection,
execute the exit rules; that is where the measurable money is.

Note this does NOT make the system profitable — the best rule is still −10.5%
average. Entries remain bad. But no entry-scoring tweak tested so far moves the
number anywhere near this much.

### The exit rules proved out LIVE, not just in backtest (2026-09-14 → 09-17)
Seven Sep18 weeklies were logged as `watch` on 09-14 to make a skip call
falsifiable. Resolved 09-17 at the 2-DTE time-stop: **$1,156 → $92, −92.0%.**
The skip call was right.

**But it was right for the wrong reason, and that is the lesson.** Two of the
seven were genuine winners at their peak:

| | peak | at close | |
|---|---|---|---|
| AMZN P250 | **+334.9%** | −34.6% | round-tripped from deep ITM |
| AVGO P335 | **+103.4%** | −99.1% | round-tripped to near zero |

Both cleared the +50% harvest threshold days before expiring worthless. Apply
the recalibrated rules (+50% first touch / −50% stop) to the SAME seven entries
and the basket returns **−33.3% instead of −92.0% — 59 percentage points from
exit discipline alone, with zero entry changes.** This is the backtest finding
reproducing in live data within three days of being written down.

What actually happened: FOMC on 09-16 hiked 25bp to 3.75–4.00% (12–0) with a
hawkish dot plot (16 of 18 expecting another hike). Stocks sold off on the
decision — puts worked — then reversed hard on 09-17 (QQQ +1.68%, SMCI +8.7%,
MU +5.7%), which killed every put. **A two-day window contained both the win
and the total loss.** Nothing about entry selection could have captured that;
only an exit rule could.

**Operative rule:** the +50% harvest is not advice, it is a RESTING LIMIT ORDER
placed at entry. The user is GMT+8 — AMZN's peak and its round-trip both
happened while they were asleep. A harvest that depends on watching the tape is
not a rule, it is a wish.

### Rejected experiment — do not rebuild: P(harvest) replacing P(ITM)
Hypothesis (2026-09-14): P(ITM) asks the wrong question for someone who always
sells before expiry, so replace it with "probability the premium spikes +50%
within 3 days" (block-bootstrapped paths, leverage effect modelled). Backtested
against all 26 labelled trades: **AUC 0.525 vs P(ITM)'s 0.767** — barely better
than a coin flip, and much worse than the metric it was meant to replace.

It fails because it systematically overscores cheap far-OTM contracts on
volatile names: a low entry premium makes +50% cheap to touch, and high vol
makes it touchable in BOTH directions. VST C190 scored 0.418 (near the top) and
lost 100%; HLT C375 scored 0.344 and lost 57%. **P(ITM) stays as the primary
discrimination metric.** Do not rebuild this without new evidence.

The general lesson: a plausible narrative about a metric being "the wrong
question" is a hypothesis, not a finding. Backtest it against the labelled book
before shipping it — the same convergence standard the DELL rule demands.

### Week of 2026-09-21 → 09-25 (MU): what was missed, and what was actually a mistake
The user flagged missed opening spikes: **MU260925C01100000 on 09-25** and
**MU260925C01120000 on 09-23**. Both are real in hindsight. Model reconstruction
(BS at RV 55%, entry at the open print):

| date | contract | spike | then |
|---|---|---|---|
| 09-25 | C1100 (0DTE) | **+53% at 09:35** (5 min in) | −60% by 10:21 |
| 09-25 | C1110 (0DTE) | +61% at 09:35 | −65% by 10:21 |
| 09-23 | C1120 (2DTE) | +13% at 09:30 (first-minute high) | −53% by 10:27 |
| 09-24 | C1062 (1DTE) | +32% at 09:47; **+72% by the close** | blocked by counter-trend |

The model shows the 09-23 C1120 spike as only +13% — the user saw a larger one on
the real chain. That gap is itself a finding: **the Black-Scholes-at-RV proxy
cannot see opening IV behaviour.** Until the moomoo chain is live, opening-spike
sizes from this system are understated and unverifiable.

**Is the opening spike a missed SIGNAL, or hindsight? Backtested before writing
a rule** (609 name-days, 21 focus names, 29 sessions 08-17→09-25, 2-min bars;
buy the 0.3σ Friday weekly at the close of the first 2-min bar, resting +50%
limit, −30% stop, 10:00 time-stop; conservative same-bar fills):

| entry condition | n | win | avg | median |
|---|---|---|---|---|
| calls, every open | 609 | 46% | +2.4% | −3.1% |
| gap up >0.5% + first bar up | 121 | 45% | +3.5% | −4.6% |
| gap up, within 2% of 20d high (the 09-25 setup) | 33 | 48% | +3.8% | −1.3% |
| puts, every open | 609 | 44% | +0.3% | −3.6% |
| straddle (both legs) | 609 | 47% | +1.3% | −0.4% |
| MU calls only | 29 | 48% | +4.7% | −1.7% |

**Zero-expectancy before friction, negative after it:** calls go to −1.6% with a
4% round-trip spread and −5.6% at 8% — and opening spreads on weeklies are often
wider than that. The spike is real and frequent (calls touch +50% on 21% of
opens, puts on 15%) but **it never happened on both sides the same day, and no
feature tested at 09:32 — gap direction, first-bar direction, proximity to the
20-day high — predicts which side.** The two named misses were drawn from a
population where the symmetric trade touched just as often. On MU this week the
blind rule would have gone +50/+50 on 09-22/09-25 and −8/−9/−3 on the other
three days: a good week, from a rule that is flat over 60 days.

**Do not build an "opening-spike scalp" rule** without new evidence — and the
evidence that would justify it is a real opening chain (moomoo), not this model.

**What WAS a mistake this week — keep these:**
1. **Confirmation structurally arrives after the opening harvest window.** On 09-23
   and 09-25 MU spiked into the 20-day high, and the "break" peaked within 1-9
   minutes then round-tripped −53% to −65%. The confirmation rule correctly
   refused to chase both — but on a gap-up into a level, *the confirmation print
   was the top.* Waiting for break-and-hold is right for entries; it is not a way
   to capture opens, and nothing should be claimed otherwise.
2. **The counter-trend gate flipped sides three sessions running** (3d +11.98% →
   −4.25% → +3.32%). A 3-day lookback on a 54%-RV name is too short to be stable;
   it blocked the 09-24 call (+72%) purely on the flip. Phase 2: test a longer
   lookback or an RV-scaled threshold before trusting it on high-vol names.
3. **Gate scoreboard, three blocked MU puts:** 09-22 would have won, 09-23 would
   have won (touched +50%), 09-24 lost 100%. 1-for-3. The separating variable was
   *which side volume confirmed* (09-24 volume confirmed the upside at 1.10x+).
   That directional-volume test is the Phase 2 hypothesis — not loosening gates.
4. **The one harvest that WAS available went unexecuted.** The 09-23 P1075
   touched +50% at 10:23 ET for one five-minute bar, then decayed to +12%. Same
   lesson as the 09-14 basket: without a resting limit placed at entry, a +50%
   print is not realisable from GMT+8.
5. **Data/monitor errors (all caught, all fixed):** a stale daily feed reported
   MU "+3.66%" pre-market when it was −1.0% (always rebuild prior close from
   intraday bars); the monitor's premium baseline and emit-filter state both reset
   on 30-min re-arms, once mislabelling a genuine new low as "nothing to report"
   (both now persist to disk); and the 10-min volume rate reads ~1.00x by
   construction in the first ~10 minutes — **never report opening volume as
   confirmation until it is measured against the same window over 20 sessions.**

### Timing is forecastable, direction is not — the event radar (built 2026-09-27)
The user asked for a system to predict moves like MRVL's +5.8% gap after the
2026-09-16 FOMC and MU's +53% opening call spike on 09-25. Built and validated
walk-forward (each test period scored by a model fitted only on earlier data):

| model | data | OOS AUC | top decile vs base |
|---|---|---|---|
| overnight big gap UP (> 1 gap-sd) | 10y daily, 21 names | 0.597 | 20.9% vs 11.9% |
| overnight big gap DOWN | same | 0.578 | 14.8% vs 9.9% |
| open: call touches +50% in 1st hour | 2y hourly + pre-market | 0.585 | 36.1% vs 25.7% |
| open: put touches +50% | same | 0.612 | 41.9% vs 25.3% |
| **open: which side wins** | same | **0.514** | 52.7% vs 49.6% |
| **overnight: expected gap (direction)** | 10y | **rank-IC +0.022**, flips sign by year | top decile +0.26% vs bottom +0.10% |

**Big-move days are forecastable (volume, range, event nights drive it); which
way they break is not.** Up- and down-tail odds rise together on flagged days.
On the user's own examples: MRVL/MU 09-16 close scored 90th-93rd percentile for a
big gap up (it came); MRVL 09-17 open scored 90th percentile for a call spike (it
came); MU 09-25 open scored an ordinary 47th percentile (missed); the direction
lean was wrong on MU 09-24 and MRVL 09-21. Do not present the lean as a signal.

**Model option P&L on flagged nights is optimistic.** On nights the overnight
model flags, realized gaps run ~1.28x what RV30 implies; the real market prices
part of that in. Simulated overnight straddles showed +10% — treat that as a
pricing artifact until a real chain (moomoo) says otherwise. Underlying-move
probabilities are unaffected.

**FOMC nights (event-level, avg across names, one row per decision):** 2024-26
next open averaged **+1.22%, 73% up (n=22)** vs +0.22% on normal nights (p≈0.002
vs random nights). **2017-23: no effect (n=40).** Regime-dependent — the radar
flags it; it is not a rule. Forward-test it: log FOMC nights as `watch` rows.
Next decision on the schedule: **2026-10-28** (same evening as MSFT's report).

**Execution constraint:** the US close is 04:00 SGT, so the overnight trade needs
the user awake or a pre-placed order; the open radar (21:15-21:28 SGT) fits the
user's evening. **Use:** deciles 9-10 on the open radar = be ready with a resting
+50% limit on anything already held, and don't open fresh short-dated premium
into a flagged open without a plan for either direction.

### Do not generalise an exit rule from a single trade
On 2026-09-14 I proposed replacing the −50% premium stop with thesis-invalidation
stops for long-dated far-OTM structures, reasoning from MPWR alone (n=1), where
the stop fired two sessions before the thesis paid. The n=26 backtest above
contradicts it: the −50% premium stop produces the BEST average outcome of any
rule tested. **Keep the premium stop.** MPWR was the exception, not the rule,
and one painful trade is not evidence.

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
   fast + sized tiny. **Strike: 0.3-0.6σ.** (This previously said "default to the
   1σ strike" — corrected 2026-09-18, the data says 1σ is already too far out.)

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

### Overbought is not a short signal; bearish puts need a reason to FALL
**What happened (2026-06-30 → 07-01):** suggested AXP P305/P300 (short on RSI 79
"overbought") and COIN P115 (short on weak/oversold, −22% 1M). Held both as *watch*
(didn't take). The tape flipped risk-on and BOTH rose — AXP +2%, COIN +9% — so the
puts would have lost ~40–54%. The one bearish put actually TAKEN, CEG P230, won
+181%: CEG kept falling (−7%) on its own name-specific downtrend with LOW IVR, so
delta AND vega both worked (textbook premium-put).

**The rule going forward:**
1. **Overbought RSI ≠ short signal.** A firm name stays overbought and grinds higher;
   shorting extension is fighting momentum (AXP kept climbing).
2. **A bearish put needs a name-specific reason to FALL** — broken structure, a
   sustained downtrend, a catalyst — NOT just "it's extended" or "it's weak/oversold."
   Oversold names bounce (COIN), overbought names keep running (AXP).
3. **Check the broad tape.** Shorting into a risk-on rally needs a name diverging DOWN
   from the market (CEG did; AXP/COIN didn't). No divergence → no bearish premium.
4. The discipline that saved it: took only the highest-conviction put (CEG: LOW IVR +
   real downtrend), held the rest as watch. Quality over quantity separated the winner
   from the two would-be losers.

### Violent-vol names price badly for weekly premium buying
Names with extreme realized vol (e.g. MRVL, WDC, SMCI, STX at RV 90-160%) make
weekly OTM strikes near-worthless coin flips and ATM strikes very expensive — poor
risk/reward for a premium buyer. Prefer a LEAPS structure for these, not 4-DTE.

### What actually worked: DELL (2026-09-02) — investigate outliers, require convergence
DELL printed +8.5% on 1.34x volume while the rest of the board was flat-to-down —
the only fully volume-confirmed move seen in weeks. Instead of trusting the scan
score alone, the anomaly was investigated directly (WebSearch), which surfaced that
DELL had actually reported earnings the prior day (a real beat-and-raise: record
$47B revenue, $60.9B in new AI server orders, $95B backlog, guidance raised $25B) —
correcting a stale *estimated* earnings date that had been blocking this name from
recommendation for over a week. The recommendation only went out once multiple
independent signals converged: real volume (the hardest bar to clear all month),
a genuine fundamental catalyst (not just a technical flag), and RSI still with room
(41.6, not yet overbought despite the size of the move).

**Keep doing this on future trades, unless a specific use case says otherwise:**
1. **An outlier reading is a prompt to investigate, not a number to accept.** A move
   that stands out from the rest of the board (unusual volume, size, or divergence
   from the broader tape) means something real likely happened — go find out what
   via a fresh search before scoring it, rather than trusting a stale assumption
   (including this system's own prior earnings-date estimates).
2. **Never act on a single flag alone — require convergence.** Volume confirmation +
   a genuine fundamental catalyst + technical room (RSI not yet extended) together
   is what makes a recommendation real. Any one of these alone (a clean scan score,
   a news headline, an oversold reading) is not sufficient by itself.
3. **Re-verify "known" facts (especially estimated earnings dates) when the live data
   stops matching the story** — an assumption that blocked a name last week should be
   re-checked, not carried forward silently, once the tape contradicts it.
