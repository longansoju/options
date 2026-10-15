"""Can we anticipate the intraday bounce? Day-trade CALLS on names that are DOWN over
3 days (the ones the counter-trend gate blocks), current v2 vehicle/exits: 0.2 sigma,
expiry 2 Fridays out, +20/-20, 120-min max hold, 15:45; 4% spread. 5m bars, 21 names,
40 tested sessions (first 20 = relvol warm-up); IS = first 20, OOS = last 20.
Entries tested:
  ORB    - opening-range-high break held 10m, above VWAP, relvol>=1 (today's signals)
  VWAP   - first reclaim of VWAP after 10:00 held 10m (earlier, 'anticipating')
  OPEN   - buy at 10:00 regardless (pure anticipation)
each under conditions: all down-3d names / gapped down >=1% today / gap <=-1% AND
group gap (avg of 21 names) <=-1% (sector selloff morning)."""
import sys, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis.harvest import whipsaw_stats

data = pd.read_pickle('dt_data.pkl'); SPREAD = 0.04


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, kind):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return (S * N(d1) - K * N(d2)) if kind == 'call' else (K * N(-d2) - S * N(-d1))


def T_at(ts, exp):
    return (max(16 * 60 - (ts.hour * 60 + ts.minute), 0) / 390 + int(np.busday_count(ts.date(), exp))) / 252


DAYS = sorted(set(data['MU'][0].index.date)); SPLIT = DAYS[40]
ND = []
for s, (b, d) in data.items():
    b = b.copy(); b['tod'] = b.index.time
    cum = b.groupby(b.index.date).V.cumsum()
    piv = pd.DataFrame({'d': b.index.date, 't': b.tod, 'c': cum.values}).pivot_table(index='d', columns='t', values='c')
    med = piv.rolling(20).median().shift(1)
    for day in DAYS[20:]:
        x = b[b.index.date == day]; h = d[d.index < day]
        if len(x) < 70 or len(h) < 60 or day not in med.index: continue
        c = h.C
        ND.append(dict(sym=s, day=day, x=x, rel=x.V.cumsum().values / med.loc[day].reindex(x.tod).values,
                       rv=float(c.pct_change().tail(30).std() * math.sqrt(252)), chop=bool(whipsaw_stats(c)['chop']),
                       ct3=c.iloc[-1] / c.iloc[-4] - 1, gap=x.O.iloc[0] / c.iloc[-1] - 1, oos=day >= SPLIT))
G = pd.DataFrame([(n['day'], n['gap']) for n in ND], columns=['day', 'gap']).groupby('day').gap.mean()


def trade(nd, i, kind='call'):
    x = nd['x']; C = x.C.values; ts = x.index[i]; S0 = C[i]; rv = nd['rv']
    exp = nd['day'] + dt.timedelta(days=(4 - nd['day'].weekday()) % 7 + 14)
    T0 = T_at(ts, exp); K = S0 * math.exp(0.2 * rv * math.sqrt(T0)); p0 = bs(S0, K, T0, rv, kind)
    for j in range(i + 1, len(C)):
        t2 = x.index[j]; T = T_at(t2 + pd.Timedelta(minutes=5), exp)
        if bs(x.L.iloc[j], K, T, rv, kind) / p0 - 1 <= -0.2: return -0.2
        if bs(x.H.iloc[j], K, T, rv, kind) / p0 - 1 >= 0.2: return 0.2
        if (t2 - ts).total_seconds() >= 120 * 60 or t2.time() >= dt.time(15, 45):
            return bs(C[j], K, T, rv, kind) / p0 - 1
    return None


def entry(nd, how):
    x = nd['x']; C = x.C.values; tm = x.index.time
    o = x[tm < dt.time(10, 0)]; hi = o.H.max()
    vw = ((x.C * x.V).cumsum() / x.V.cumsum()).values
    run = 0
    for i in range(len(C)):
        if how == 'OPEN':
            if tm[i] >= dt.time(10, 0): return i
            continue
        cond = (C[i] > hi and C[i] > vw[i]) if how == 'ORB' else C[i] > vw[i]
        run = run + 1 if cond else 0
        if tm[i] < dt.time(10, 0) or tm[i] >= dt.time(15, 0): continue
        if run >= 2 and (how != 'ORB' or np.isnan(nd['rel'][i]) or nd['rel'][i] >= 1.0): return i
    return None


def show(name, pool, how):
    rows = []
    for nd in pool:
        i = entry(nd, how)
        if i is None: continue
        r = trade(nd, i)
        if r is not None: rows.append((nd['oos'], r - SPREAD))
    t = pd.DataFrame(rows, columns=['oos', 'pnl'])
    if not len(t): print(f"{name:52s} n=0"); return
    f = lambda g: f"{g.pnl.mean():+.1%} (n={len(g)})" if len(g) else 'n/a'
    print(f"{name:52s} n={len(t):4d} win {(t.pnl>0).mean():.0%} | IS {f(t[~t.oos])} OOS {f(t[t.oos])} | all {t.pnl.mean():+.1%}")


base = [n for n in ND if not n['chop'] and n['ct3'] >= 0]
down = [n for n in ND if not n['chop'] and n['ct3'] < 0]
gapd = [n for n in down if n['gap'] <= -0.01]
sect = [n for n in gapd if G[n['day']] <= -0.01]
print(f"name-days {len(ND)} | sector gap-down mornings (avg gap <= -1%): {(G <= -0.01).sum()} of {len(G)}\n")
show('REFERENCE: calls the gate allows (up 3d), ORB', base, 'ORB')
for how in ('ORB', 'VWAP', 'OPEN'):
    show(f'[{how}] down-3d names (gate-blocked)', down, how)
    show(f'[{how}]   + gapped down >=1% today', gapd, how)
    show(f'[{how}]   + sector gap-down morning', sect, how)
    print()
