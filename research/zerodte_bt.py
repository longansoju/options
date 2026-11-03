"""User 11-03 (MU 261102 840P, $0.04 -> $10.48 on 11-02): same-day option on a CONFIRMED break.
The day-trade signal fired at 11:18 (MU put, 869.48) but the 2-week 0.2-sigma put cost ~$3,600.
Screen: every ORB signal from month_review.py (gates recorded) on the daily-expiry names, vehicle =
SAME-DAY expiry option, strike k x the remaining-session sigma OTM, BS at RV30 for the time left
(no smile, no intraday IV - a model screen only, real 0DTE quotes are the decisive test).
Exits: +100% / -50% / 15:45 (expiry is 16:00). 10% friction (0DTE spreads are wide).
IS/OOS halves by session, as in month_review."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
OUT = '/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/mr/'
R = pd.read_pickle(OUT + 'signals.pkl'); D = pd.read_pickle(OUT + 'data_merged.pkl')
STOP = "nostop" not in sys.argv
DAILY = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'MU'}
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    if T <= 0: return max(S - K, 0) if k == 'call' else max(K - S, 0)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
def tleft(t): return max(16 * 60 - (t.hour * 60 + t.minute), 0) / 390 / 252
rows = []
for r in R[R.sym.isin(DAILY)].itertuples():
    b = D[r.sym][0]; x = b[b.index.date == r.day]; ts = r.ts
    S0 = float(x.C.loc[ts]); T0 = tleft(ts + pd.Timedelta(minutes=5)); g = 1 if r.kind == 'call' else -1
    for k in (0.5, 1.0, 1.5):
        K = S0 * math.exp(g * k * r.rv * math.sqrt(T0)); p0 = bs(S0, K, T0, r.rv, r.kind)
        if p0 < 0.01: continue
        res = None
        for t, bar in x[x.index > ts].iterrows():
            T = tleft(t + pd.Timedelta(minutes=5))
            w = bs(bar.L if g == 1 else bar.H, K, T, r.rv, r.kind) / p0 - 1; bb = bs(bar.H if g == 1 else bar.L, K, T, r.rv, r.kind) / p0 - 1
            if STOP and w <= -0.5: res = -0.5; break
            if bb >= 1.0: res = 1.0; break
            if t.time() >= dt.time(15, 45): res = bs(bar.C, K, T, r.rv, r.kind) / p0 - 1; break
        if res is None: continue
        rows.append(dict(sym=r.sym, day=r.day, kind=r.kind, k=k, blocks=r.blocks, half=r.half, third=r.third, pnl=res - 0.10, prem=p0 * 100))
Z = pd.DataFrame(rows)
for k, g in Z.groupby('k'):
    print(f"\n=== same-day option {k} remaining-session sigma OTM (median ${g.prem.median():.0f})")
    for lab, m in (('all signals', g.index == g.index), ('passes today\'s gates', g.blocks.isin(['', 'budget'])), ('blocked by a gate', ~g.blocks.isin(['', 'budget']))):
        s = g[m]; i, o = s[s.half == 'IS'], s[s.half == 'OOS']
        th = ' '.join(f"{p} {x.pnl.mean():+.1%}({len(x)})" for p, x in s.groupby('third'))
        print(f"  {lab:24s} n={len(s):3d} win {(s.pnl > 0).mean():.0%} avg {s.pnl.mean():+6.1%} med {s.pnl.median():+5.0%} | IS {i.pnl.mean():+6.1%} OOS {o.pnl.mean():+6.1%} | {th}")
