"""Day-trade rule backtest: 21 focus names, 60 sessions of 5m bars.
Instrument: nearest-Friday weekly, strike 0.4 sigma OTM (inside 0.3-0.6), BS at RV30.
Entry at the close of the bar that completes the confirmation; exits checked
bar-by-bar on the bar's best/worst price (stop checked FIRST = conservative),
time stop 15:45. Friction: round-trip spread as % of premium."""
import sys, math, datetime as dt, itertools
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats
config.YF_INTER_CALL_DELAY = 0.2
SYMS = config.FOCUS_AI_SEMI_IT


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, kind):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return (S * N(d1) - K * N(d2)) if kind == 'call' else (K * N(-d2) - S * N(-d1))


def T_at(ts, exp):
    mins = max(16 * 60 - (ts.hour * 60 + ts.minute), 0)
    return (mins / 390 + int(np.busday_count(ts.date(), exp))) / 252


def load():
    out = {}
    for s in SYMS:
        b = er.fetch_chart(s, '5m', '60d')
        b = b[(b.index.time >= dt.time(9, 30)) & (b.index.time < dt.time(16, 0))].dropna()
        d = er.daily_frame(s, '2y')
        out[s] = (b, d)
    pd.to_pickle(out, 'dt_data.pkl')
    return out


def trades(data, rule, tgt, stop, gates_on, hold_bars=2):
    rows = []
    for s, (b, d) in data.items():
        days = sorted(set(b.index.date))
        for day in days[20:]:
            x = b[b.index.date == day]
            if len(x) < 30: continue
            hist = d[d.index < day]
            if len(hist) < 60: continue
            c = hist.C; rv = float(c.pct_change().tail(30).std() * math.sqrt(252))
            if rule == '20d':
                hi, lo = float(hist.H.tail(20).max()), float(hist.L.tail(20).min()); start = dt.time(9, 30)
            else:   # opening range = first 30 min
                orb = x[x.index.time < dt.time(10, 0)]; hi, lo = float(orb.H.max()), float(orb.L.min()); start = dt.time(10, 0)
            # same-clock relvol reference: prior 20 sessions
            prev = [g for dd, g in b.groupby(b.index.date) if dd < day][-20:]
            cum = x.V.cumsum(); vw = (x.C * x.V).cumsum() / cum
            w = whipsaw_stats(c); ct3 = (c.iloc[-1] / c.iloc[-4] - 1) * 100
            exp = day + dt.timedelta(days=(4 - day.weekday()) % 7)
            for kind in ('call', 'put'):
                if gates_on:
                    if w['chop']: continue
                    if kind == 'call' and ct3 < 0: continue
                    if kind == 'put' and ct3 > 0: continue
                beyond = (x.C > hi) if kind == 'call' else (x.C < lo)
                run = beyond.groupby((~beyond).cumsum()).cumsum()
                ok = (run >= hold_bars) & (x.index.time >= start) & (x.index.time < dt.time(15, 0))
                ok &= (x.C > vw) if kind == 'call' else (x.C < vw)
                cand = x.index[ok.values]
                ent = None
                for ts in cand:
                    t = ts.time()
                    ref = [float(g.V[g.index.time <= t].sum()) for g in prev]
                    if ref and cum[ts] / max(np.median(ref), 1) >= 1.0:
                        ent = ts; break
                if ent is None: continue
                S0 = float(x.C[ent]); sd = rv * math.sqrt(T_at(ent, exp))
                K = S0 * math.exp((0.4 if kind == 'call' else -0.4) * sd)
                p0 = bs(S0, K, T_at(ent, exp), rv, kind)
                if p0 <= 0: continue
                res = None
                for ts, r in x[x.index > ent].iterrows():
                    T = T_at(ts + pd.Timedelta(minutes=5), exp)
                    worst = bs(r.L if kind == 'call' else r.H, K, T, rv, kind) / p0 - 1
                    best = bs(r.H if kind == 'call' else r.L, K, T, rv, kind) / p0 - 1
                    if worst <= -stop: res = -stop; break
                    if best >= tgt: res = tgt; break
                    if ts.time() >= dt.time(15, 45):
                        res = bs(r.C, K, T, rv, kind) / p0 - 1; break
                if res is None: continue
                rows.append(dict(sym=s, day=day, kind=kind, pnl=res, chop=w['chop'], ct3=ct3))
                break   # one trade per name-day
    return pd.DataFrame(rows)


if __name__ == '__main__':
    data = load() if len(sys.argv) < 2 else pd.read_pickle('dt_data.pkl')
    print('sessions', len(set(data['MU'][0].index.date)))
    for rule, gates_on, (tgt, stop) in itertools.product(['20d', 'orb'], [True, False], [(0.5, 0.5), (0.3, 0.3), (0.5, 0.25)]):
        t = trades(data, rule, tgt, stop, gates_on)
        if not len(t): print(rule, gates_on, tgt, stop, 'n=0'); continue
        f4 = t.pnl - 0.04; f8 = t.pnl - 0.08
        print(f"{rule:4s} gates={'Y' if gates_on else 'N'} +{tgt:.0%}/-{stop:.0%} n={len(t):4d} win {(t.pnl>0).mean():.0%} "
              f"avg {t.pnl.mean():+.1%} med {t.pnl.median():+.1%} | 4% spread {f4.mean():+.1%} | 8% {f8.mean():+.1%} | "
              f"calls {t[t.kind=='call'].pnl.mean():+.1%} (n={(t.kind=='call').sum()}) puts {t[t.kind=='put'].pnl.mean():+.1%} (n={(t.kind=='put').sum()})")
        if rule == 'orb' and gates_on and tgt == 0.5 and stop == 0.5:
            t.to_csv('dt_orb_trades.csv', index=False)
