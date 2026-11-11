"""11-11: the Z0 ticket caught MU's break (845C $33 at 10:11) and sold at the +100% cap ($65) while the move ran on.
Does a trailing exit beat the fixed +100% cap? Same-day ~1.25 remaining-session-sigma option at every confirmed ORB
signal on the 7 daily-expiry names (month_review rebuild, 40 sessions 09-10..11-04, 5m bars), BS at 1.0x RV30, 10% friction."""
import sys, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import option_quotes as oq
D = '/tmp/claude-0/-home-user-options/1900b617-71ad-55f2-b6c2-442b5e790faa/scratchpad/mr/'
R = pd.read_pickle(D + 'signals.pkl'); data = pd.read_pickle(D + 'data.pkl')
Z = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'MU'}
R = R[R.sym.isin(Z)].sort_values('ts'); R = R.groupby('day').head(1)          # first signal of the day, as the slot does
left = lambda t: max(16 * 60 - (t.hour * 60 + t.minute), 0) / 390 / 252
def run(r, mode):
    b = data[r.sym][0]; x = b[(b.index.date == r.day) & (b.index > r.ts)]
    S0 = float(b.loc[r.ts].C); T0 = max(left(r.ts), 1e-6); sg = 1 if r.kind == 'call' else -1
    K = S0 * math.exp(sg * 1.25 * r.rv * math.sqrt(T0)); p0 = oq.bs(S0, K, T0, r.rv, r.kind)
    if p0 <= 0: return None
    peak = None
    for t, row in x.iterrows():
        T = max(left(t + pd.Timedelta(minutes=5)), 1e-6)
        w = oq.bs(row.L if sg == 1 else row.H, K, T, r.rv, r.kind) / p0 - 1
        bst = oq.bs(row.H if sg == 1 else row.L, K, T, r.rv, r.kind) / p0 - 1
        c = oq.bs(row.C, K, T, r.rv, r.kind) / p0 - 1
        if w <= -0.5: return -0.5
        if mode == 'cap' and bst >= 1.0: return 1.0
        if mode.startswith('trail'):
            g = float(mode[5:]) / 100
            if peak is not None and (1 + w) <= (1 + peak) * (1 - g): return (1 + peak) * (1 - g) - 1
            if bst >= 1.0: peak = bst if peak is None else max(peak, bst)
        if mode == 'half' and bst >= 1.0 and peak is None: peak = 1.0          # sell half at +100%, hold half to 15:45 / stop at entry
        if mode == 'half' and peak is not None and w <= 0: return 0.5 * 1.0 + 0.5 * 0.0
        if t.time() >= dt.time(15, 45): return (0.5 * 1.0 + 0.5 * c) if (mode == 'half' and peak is not None) else c
    return c if len(x) else None
days = sorted(R.day.unique()); cut = days[len(days) // 2]
print(f"{len(R)} first-of-day signals, {len(days)} sessions, IS/OOS cut {cut}")
for mode, lab in (('cap', 'current: +100% cap / -50% / 15:45'), ('trail30', 'trail 30% off peak after +100%'), ('trail50', 'trail 50% off peak after +100%'), ('half', 'sell half at +100%, rest to 15:45 (stop at entry)'), ('none', 'no target: -50% / 15:45')):
    v = pd.Series([run(r, mode) for r in R.itertuples()], index=R.index).dropna() - 0.10
    i, o = v[R.loc[v.index].day < cut], v[R.loc[v.index].day >= cut]
    print(f"{lab:50s} n={len(v)} win {(v>0).mean():.0%} avg {v.mean():+.1%} med {v.median():+.0%} | IS {i.mean():+.1%} OOS {o.mean():+.1%} | best {v.max():+.0%}")
