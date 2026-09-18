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
  mean-reversion risk, size tiny, 1σ strike on weeklies.
- **Honest pricing caveat.** No live chain — paper fills are Black-Scholes at the
  realized-vol proxy, with NO slippage or spread. A paper edge must be robust enough
  to survive real friction; paper validates direction/timing, not exact premium.
- **Book separation.** `recommendations.book` = `real` (user's actual fills) |
  `paper` (Claude's trades) | `watch` (pending-trigger candidates).
- **Exit rules (recalibrated 2026-09-14 against the 26-trade book).** BOTH
  strategies: **+50% target on FIRST TOUCH** / −50% stop / **cut on day 2 if the
  position is red** / swing also exits by 21 DTE, momentum by 2 DTE or EOD.
  Every exit → a labeled outcome. The +50% target replaced swing's old +75%:
  backtested, +75% gives back more than it captures (−29.1% vs −24.6% avg).
  Because the user is GMT+8 and the US session runs overnight, the harvest must
  be a **resting limit order**, not a discretionary decision made in real time.
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
