"""Week review 11-13 (user: "we've been losing quite a bit this week ... make the required improvements").
Since 11-04 fills are REAL: buy at the ask, mark/stop at the bid. The +20/-20/120m rule was pen-tested with a flat 4%
friction taken off the result - but live, a spread s puts the position at about -s the moment it fills, so the -20% stop
sits only (20 - s)% of mid-price movement away while the +20% target needs (20 + s)%. Two PRE-SPECIFIED questions:
  1. How does the SAME rule perform as the real spread grows (4 / 8 / 12 / 16 / 20%)?  -> is a spread cap justified, where?
  2. Does measuring the stop/target on the MID (exit still filled at the bid) beat measuring them on the bid?
Signals: month_review rebuild (gate-passing ORB signals, 40 sessions 09-10..11-04, 5m bars, model mid path at RV30).
A = live rule: levels on the bid vs the ask paid.  B = levels on the mid (20% mid move either way), fills at the bid."""
import sys, datetime as dt, numpy as np, pandas as pd
D = sys.argv[1]
R = pd.read_pickle(D + 'signals.pkl'); P = pd.read_pickle(D + 'paths.pkl').path
def run(p, s, on_mid, tgt=.2, stop=.2, mh=120, end=dt.time(15, 45)):
    k = (1 - s / 2) / (1 + s / 2); f = lambda r: (1 + r) * k - 1          # mid return -> return at the bid on the ask paid
    for m, t, w, b, c in p:
        if on_mid:
            if w <= -stop: return f(-stop)
            if b >= tgt: return f(tgt)
        else:
            if f(w) <= -stop: return min(f(w), -stop) if m == p[0][0] else -stop   # first bar can gap through (the 1-minute stops)
            if f(b) >= tgt: return tgt
        if m >= mh or t >= end: return f(c)
    return f(p[-1][4]) if p else 0.0
C = R[R.blocks == ''].copy(); PC = P.loc[C.index]
days = sorted(R.day.unique()); cut = days[len(days) // 2]; t3 = [days[len(days) // 3], days[2 * len(days) // 3]]
print(f"gate-passing signals {len(C)} | sessions {days[0]}..{days[-1]}")
print(f"{'spread':>6} {'rule':28s} {'win':>4} {'avg':>7} | {'IS':>7} {'OOS':>7} | {'P1':>7} {'P2':>7} {'P3':>7}")
for s in (0.04, 0.08, 0.12, 0.16, 0.20):
    for lab, om in (('A levels on the bid (live)', False), ('B levels on the mid', True)):
        r = pd.Series([run(p, s, om) for p in PC], index=C.index); d = C.day
        print(f"{s:6.0%} {lab:28s} {(r > 0).mean():4.0%} {r.mean():+7.1%} | {r[d < cut].mean():+7.1%} {r[d >= cut].mean():+7.1%} | "
              f"{r[d < t3[0]].mean():+7.1%} {r[(d >= t3[0]) & (d < t3[1])].mean():+7.1%} {r[d >= t3[1]].mean():+7.1%}")
