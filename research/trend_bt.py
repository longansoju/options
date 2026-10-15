"""Multi-day TREND option backtest (overnight holds), daily bars, ~2y.
Signal at day t close: close breaks the prior 20-day low (put) / high (call).
Gates (current rules): whipsaw not chop (30d), counter-trend 3d aligned, RSI (put
needs RSI>=32, call RSI<=70) - plus variants. Entry at t close (approximation:
the close is used as the signal and the fill). Vehicle priced Black-Scholes at
RV30; held overnight; each later day checks the day's H/L for -50% stop (first,
conservative) then +50% target; time stop when <=2 business days to expiry, at
that day's close. Friction: round-trip % of premium. IS = first half of signal
dates, OOS = second half."""
import sys, math, datetime as dt, itertools
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats
config.YF_INTER_CALL_DELAY = 0.2
SYMS = sorted(set(config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION + ['SNDK']))
MEM = {'MU', 'SNDK', 'WDC', 'STX'}


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, kind):
    T = max(T, 1e-5); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return (S * N(d1) - K * N(d2)) if kind == 'call' else (K * N(-d2) - S * N(-d1))


def rsi(c, n=14):
    d = c.diff(); g = d.clip(lower=0).ewm(alpha=1 / n).mean(); l = (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + g / l)


def load():
    out = {}
    for s in SYMS:
        try:
            d = er.daily_frame(s, '2y'); d = d[d.index < dt.date(2026, 10, 15)]
            if len(d) > 200: out[s] = d
        except Exception as e:
            print('skip', s, e)
    pd.to_pickle(out, 'trend_data.pkl'); return out


def signals(data, gates):
    rows = []
    for s, d in data.items():
        c = d.C; r = c.pct_change()
        rv = r.rolling(30).std() * math.sqrt(252); rs = rsi(c)
        lo20 = d.L.rolling(20).min().shift(1); hi20 = d.H.rolling(20).max().shift(1)
        up5 = (r > 0.05).rolling(30).sum(); dn5 = (r < -0.05).rolling(30).sum()
        chop = ((up5 + dn5) >= 4) & ((up5 - dn5).abs() <= 1)
        ct3 = c / c.shift(3) - 1
        last = {'put': None, 'call': None}
        for i in range(60, len(d) - 1):
            day = d.index[i]
            for kind, brk in (('put', c.iloc[i] < lo20.iloc[i]), ('call', c.iloc[i] > hi20.iloc[i])):
                if not brk: continue
                if last[kind] is not None and i - last[kind] < 5: continue   # one signal per 5 days per side
                ok = True
                if 'whip' in gates and chop.iloc[i]: ok = False
                if 'ct' in gates and ((kind == 'put' and ct3.iloc[i] > 0) or (kind == 'call' and ct3.iloc[i] < 0)): ok = False
                if 'rsi' in gates and ((kind == 'put' and rs.iloc[i] < 32) or (kind == 'call' and rs.iloc[i] > 70)): ok = False
                if not ok: continue
                last[kind] = i
                rows.append(dict(sym=s, i=i, day=day, kind=kind, S=float(c.iloc[i]), rv=float(rv.iloc[i])))
    return pd.DataFrame(rows)


def run(data, sig, wk, sigma, tgt=0.5, stop=0.5, budget=None):
    out = []
    for r in sig.itertuples():
        d = data[r.sym]; day = r.day
        exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 7 * wk)
        if (exp - day).days < 3: exp += dt.timedelta(days=7)
        T0 = int(np.busday_count(day, exp)) / 252
        g = 1 if r.kind == 'call' else -1
        K = r.S * math.exp(g * sigma * r.rv * math.sqrt(T0))
        p0 = bs(r.S, K, T0, r.rv, r.kind)
        if p0 <= 0.005 * r.S * 0 + 1e-4: continue
        if budget and p0 * 100 > budget: continue
        res = None; held = 0
        for j in range(r.i + 1, len(d)):
            dj = d.index[j]; held += 1
            bd = int(np.busday_count(dj, exp))
            Tm = (bd + 0.5) / 252; Tc = max(bd, 0) / 252
            worst = bs(d.H.iloc[j] if r.kind == 'put' else d.L.iloc[j], K, Tm, r.rv, r.kind) / p0 - 1
            best = bs(d.L.iloc[j] if r.kind == 'put' else d.H.iloc[j], K, Tm, r.rv, r.kind) / p0 - 1
            if worst <= -stop: res = -stop; break
            if best >= tgt: res = tgt; break
            if bd <= 2:
                res = bs(d.C.iloc[j], K, max(Tc, 1e-5), r.rv, r.kind) / p0 - 1; break
        if res is None: continue
        out.append(dict(sym=r.sym, day=day, kind=r.kind, pnl=res, prem=p0 * 100, held=held, mem=r.sym in MEM))
    return pd.DataFrame(out)


def show(name, t, fric):
    if not len(t): print(f"{name:52s} n=0"); return
    t = t.sort_values('day'); cut = t.day.iloc[len(t) // 2]
    i, o = t[t.day < cut], t[t.day >= cut]
    f = lambda x: (x.pnl - fric).mean()
    print(f"{name:52s} n={len(t):4d} win {(t.pnl>0).mean():.0%} | IS {f(i):+.1%} OOS {f(o):+.1%} | all {f(t):+.1%} "
          f"(pre {t.pnl.mean():+.1%}) | puts {f(t[t.kind=='put']):+.1%} n={int((t.kind=='put').sum())} calls {f(t[t.kind=='call']):+.1%} | memory {f(t[t.mem]) if t.mem.any() else float('nan'):+.1%} n={int(t.mem.sum())} | med prem ${t.prem.median():.0f}")


if __name__ == '__main__':
    data = load() if len(sys.argv) < 2 else pd.read_pickle('trend_data.pkl')
    print('names', len(data), sorted(data))
    G = {'all gates': {'whip', 'ct', 'rsi'}, 'no RSI gate': {'whip', 'ct'}, 'no whipsaw': {'ct', 'rsi'}, 'no gates': set()}
    for gname, gs in G.items():
        sig = signals(data, gs)
        for wk, sg, fric in ((1, 0.2, 0.04), (2, 0.2, 0.04), (1, 1.0, 0.08), (0, 1.0, 0.10)):
            label = f"[{gname}] {'this' if wk == 0 else str(wk) + 'wk'} expiry, {sg}σ"
            show(label, run(data, sig, wk, sg), fric)
        print()
    # this week's sanity check
    sig = signals(data, {'whip', 'ct', 'rsi'})
    print('recent signals (all gates):'); print(sig[sig.day >= dt.date(2026, 10, 1)][['sym', 'day', 'kind', 'S']].to_string(index=False))
