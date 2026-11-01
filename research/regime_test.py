"""Follow-up to month_review.py (11-01): the day-trade result swings by REGIME (period 2, 09-17..10-08,
-8.0%/trade; period 3, 10-09..10-30, +1.2%), not by any entry feature. ONE pre-specified test: is the
regime knowable at the prior close? Feature = SMH 10-day efficiency ratio (|10d net move| / sum of
|daily moves|; 1 = clean trend, 0 = chop), known at the prior close. Threshold = the IS-half median,
applied unchanged to the OOS half. No other thresholds or lookbacks were tried."""
import sys, numpy as np, pandas as pd
OUT = '/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/mr/'
R = pd.read_pickle(OUT + 'signals.pkl'); D = pd.read_pickle(OUT + 'data_merged.pkl')['SMH'][1]
c = D.C.copy(); c.index = [pd.Timestamp(i).date() for i in c.index]
er10 = ((c - c.shift(10)).abs() / c.diff().abs().rolling(10).sum()).shift(1)   # known at the prior close
R['er'] = R.day.map(er10); T = R[R.blocks == ''].copy()
thr = T[T.half == 'IS'].er.median()
for h in ('IS', 'OOS'):
    g = T[T.half == h]
    print(f"{h}: trending (ER >= {thr:.2f}) {g[g.er >= thr].cur.mean():+.1%} (n={(g.er >= thr).sum()}) | choppy {g[g.er < thr].cur.mean():+.1%} (n={(g.er < thr).sum()}) | all {g.cur.mean():+.1%}")
for p, g in T.groupby('third'):
    print(f"  {p}: mean ER {g.er.mean():.2f} | trending {g[g.er >= thr].cur.mean():+.1%} ({(g.er >= thr).sum()}) choppy {g[g.er < thr].cur.mean():+.1%} ({(g.er < thr).sum()})")
