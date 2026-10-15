"""Buy the bounce after a big down day? 2y daily, 27 names + SMH.
(a) Underlying: forward 1/3/5-day returns after a name's own big down day and after
    sector-wide down days (SMH <= -3%), vs all days.
(b) Options: buy a 0.2-sigma 2-week call at that close, +50/-50, 2-DTE time stop,
    4% friction (trend_bt.run). IS/OOS halves by date."""
import sys, math
sys.path.insert(0, '/home/user/options'); sys.path.insert(0, '.')
import numpy as np, pandas as pd
from analysis import event_radar as er
from trend_bt import run

data = pd.read_pickle('trend_data.pkl')
smh = er.daily_frame('SMH', '2y'); smh = smh[smh.index < max(d.index.max() for d in data.values()) + pd.Timedelta(days=1)]
smh_r = smh.C.pct_change()
mkt_down = set(smh_r[smh_r <= -0.03].index)
print('SMH <= -3% days:', len(mkt_down))

rows = []
for s, d in data.items():
    c = d.C; r = c.pct_change(); rv = r.rolling(30).std() * math.sqrt(252)
    for h in (1, 3, 5):
        d[f'f{h}'] = c.shift(-h) / c - 1
    for i in range(40, len(d) - 5):
        rows.append(dict(sym=s, i=i, day=d.index[i], r=r.iloc[i], z=r.iloc[i] / (rv.iloc[i] / math.sqrt(252)),
                         mkt=d.index[i] in mkt_down, S=float(c.iloc[i]), rv=float(rv.iloc[i]),
                         f1=d.f1.iloc[i], f3=d.f3.iloc[i], f5=d.f5.iloc[i]))
A = pd.DataFrame(rows)

def under(name, g):
    print(f"{name:40s} n={len(g):5d} | next day {g.f1.mean():+.2%} ({(g.f1>0).mean():.0%} up) | 3d {g.f3.mean():+.2%} ({(g.f3>0).mean():.0%}) | 5d {g.f5.mean():+.2%} ({(g.f5>0).mean():.0%})")

print('\nUNDERLYING forward returns')
under('all days (baseline)', A)
under('name down <= -4%', A[A.r <= -0.04])
under('name down <= -2 sigma', A[A.z <= -2])
under('SMH down <= -3% (sector selloff)', A[A.mkt])
under('SMH <= -3% AND name <= -4%', A[A.mkt & (A.r <= -0.04)])

# event level: one row per sector selloff day, average across names
ev = A[A.mkt].groupby('day')[['f1', 'f3', 'f5']].mean()
print(f"\nper selloff DAY (n={len(ev)}): next day {ev.f1.mean():+.2%} ({(ev.f1>0).mean():.0%} up), 3d {ev.f3.mean():+.2%} ({(ev.f3>0).mean():.0%}), 5d {ev.f5.mean():+.2%} ({(ev.f5>0).mean():.0%})")
print(ev.round(4).tail(12).to_string())

print('\nOPTIONS: buy 0.2σ 2-week CALL at the selloff close, +50/-50, 4% friction')
for name, sig in (('every day (baseline)', A[A.i % 5 == 0]), ('name down <= -4%', A[A.r <= -0.04]),
                  ('SMH down <= -3%', A[A.mkt]), ('SMH <= -3% AND name <= -4%', A[A.mkt & (A.r <= -0.04)])):
    sig = sig.assign(kind='call')
    t = run(data, sig, 2, 0.2).sort_values('day')
    cut = t.day.iloc[len(t) // 2]; f = lambda x: (x.pnl - 0.04).mean()
    print(f"{name:32s} n={len(t):4d} win {(t.pnl>0).mean():.0%} | IS {f(t[t.day<cut]):+.1%} OOS {f(t[t.day>=cut]):+.1%} | all {f(t):+.1%} | median {(t.pnl-0.04).median():+.1%}")
