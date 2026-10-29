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
Model-priced (call IV = RV30, put IV = RV30 x 1.15 skew); ask the user for real quotes to log IV."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
DAILY = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'MU'}   # assumed daily expiries - confirm on moomoo
EARN = {k: dt.date.fromisoformat(v) for k, v in config.DAYTRADE_EARNINGS.items()}
PAIR_MAX, MAXN, SKEW = 300.0, 3, 1.15
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    T = max(T, 1e-7); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
def inc(S): return 10.0 if S >= 1000 else 5.0 if S >= 200 else 2.5 if S >= 100 else 1.0 if S >= 25 else 0.5


def run():
    now = pd.Timestamp.now(tz='America/New_York'); today = now.date()
    nxt = pd.Timestamp(np.busday_offset(today, 1, roll='forward')).date()
    book = pd.read_csv('/home/user/options/data/recommendations.csv')
    openr = book[(book.strategy == 'lottery') & (book.status == 'open') & (book.book == 'paper')]
    for _, r in openr.iterrows():                                     # ---- exits at today's open
        if dt.date.fromisoformat(r.created_date) >= today: continue
        d = er.daily_frame(r.symbol, '3mo').dropna(); O = float(d.O.iloc[-1])
        rv = float(r.thesis.split('RV30 ')[1].split('%')[0]) / 100; f = float(r.thesis.split('overnight share ')[1].split(' ')[0])
        iv = rv * (SKEW if r.direction == 'put' else 1)
        p = bs(O, float(r.strike), (1 - f) / 252, iv, r.direction) * 100
        print(f"*** LT EXIT {r.occ_code} | {r.symbol} open {O:.2f} | ~${p:.0f} vs entry ${r.entry_premium:.0f} ({p / r.entry_premium - 1:+.0%}) | sold at the 09:30 ET open")
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
    n = 0
    for _, s, S, rv, f, volx, rng, big, why in cands:
        tag = f"{s} {S:.2f} | vol {volx:.2f}x range {rng:.1f} sd{' | FOMC' if fomc else ''} | RV30 {rv:.0%} | overnight share {f:.2f} "
        if why: print(f"   LT signal {tag}REJECTED: {'; '.join(why)}"); continue
        if n >= MAXN: print(f"   LT signal {tag}SKIPPED: max {MAXN}/night"); continue
        T = (mins / 390 + 1) / 252; sdv = rv * math.sqrt(1 / 252); st = inc(S)
        Kc = math.ceil(S * math.exp(sdv) / st) * st; Kp = math.floor(S * math.exp(-sdv) / st) * st
        pc, pp = bs(S, Kc, T, rv, 'call') * 100, bs(S, Kp, T, rv * SKEW, 'put') * 100
        if pc + pp > PAIR_MAX: print(f"   LT signal {tag}REJECTED: pair ${pc + pp:.0f} > ${PAIR_MAX:.0f}"); continue
        occ = lambda k, K: f"{s}{nxt.strftime('%y%m%d')}{k}{int(round(K * 1000)):08d}"
        print(f"*** LT ENTRY {tag}| CALL {occ('C', Kc)} ~${pc:.0f} + PUT {occ('P', Kp)} ~${pp:.0f} = ${pc + pp:.0f} | sell both at the {nxt} open")
        n += 1
    if n == 0: print('   no 1-day tickets tonight')


if __name__ == '__main__':
    run()
