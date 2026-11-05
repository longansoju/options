"""Paper 1-DAY TICKET ("lottery") engine (user 10-29: "be more accepting to such 1-day ticket bets.
they're low cost so they deserve a chance too").  Run once per session at ~15:50 ET, after
strangle_engine.py and trendhold_engine.py:  python lottery_engine.py
Evidence (research/lottery_event.py, 27 names, 2022-26, overnight-variance pricing, 10% friction):
every night the ~1-sigma call+put pair loses (-16% at IV=RV, -28% at 1.15x); on nights where the name
traded > 1.5x its 20-day volume AND a range > 2 daily sd, the same pair sold at the next OPEN was
+69% per night at IV=RV, +8% at 1.3x, -2% at 1.5x (IS/OOS alike) - but the median ticket loses ~47%,
and without the best 2% of nights it is +12% at RV / -20% at 1.3x. Break-even is ~1.4x RV30, and real
1-DTE IV after a big day is unmeasured: that is what this forward test exists to measure.
  1. EXIT: tickets bought at the previous close are sold at today's OPEN (the rule's exit; exit_ts =
     09:30 ET), valued at the open with the session's variance still to come.
  2. ENTER: today's volume (scaled to a full day) > 1.5x the 20-day average AND today's range >
     2 x the 20-day sd of daily returns (FOMC nights alone are NOT a trigger: +2% IS at 1.15x, -12% IS
     at 1.3x - too thin). Only when tomorrow is an expiry
     for that name (DAILY names: any night; others: Thursday night -> Friday expiry). ~1 daily-sigma
     call + put, 1 contract each, pair <= $300, max 3 names/night ranked by volume x range.
     Blocked: earnings today or next session (IV on a print night is far above RV - model meaningless).
Run `python lottery_engine.py exits` at ~09:35 ET to price/book the open exits early (frees November cash).
From 11-04 fills use the REAL Yahoo chain (analysis/option_quotes.py): buy at the ask, sell at the bid, IV and
IV/RV30 logged; the model (call IV = RV30, put IV = RV30 x 1.15 skew) is the fallback only when no quote exists."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from analysis import bankroll   # November $1,000 cash book (user 11-01)
from analysis import option_quotes as oq   # 11-04: real fills - buy at the ASK, sell at the BID (Yahoo, ~15m delayed)
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
DAILY = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'MU'}   # assumed daily expiries - confirm on moomoo
EARN = {k: dt.date.fromisoformat(v) for k, v in config.DAYTRADE_EARNINGS.items()}
PAIR_MAX, MAXN, SKEW = 300.0, 2, 1.15   # 11-01: max 2 pairs/night, each <= 10% of November equity (bankroll.py)
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    T = max(T, 1e-7); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
def inc(S): return 10.0 if S >= 1000 else 5.0 if S >= 500 else 2.5 if S >= 100 else 1.0 if S >= 25 else 0.5   # 10-30: $5 grid at $200-500 put NVDA tickets at ~1.8 sigma


def run(exits_only=False):
    now = pd.Timestamp.now(tz='America/New_York'); today = now.date()
    nxt = pd.Timestamp(np.busday_offset(today, 1, roll='forward')).date()
    book = pd.read_csv('/home/user/options/data/recommendations.csv')
    openr = book[(book.strategy == 'lottery') & (book.status == 'open') & (book.book == 'paper')]
    for _, r in openr.iterrows():                                     # ---- exits at today's open
        if dt.date.fromisoformat(r.created_date) >= today: continue
        d = er.daily_frame(r.symbol, '3mo').dropna(); O = float(d.O.iloc[-1])
        rv = float(r.thesis.split('RV30 ')[1].split('%')[0]) / 100; f = float(r.thesis.split('overnight share ')[1].split(' ')[0].rstrip('.,;|'))
        iv = rv * (SKEW if r.direction == 'put' else 1)
        p = bs(O, float(r.strike), (1 - f) / 252, iv, r.direction) * 100
        if now.time() < dt.time(9, 45): print(f"   (warning: {now:%H:%M} ET - the ~15m-delayed chain still shows PRE-OPEN quotes; run exits at >= 09:46 ET)")
        q = oq.fill(r.occ_code, 'sell', O, S_quote=O, rv=rv, T=(1 - f) / 252, patient=True, spot_at_age=lambda m_, s_=r.symbol: oq.spot_at(s_, m_))
        src = f"REAL BID ${q['prem']:.0f} [{q['note']}]" if q else f"NO QUOTE - model price (flag price_source=model)"
        px = q['prem'] if q else p
        print(f"*** LT EXIT {r.occ_code} | {r.symbol} open {O:.2f} | ${px:.0f} vs entry ${r.entry_premium:.0f} ({px / r.entry_premium - 1:+.0%}) | sold at the 09:30 ET open | model ${p:.0f} | {src}")
    if exits_only: print('   ' + bankroll.summary() + ' (before booking these exits)'); return
    fomc = today in er.FOMC_DATES
    exp_ok = lambda s: s in DAILY or nxt.weekday() == 4
    cands = []
    mins = max(16 * 60 - (now.hour * 60 + now.minute), 0)
    for s in SYMS:
        try: d = er.daily_frame(s, '1y').dropna()
        except Exception as e: print(f"   skip {s}: {str(e)[:40]}"); continue
        c = d.C; r1 = c.pct_change(); sd20 = float(r1.iloc[-21:-1].std())
        volx = float(d.V.iloc[-1]) * 390 / max(390 - mins, 1) / float(d.V.iloc[-21:-1].mean())
        rng = (float(d.H.iloc[-1]) - float(d.L.iloc[-1])) / float(c.iloc[-1]) / sd20
        big = volx > 1.5 and rng > 2
        if not big: continue
        cc = np.log(c / c.shift(1)); gp = np.log(d.O / c.shift(1))
        f = float(np.clip((gp ** 2).tail(250).mean() / (cc ** 2).tail(250).mean(), 0.05, 0.9))
        rv = float(cc.tail(30).std() * math.sqrt(252)); S = float(c.iloc[-1])
        why = []
        if not exp_ok(s): why.append(f'no expiry on {nxt} (weekly-only name, not a Thursday night)')
        if s not in EARN: why.append('no verified earnings date')
        elif today <= EARN[s] <= nxt: why.append(f'earnings {EARN[s]}')
        cands.append((volx * rng, s, S, rv, f, volx, rng, big, why))
    cands.sort(reverse=True)
    print(f"[{now:%H:%M}ET] 1-day ticket scan | FOMC day: {fomc} | candidates: " + (', '.join(f"{s} vol {vx:.1f}x rng {rg:.1f}sd" for _, s, _, _, _, vx, rg, _, _ in cands[:8]) or 'none'))
    n = 0; spent = 0.0
    for _, s, S, rv, f, volx, rng, big, why in cands:
        tag = f"{s} {S:.2f} | vol {volx:.2f}x range {rng:.1f} sd{' | FOMC' if fomc else ''} | RV30 {rv:.0%} | overnight share {f:.2f} "
        if why: print(f"   LT signal {tag}REJECTED: {'; '.join(why)}"); continue
        if n >= MAXN: print(f"   LT signal {tag}SKIPPED: max {MAXN}/night"); continue
        S, age = er.live_price(s)   # 11-02: daily_frame's last bar was ~30 min stale on 10-30 (NVDA 202.90 vs 204.75)
        T = (mins / 390 + 1) / 252; sdv = rv * math.sqrt(1 / 252); st = inc(S)
        Kc = oq.snap(s, nxt, math.ceil(S * math.exp(sdv) / st) * st, 'up'); Kp = oq.snap(s, nxt, math.floor(S * math.exp(-sdv) / st) * st, 'down')   # listed strikes (11-05)
        mc, mp = bs(S, Kc, T, rv, 'call') * 100, bs(S, Kp, T, rv * SKEW, 'put') * 100
        occ = lambda k, K: f"{s}{nxt.strftime('%y%m%d')}{k}{int(round(K * 1000)):08d}"
        Sq = oq.spot_at(s) or S   # the delayed quote was made against the spot ~15 min ago
        qc, qp = oq.fill(occ('C', Kc), 'buy', S, Sq, rv=rv, T=T, patient=True, spot_at_age=lambda m_, s_=s: oq.spot_at(s_, m_)), oq.fill(occ('P', Kp), 'buy', S, Sq, rv=rv, T=T, patient=True, spot_at_age=lambda m_, s_=s: oq.spot_at(s_, m_))
        pc, pp = (qc['prem'] if qc else mc), (qp['prem'] if qp else mp)
        src = lambda q, m: (f"REAL ASK [{q['note']}] IVbid {q['iv_bid'] or q['iv_ask'] or 0:.3f}" if q else f"NO QUOTE - model ${m:.0f} (flag price_source=model)")
        cap = min(PAIR_MAX, bankroll.budget('lottery', unbooked=spent))
        if pc + pp > cap: print(f"   LT signal {tag}REJECTED: pair ${pc + pp:.0f} at the ask > ${cap:.0f} (November book: 10% of equity, within cash) | model pair ${mc + mp:.0f}"); continue
        print(f"*** LT ENTRY {tag}| CALL {occ('C', Kc)} ${pc:.0f} + PUT {occ('P', Kp)} ${pp:.0f} = ${pc + pp:.0f} | sell both at the {nxt} open | spot = live 1m print {S:.2f}, {age:.0f} min old"
              f"\n      call: {src(qc, mc)}\n      put:  {src(qp, mp)}")
        n += 1; spent += pc + pp
    if n == 0: print('   no 1-day tickets tonight')
    print('   ' + bankroll.summary())


if __name__ == '__main__':
    run(exits_only=len(sys.argv) > 1 and sys.argv[1] == 'exits')   # 'exits' at ~09:35 ET frees the cash before 10:00 day trades
