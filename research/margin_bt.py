"""User 10-20: "you can hold 1-2 weeks to maximize profit" + "$700 on $15k - any pattern that nets more?"
Same v2 day-trade ENTRIES (30-min OR break held 10m, VWAP side, relvol>=1, whipsaw/ct3/RSI gates,
0.2 sigma, Friday 2 weeks out, <= $1,000), only the EXIT varies - same-day vs holding up to 1-2
weeks with the swing/momentum trailing exit. 5m bars, continuous across days (overnight gaps
priced at the next day's first bar), BS at RV30, 4% spread. IS = first half of sessions, OOS =
second half. Earnings dates are NOT gated in this test (multi-day rows may hold through prints)."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats
config.YF_INTER_CALL_DELAY = 0.15
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
FR = 0.04


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def opt(S, K, T, v, k):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)


def T_at(ts, exp):
    return (max(16 * 60 - (ts.hour * 60 + ts.minute), 0) / 390 + int(np.busday_count(ts.date(), exp))) / 252


if len(sys.argv) < 2:
    data = {}
    for s in SYMS:
        b = er.fetch_chart(s, '5m', '60d'); b = b[(b.index.time >= dt.time(9, 30)) & (b.index.time < dt.time(16, 0))].dropna()
        data[s] = (b, er.daily_frame(s, '2y'))
    pd.to_pickle(data, 'hold_data.pkl')
data = pd.read_pickle('hold_data.pkl')
DAYS = sorted(set(data['NVDA'][0].index.date))

# ---------- entries (identical to the live engine's rules on 5m bars)
ents = []
for s in SYMS:
    b, d = data[s]; b = b.copy(); b['tod'] = b.index.time
    cum = b.groupby(b.index.date).V.cumsum()
    piv = pd.DataFrame({'d': b.index.date, 't': b.tod, 'c': cum.values}).pivot_table(index='d', columns='t', values='c')
    med = piv.rolling(20).median().shift(1)
    for day in DAYS[20:]:
        x = b[b.index.date == day]; h = d[d.index < day]
        if len(x) < 70 or day not in med.index or len(h) < 60: continue
        c = h.C
        if whipsaw_stats(c)['chop']: continue
        rv = float(c.pct_change().tail(30).std() * math.sqrt(252)); ct3 = c.iloc[-1] / c.iloc[-4] - 1
        dl = c.diff(); g = dl.clip(lower=0).ewm(alpha=1 / 14).mean(); l = (-dl.clip(upper=0)).ewm(alpha=1 / 14).mean()
        rsi = float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1]))
        rel = x.V.cumsum().values / med.loc[day].reindex(x.tod).values; vw = ((x.C * x.V).cumsum() / x.V.cumsum()).values
        o = x[x.index.time < dt.time(10, 0)]; hi, lo = o.H.max(), o.L.min(); C = x.C.values; tm = x.index.time
        exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 14)
        for kind in ('call', 'put'):
            if (kind == 'call' and (ct3 < 0 or rsi > 70)) or (kind == 'put' and (ct3 > 0 or rsi < 32)): continue
            be = (C > hi) if kind == 'call' else (C < lo); run = 0
            for i in range(len(C)):
                run = run + 1 if be[i] else 0
                if tm[i] < dt.time(10, 0) or tm[i] >= dt.time(15, 0): continue
                if run >= 2 and ((C[i] > vw[i]) if kind == 'call' else (C[i] < vw[i])) and (np.isnan(rel[i]) or rel[i] >= 1.0):
                    ts = x.index[i]; S0 = C[i]; g_ = 1 if kind == 'call' else -1
                    K = S0 * math.exp(g_ * 0.2 * rv * math.sqrt(T_at(ts, exp))); p0 = opt(S0, K, T_at(ts, exp), rv, kind)
                    if p0 * 100 <= 1000: ents.append(dict(sym=s, day=day, ts=ts, kind=kind, K=K, rv=rv, p0=p0, exp=exp, rel=float(rel[i]) if not np.isnan(rel[i]) else 1.0, ct3=ct3*100, rsi=rsi, smh=None))
                    break
print(f"sessions {DAYS[20]}..{DAYS[-1]} | entries {len(ents)}")


def path(e):
    b = data[e['sym']][0]; seg = b[(b.index > e['ts']) & (b.index.date <= e['exp'])]
    out = []
    for t, r in seg.iterrows():
        T = T_at(t + pd.Timedelta(minutes=5), e['exp'])
        w, bst = (r.L, r.H) if e['kind'] == 'call' else (r.H, r.L)
        out.append((t, opt(w, e['K'], T, e['rv'], e['kind']) / e['p0'] - 1, opt(bst, e['K'], T, e['rv'], e['kind']) / e['p0'] - 1,
                    opt(r.C, e['K'], T, e['rv'], e['kind']) / e['p0'] - 1, int(np.busday_count(t.date(), e['exp']))))
    return out


def same_day(P, e, tgt, stop, maxhold):
    for t, w, bst, c, bd in P:
        if w <= -stop: return -stop, t
        if bst >= tgt: return tgt, t
        if (maxhold and (t - e['ts']).total_seconds() >= maxhold * 60) or t.time() >= dt.time(15, 45) or t.date() > e['day']: return c, t
    return (P[-1][3], P[-1][0]) if P else (None, None)


def multi(P, e, stop, arm, give, maxdays):
    peak = None; d0 = e['day']
    for t, w, bst, c, bd in P:
        if w <= -stop: return -stop, t
        if peak is not None and (1 + w) <= (1 + peak) * (1 - give): return (1 + peak) * (1 - give) - 1, t
        if bst >= arm: peak = bst if peak is None else max(peak, bst)
        held = int(np.busday_count(d0, t.date()))
        if t.time() >= dt.time(15, 45) and (held >= maxdays or bd <= 2): return c, t
    return (P[-1][3], P[-1][0]) if P else (None, None)



import collections
out=[]
for e in ents:
    P=path(e); r,t=same_day(P,e,.20,.20,120)
    if r is None: continue
    out.append(dict(day=e['day'],kind=e['kind'],rel=e['rel'],ct3=e['ct3'],rsi=e['rsi'],pnl=r-FR))
T=pd.DataFrame(out); cut=DAYS[20+(len(DAYS)-20)//2]
def show(n,g):
    i,o=g[g.day<cut],g[g.day>=cut]
    print(f"  {n:38s} n={len(g):3d} win {(g.pnl>0).mean():.0%} avg {g.pnl.mean():+.1%} | IS {i.pnl.mean():+.1%} (n={len(i)}) OOS {o.pnl.mean():+.1%} (n={len(o)})")
a=T.ct3.abs()
show('all',T)
show('relvol < 1.10 (barely confirmed)',T[T.rel<1.10]); show('relvol >= 1.10',T[T.rel>=1.10]); show('relvol >= 1.50',T[T.rel>=1.5])
show('|3d| < 0.5% (marginal trend)',T[a<0.5]); show('|3d| < 1%',T[a<1]); show('|3d| >= 1%',T[a>=1]); show('|3d| >= 3%',T[a>=3])
show('both marginal (rel<1.1 or |3d|<1)',T[(T.rel<1.1)|(a<1)]); show('neither marginal',T[(T.rel>=1.1)&(a>=1)])
