"""User 11-02: "don't only follow the day trade engine ... make the most optimal trades using the
current $1000. even longer term options e.g. 2-3 weeks dte should be taken in consideration."
The only multi-week entry that survived (hold_entry.py) is a CALL on a 20d closing breakout with
SMH above its 50d MA and >= 1.5x volume - dormant now (SMH 523 vs 50d 572). Question: is there a
2-3 week trade that works in THIS tape? 5 years daily (incl. the 2022 bear market), 26 names,
20d closing break/breakdown signals with the standard gates (whipsaw, 3d counter-trend, RSI),
0.2-sigma option 2 or 3 Fridays out, the adopted trailing exit (-50% stop; after +50% exit 30%
off the peak; out at 2 DTE), 4% friction, IV = RV and 1.15x RV, IS/OOS halves by date.
Pre-specified cuts only (no sweep):
  A. calls, SMH > 50d MA, vol >= 1.5x            (the live trend-hold rule, re-checked on 5y)
  B. puts,  SMH < 50d MA, vol >= 1.5x            (its mirror - what the current tape would allow)
  C. calls, QQQ > 50d MA, vol >= 1.5x, NON-semis (market trend instead of the chip sector)
  D. puts,  QQQ < 50d MA, vol >= 1.5x, NON-semis"""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options'); sys.path.insert(0, '.')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from trend_bt import signals, bs
OUT = '/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/swing5y.pkl'
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
NONSEMI = {'MSFT', 'AAPL', 'AMZN', 'META', 'GOOGL', 'PLTR', 'JPM', 'XOM', 'V', 'VRT', 'DELL', 'SMCI', 'NBIS'}
if len(sys.argv) > 1 and sys.argv[1] == 'fetch':
    D = {}
    for s in SYMS + ['SMH', 'QQQ']:
        try: D[s] = er.daily_frame(s, '5y').dropna()
        except Exception as e: print('skip', s, e)
    pd.to_pickle(D, OUT); print('fetched', len(D)); sys.exit()
D = pd.read_pickle(OUT); idx = {k: pd.Index([pd.Timestamp(i).date() for i in v.index]) for k, v in D.items()}
for k in D: D[k].index = idx[k]
mk = {m: (D[m].C > D[m].C.rolling(50).mean()) for m in ('SMH', 'QQQ')}
data = {s: D[s] for s in SYMS if s in D}
sig = signals(data, {'whip', 'ct', 'rsi'})


def path(r, wk, ivm):
    d = data[r.sym]; day = r.day
    exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 7 * wk)
    T0 = int(np.busday_count(day, exp)) / 252; g = 1 if r.kind == 'call' else -1; v = r.rv * ivm
    K = r.S * math.exp(g * 0.2 * r.rv * math.sqrt(T0)); p0 = bs(r.S, K, T0, v, r.kind); P = []
    for j in range(r.i + 1, len(d)):
        bd = int(np.busday_count(d.index[j], exp))
        if bd < 0: break
        lo, hi = (d.H.iloc[j], d.L.iloc[j]) if r.kind == 'put' else (d.L.iloc[j], d.H.iloc[j])
        Tm = (bd + 0.5) / 252
        P.append((bs(lo, K, Tm, v, r.kind) / p0 - 1, bs(hi, K, Tm, v, r.kind) / p0 - 1, bs(d.C.iloc[j], K, max(bd, 1e-3) / 252, v, r.kind) / p0 - 1, bd))
    return P, p0 * 100


def trail(P):
    peak = None
    for w, b, c, bd in P:
        if w <= -0.5: return -0.5
        if peak is not None and (1 + w) <= (1 + peak) * 0.7: return (1 + peak) * 0.7 - 1
        if b >= 0.5: peak = b if peak is None else max(peak, b)
        if bd <= 2: return c
    return P[-1][2] if P else None


rows = []
for r in sig.itertuples():
    vx = data[r.sym].V.iloc[r.i] / data[r.sym].V.iloc[r.i - 20:r.i].mean()
    rec = dict(day=r.day, sym=r.sym, kind=r.kind, volx=vx, smh=bool(mk['SMH'].get(r.day, False)), qqq=bool(mk['QQQ'].get(r.day, False)))
    for wk in (2, 3):
        for ivm in (1.0, 1.15):
            P, prem = path(r, wk, ivm); x = trail(P)
            rec[f'{wk}w_{ivm}'] = None if x is None else x - 0.04
            if ivm == 1.0: rec[f'prem{wk}'] = prem
    rows.append(rec)
T = pd.DataFrame(rows).dropna(); days = sorted(T.day.unique()); cut = days[len(days) // 2]
C, P_, V = T.kind == 'call', T.kind == 'put', T.volx >= 1.5; NS = T.sym.isin(NONSEMI)
cuts = {'all signals': T.index == T.index, 'A calls, SMH>50d, vol>=1.5x': C & T.smh & V, 'B puts, SMH<50d, vol>=1.5x': P_ & ~T.smh & V,
        'C calls, QQQ>50d, vol>=1.5x, non-semis': C & T.qqq & V & NS, 'D puts, QQQ<50d, vol>=1.5x, non-semis': P_ & ~T.qqq & V & NS}
print(f"{len(T)} signals {days[0]}..{days[-1]}, split {cut}")
for n, m in cuts.items():
    g = T[m]; out = []
    for col in ('2w_1.0', '2w_1.15', '3w_1.0', '3w_1.15'):
        i, o = g[g.day < cut][col], g[g.day >= cut][col]
        out.append(f"{col}: {g[col].mean():+6.1%} (IS {i.mean():+6.1%}/OOS {o.mean():+6.1%})")
    yrs = ' '.join(f"{y}:{x['3w_1.15'].mean():+.0%}({len(x)})" for y, x in g.groupby([pd.Timestamp(d).year for d in g.day]))
    print(f"\n  {n:40s} n={len(g)} (IS {(g.day < cut).sum()} / OOS {(g.day >= cut).sum()}) win3w {(g['3w_1.15'] > 0).mean():.0%} med3w {g['3w_1.15'].median():+.0%} | 3w premium median ${g.prem3.median():.0f}\n    " + '\n    '.join(out) + f"\n    by year (3w, 1.15x): {yrs}")
