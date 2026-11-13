"""User 11-13 (MU 261113 750P, $0.54 -> $5.90 by 10:21): "there has to be something we can study ... for stocks that
have high prices". Two PRE-SPECIFIED cuts of the same-day-option screen (zerodte_bt.py), no sweep:
  A. BREADTH: >= 3 OTHER names had already fired a same-direction ORB signal that day (11-13: nine chip names broke lows).
  B. PRICE: stock >= $300 vs < $300 (the "high-priced names" idea).
Vehicle: same-day option 1.0 remaining-session sigma OTM at the confirmed ORB signal, +100% / -50% / 15:45, 10% friction,
priced at IV = RV30 and at 1.3x RV30 (real short-dated IV has read 1.3-1.9x). All 26 names as if a same-day expiry
existed ("hyp"), and the subset where one really is listed (Fri: all; Mon/Wed: the 7 M/W/F names) ("listed").
Signals: month_review ORB signals 09-10 -> 11-04 (40 sessions), gates recorded not applied. Model screen only."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
OUT = sys.argv[1]
R = pd.read_pickle(OUT + 'signals.pkl'); D = pd.read_pickle(OUT + 'data.pkl')
MWF = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'MU'}
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    if T <= 0: return max(S - K, 0) if k == 'call' else max(K - S, 0)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
def tleft(t): return max(16 * 60 - (t.hour * 60 + t.minute), 0) / 390 / 252
R = R.sort_values('ts').reset_index(drop=True)
R['breadth'] = [int(((R.day == r.day) & (R.kind == r.kind) & (R.ts < r.ts) & (R.sym != r.sym)).sum()) for r in R.itertuples()]
rows = []
for r in R.itertuples():
    b = D[r.sym][0]; x = b[b.index.date == r.day]
    if r.ts not in x.index: continue
    S0 = float(x.C.loc[r.ts]); T0 = tleft(r.ts + pd.Timedelta(minutes=5)); g = 1 if r.kind == 'call' else -1
    wd = pd.Timestamp(r.day).weekday(); listed = wd == 4 or (r.sym in MWF and wd in (0, 2))
    for mult in (1.0, 1.3):
        v = r.rv * mult; K = S0 * math.exp(g * 1.0 * r.rv * math.sqrt(T0)); p0 = bs(S0, K, T0, v, r.kind)
        if p0 < 0.01: continue
        res = None
        for t, bar in x[x.index > r.ts].iterrows():
            T = tleft(t + pd.Timedelta(minutes=5))
            w = bs(bar.L if g == 1 else bar.H, K, T, v, r.kind) / p0 - 1; bb = bs(bar.H if g == 1 else bar.L, K, T, v, r.kind) / p0 - 1
            if w <= -0.5: res = -0.5; break
            if bb >= 1.0: res = 1.0; break
            if t.time() >= dt.time(15, 45): res = bs(bar.C, K, T, v, r.kind) / p0 - 1; break
        if res is None: continue
        rows.append(dict(sym=r.sym, day=r.day, kind=r.kind, mult=mult, half=r.half, third=r.third, pnl=res - 0.10, S=S0,
                         breadth=r.breadth, listed=listed, gated=r.blocks in ('', 'budget')))
Z = pd.DataFrame(rows)
def line(lab, s):
    if not len(s): print(f"  {lab:38s} n=  0"); return
    i, o = s[s.half == 'IS'], s[s.half == 'OOS']
    th = ' '.join(f"{p} {x.pnl.mean():+.0%}({len(x)})" for p, x in s.groupby('third'))
    print(f"  {lab:38s} n={len(s):3d} days {s.day.nunique():2d} win {(s.pnl > 0).mean():3.0%} avg {s.pnl.mean():+6.1%} | IS {i.pnl.mean():+6.1%} OOS {o.pnl.mean():+6.1%} | {th}")
for mult in (1.0, 1.3):
    for uni, U in (('hyp (all names, any day)', Z[Z.mult == mult]), ('listed expiries only', Z[(Z.mult == mult) & Z.listed])):
        print(f"\n=== IV = {mult}x RV30 | {uni}")
        line('all signals', U)
        line('A breadth >= 3 same-direction', U[U.breadth >= 3]); line('  breadth 0-2', U[U.breadth < 3])
        line('A puts, breadth >= 3', U[(U.breadth >= 3) & (U.kind == 'put')]); line('A calls, breadth >= 3', U[(U.breadth >= 3) & (U.kind == 'call')])
        line('B price >= $300', U[U.S >= 300]); line('  price < $300', U[U.S < 300])
        line('A+B breadth >= 3 and price >= $300', U[(U.breadth >= 3) & (U.S >= 300)])
