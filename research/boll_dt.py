"""User 11-22: "yes run the bollinger test on the day trades". PRE-SPECIFIED before looking (from research/boll_test.py:
on daily data a close below the lower band bounced, +1.68% over 5 days, and a close above the upper band stalled).
Question: does a Bollinger(20, 2) "don't chase" gate improve the day-trade book?
  A  prior close outside the band in the trade's direction  -> block (put after a close < lower band, call after > upper)
  B  ENTRY price outside the band (band from the prior 19 closes + the entry price) in the trade's direction -> block
Signals: month_review rebuild on 5m bars, 52 sessions 09-10 -> 11-20 (merged 5m data), v2 vehicle (0.2 sigma, Friday two
weeks out), exits +20 / -20 / 120m / 15:45 measured ON THE BID against the ask paid (the live rule, research/spread_stop.py),
real spread 4% and 8% (8% = median logged 2-week spread). Sets: gate-passing signals (today's rules) and all signals.
ADOPT only if the kept set beats the baseline in BOTH halves AND all three thirds at 8%, and the blocked set loses.
  python research/boll_dt.py <scratchpad>/mr/"""
import sys, datetime as dt, numpy as np, pandas as pd
D = sys.argv[1]
R = pd.read_pickle(D + 'signals.pkl'); P = pd.read_pickle(D + 'paths.pkl').path; data = pd.read_pickle(D + 'data_merged.pkl')
def run(p, s, tgt=.2, stop=.2, mh=120, end=dt.time(15, 45)):
    k = (1 - s / 2) / (1 + s / 2); f = lambda r: (1 + r) * k - 1
    for m, t, w, b, c in p:
        if f(w) <= -stop: return min(f(w), -stop) if m == p[0][0] else -stop
        if f(b) >= tgt: return tgt
        if m >= mh or t >= end: return f(c)
    return f(p[-1][4]) if p else 0.0
A, B, Z = [], [], []
for i, r in R.iterrows():
    b, d = data[r.sym]; c = d.C.copy(); c.index = [pd.Timestamp(x).date() for x in c.index]; c = c[c.index < r.day].tail(20)
    S0 = float(b.C.loc[r.ts]) if r.ts in b.index else np.nan
    m, sd = c.mean(), c.std(); up, lo = m + 2 * sd, m - 2 * sd
    c2 = pd.concat([c.iloc[1:], pd.Series([S0])]); m2, s2 = c2.mean(), c2.std()
    if r.kind == 'call': A.append(c.iloc[-1] > up); B.append(S0 > m2 + 2 * s2)
    else: A.append(c.iloc[-1] < lo); B.append(S0 < m2 - 2 * s2)
    Z.append((S0 - m2) / s2)
R['bA'], R['bB'], R['z'] = A, B, Z
days = sorted(R.day.unique()); cut = days[len(days) // 2]; t3 = [days[len(days) // 3], days[2 * len(days) // 3]]
def line(lab, x, s):
    r = pd.Series([run(P.loc[j], s) for j in x.index], index=x.index, dtype=float); d = x.day
    seg = lambda m: f"{r[m].mean():+6.1%}({m.sum():3d})" if m.sum() else '    n/a     '
    print(f"  {lab:34s} n={len(x):4d} win {(r > 0).mean():3.0%} avg {r.mean():+6.1%} | IS {seg(d < cut)} OOS {seg(d >= cut)} | "
          f"P1 {seg(d < t3[0])} P2 {seg((d >= t3[0]) & (d < t3[1]))} P3 {seg(d >= t3[1])}")
print(f"signals {len(R)} ({(R.blocks == '').sum()} pass today's gates) | sessions {days[0]}..{days[-1]} | "
      f"A flags {R.bA.mean():.0%}, B flags {R.bB.mean():.0%} of all signals")
for setlab, X in (("GATE-PASSING (today's rules)", R[R.blocks == '']), ('ALL SIGNALS (gates ignored)', R)):
    for s in (0.04, 0.08):
        print(f"\n{setlab}, real spread {s:.0%}")
        line('baseline', X, s)
        for g in ('bA', 'bB'):
            line(f"{g[1]}: kept (not outside the band)", X[~X[g]], s)
            line(f"{g[1]}: BLOCKED (outside the band)", X[X[g]], s)
