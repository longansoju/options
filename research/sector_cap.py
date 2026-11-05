"""Pre-specified 11-05 test: does 'max 1 open day trade per sector group' beat the current 'max 2 open'?
Signals: month_review rebuild (40 sessions 09-10..11-04, 5m bars), gates passing, v2 exits, 4% spread."""
import datetime as dt, numpy as np, pandas as pd
D = '/tmp/claude-0/-home-user-options/1900b617-71ad-55f2-b6c2-442b5e790faa/scratchpad/mr/'
R = pd.read_pickle(D + 'signals.pkl'); P = pd.read_pickle(D + 'paths.pkl').path
CHIPS = {'AVGO','MRVL','MU','NBIS','SMCI','DELL','VRT','NVDA','TSM','ASML','COHR','ANET','CRDO','NVTS','MPWR','STX','WDC'}
MEGA = {'MSFT','AAPL','AMZN','META','GOOGL'}
grp = lambda s: 'chips' if s in CHIPS else 'mega' if s in MEGA else s
def ex(p, tgt=.2, stop=.2, mh=120, end=dt.time(15, 45)):
    for m, t, w, b, c in p:
        if w <= -stop: return -stop, m
        if b >= tgt: return tgt, m
        if m >= mh or t >= end: return c, m
    return (p[-1][4], p[-1][0]) if p else (0.0, 0)
R['ret'], R['hold'] = zip(*[ex(p) for p in P]); R['ret'] -= 0.04
R['out'] = [ts + pd.Timedelta(minutes=h + 5) for ts, h in zip(R.ts, R.hold)]; R['g'] = R.sym.map(grp)
C = R[R.blocks == ''].sort_values('ts')
def sim(maxn, per_group):
    take = []; open_ = []
    for i, r in C.iterrows():
        open_ = [(o, g) for o, g in open_ if o > r.ts]
        if maxn and len(open_) >= maxn: continue
        if per_group and any(g == r.g for _, g in open_): continue
        open_.append((r.out, r.g)); take.append(i)
    return C.loc[take]
days = sorted(R.day.unique()); cut = days[len(days) // 2]; t3 = [days[len(days) // 3], days[2 * len(days) // 3]]
def rep(name, x):
    h = lambda m: f"{x[m].ret.mean():+.1%}({m.sum()})"
    print(f"{name:34s} n={len(x):3d} win {(x.ret > 0).mean():.0%} avg {x.ret.mean():+.2%} | IS {h(x.day < cut)} OOS {h(x.day >= cut)} | "
          f"P1 {h(x.day < t3[0])} P2 {h((x.day >= t3[0]) & (x.day < t3[1]))} P3 {h(x.day >= t3[1])} | trades/day {len(x) / len(days):.1f} | chips share {(x.g == 'chips').mean():.0%}")
print(f"sessions {days[0]}..{days[-1]} ({len(days)}) | gate-passing signals {len(C)}")
rep('C  no slot limit (reference)', C)
A = sim(2, False); B = sim(2, True); rep('A  max 2 open (current)', A); rep('B  max 2 open, 1 per sector group', B)
rep('B2 max 3 open, 1 per sector group', sim(3, True))
x = B[~B.index.isin(A.index)]; y = A[~A.index.isin(B.index)]
print(f"\nB takes {len(x)} trades A skips: avg {x.ret.mean():+.1%} | A takes {len(y)} trades B skips: avg {y.ret.mean():+.1%}")
print("same-group second positions under A:", (A.groupby('day').g.apply(lambda s: s.duplicated().sum())).sum())
