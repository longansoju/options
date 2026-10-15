"""User 10-15: "the exit is the issue - the surging options took a few days to flip."
Hold entries fixed (20d close-break trend signals, all gates, 27 names, 2y daily) and
vary ONLY the exit: target (+50/+100/+200/none), stop (-50/-80/none), trailing stop,
expiry length, strike. Daily H/L, stop checked before target (conservative).
Also: of trades whose premium PEAKED >= +200%, how many days to the peak, and how many
were stopped out at -50% first."""
import sys, math, datetime as dt
sys.path.insert(0, '.')
import numpy as np, pandas as pd
from trend_bt import signals, bs

data = pd.read_pickle('trend_data.pkl')
sig = signals(data, {'whip', 'ct', 'rsi'})
FR = {0.2: 0.04, 1.0: 0.08}


def paths(wk, sigma):
    """premium path per signal: list of (worst, best, close) ratios per day held."""
    out = []
    for r in sig.itertuples():
        d = data[r.sym]; day = r.day
        exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 7 * wk)
        if (exp - day).days < 3: exp += dt.timedelta(days=7)
        T0 = int(np.busday_count(day, exp)) / 252; g = 1 if r.kind == 'call' else -1
        K = r.S * math.exp(g * sigma * r.rv * math.sqrt(T0)); p0 = bs(r.S, K, T0, r.rv, r.kind)
        if p0 < 1e-4: continue
        P = []
        for j in range(r.i + 1, len(d)):
            bd = int(np.busday_count(d.index[j], exp))
            if bd < 0: break
            Tm = (bd + 0.5) / 252; Tc = max(bd, 0) / 252
            hi_px, lo_px = (d.L.iloc[j], d.H.iloc[j]) if r.kind == 'put' else (d.H.iloc[j], d.L.iloc[j])
            P.append((bs(lo_px, K, Tm, r.rv, r.kind) / p0 - 1, bs(hi_px, K, Tm, r.rv, r.kind) / p0 - 1,
                      bs(d.C.iloc[j], K, max(Tc, 1e-5), r.rv, r.kind) / p0 - 1, bd))
        if P and P[-1][3] <= 0 or (P and len(P) >= 1 and d.index[-1] >= exp):
            out.append(dict(day=day, kind=r.kind, sym=r.sym, P=P))
        elif P and int(np.busday_count(d.index[-1], exp)) <= 0:
            out.append(dict(day=day, kind=r.kind, sym=r.sym, P=P))
    return out


def ex(P, tgt, stop, trail, tstop):
    peak = 0.0
    for k, (w, b, c, bd) in enumerate(P):
        if stop is not None and w <= -stop: return -stop, k + 1
        if trail and peak >= trail[0] and w <= peak * (1 - trail[1]) - (1 - trail[1]) * 0 and (1 + w) <= (1 + peak) * (1 - trail[1]):
            return (1 + peak) * (1 - trail[1]) - 1, k + 1
        if tgt is not None and b >= tgt: return tgt, k + 1
        peak = max(peak, b)
        if bd <= tstop: return c, k + 1
    return P[-1][2], len(P)


RULES = [('+50 / -50, out at 2 DTE (current swing/momentum)', 0.5, 0.5, None, 2),
         ('+100 / -50', 1.0, 0.5, None, 2), ('+200 / -50', 2.0, 0.5, None, 2),
         ('+100 / no stop', 1.0, None, None, 2), ('+200 / no stop', 2.0, None, None, 2),
         ('no target / -50, hold to 2 DTE', None, 0.5, None, 2), ('no target / no stop, hold to 2 DTE', None, None, None, 2),
         ('hold to expiry, nothing', None, None, None, 0),
         ('-50 stop, trail: after +50% give back 30% of value', None, 0.5, (0.5, 0.3), 2),
         ('-50 stop, trail: after +100% give back 40%', None, 0.5, (1.0, 0.4), 2),
         ('no stop, trail: after +100% give back 40%', None, None, (1.0, 0.4), 2)]

for wk, sigma in ((1, 0.2), (2, 0.2), (4, 0.2), (1, 1.0), (2, 1.0)):
    Ps = paths(wk, sigma); fr = FR[sigma]
    days = sorted(p['day'] for p in Ps); cut = days[len(days) // 2]
    print(f"\n=== expiry {wk}wk, strike {sigma} sigma | n={len(Ps)} | friction {fr:.0%} ===")
    for name, tgt, stop, trail, ts in RULES:
        res = [(p['day'], ex(p['P'], tgt, stop, trail, ts)) for p in Ps]
        t = pd.DataFrame([(d, r - fr, h) for d, (r, h) in res], columns=['day', 'pnl', 'held'])
        i, o = t[t.day < cut], t[t.day >= cut]
        print(f"  {name:52s} avg {t.pnl.mean():+6.1%} | IS {i.pnl.mean():+6.1%} OOS {o.pnl.mean():+6.1%} | win {(t.pnl>0).mean():.0%} | med {t.pnl.median():+6.1%} | held {t.held.mean():.1f}d")
    pk = pd.DataFrame([dict(peak=max(b for _, b, _, _ in p['P']), dpk=1 + int(np.argmax([b for _, b, _, _ in p['P']])),
                            stopped=any(w <= -0.5 for w, _, _, _ in p['P'][:int(np.argmax([b for _, b, _, _ in p['P']]))] ),
                            final=p['P'][-1][2]) for p in Ps])
    big = pk[pk.peak >= 2.0]
    print(f"  peaked >= +200%: {len(big)} of {len(pk)} ({len(big)/len(pk):.0%}) | days to peak median {big.dpk.median():.0f} "
          f"| hit -50% BEFORE the peak: {big.stopped.mean():.0%} | ended (at 2DTE/expiry) avg {big.final.mean():+.0%}")
    pk2 = pk[pk.peak >= 0.5]
    print(f"  peaked >= +50%: {len(pk2)/len(pk):.0%} | days to peak median {pk2.dpk.median():.0f} | ended avg {pk2.final.mean():+.0%} "
          f"| ended below entry {(pk2.final<0).mean():.0%}")
