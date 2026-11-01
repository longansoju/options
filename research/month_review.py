"""User 11-01: "review our current strategies against the market movement for the past month. were
there any losses that could've been avoided and wins that we could've took? study them and improve."
Rebuilds EVERY day-trade signal on 5m bars over the last ~40 tradeable sessions (60d of 5m data, 20-
session warm-up): first confirmed 30-min opening-range break per name/side/day (held 2 x 5m closes,
VWAP side, relvol >= 1.0x same-clock), 10:00-15:00. Gates are RECORDED, not applied, so taken and
passed signals can be scored the same way. Outcome = v2 vehicle (0.2 sigma, Friday 2 weeks out) under
the current exit (+20/-20/120m/15:45) and variants, BS at RV30, 4% spread. Earnings: the backtest
cannot see the report-day block (no history of dates); report REACTION days are flagged from the tape
(|gap| > 3 gap-sd AND volume > 2.5x). IS = first half of sessions, OOS = second half.
  python research/month_review.py fetch   # download 5m/daily data (scratchpad/mr/)
  python research/month_review.py         # build signals + report"""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats
config.YF_INTER_CALL_DELAY = 0.15
OUT = '/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/mr/'
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
FR = 0.04
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def opt(S, K, T, v, k):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
def T_at(ts, exp): return (max(16 * 60 - (ts.hour * 60 + ts.minute), 0) / 390 + int(np.busday_count(ts.date(), exp))) / 252

if len(sys.argv) > 1 and sys.argv[1] == 'fetch':
    data = {}
    for s in SYMS + ['SMH']:
        b = er.fetch_chart(s, '5m', '60d'); b = b[(b.index.time >= dt.time(9, 30)) & (b.index.time < dt.time(16, 0))].dropna()
        data[s] = (b, er.daily_frame(s, '2y').dropna())
    pd.to_pickle(data, OUT + 'data.pkl'); print('fetched', len(data)); sys.exit()

data = pd.read_pickle(OUT + ('data_merged.pkl' if 'merged' in sys.argv else 'data.pkl'))   # merged = + older 5m bars from hold_bt (07-29 on)
DAYS = sorted(set(data['NVDA'][0].index.date))
sb = data['SMH'][0]; sd_ = data['SMH'][1]
rows = []
for s in SYMS:
    b, d = data[s]; b = b.copy(); b['tod'] = b.index.time
    cum = b.groupby(b.index.date).V.cumsum()
    piv = pd.DataFrame({'d': b.index.date, 't': b.tod, 'c': cum.values}).pivot_table(index='d', columns='t', values='c')
    med = piv.rolling(20).median().shift(1)
    dd = d.copy(); dd.index = [pd.Timestamp(i).date() for i in dd.index]
    gap = dd.O / dd.C.shift(1) - 1; gsd = gap.rolling(60).std().shift(1); vx = dd.V / dd.V.rolling(20).mean().shift(1)
    for day in DAYS[20:]:
        x = b[b.index.date == day]; h = dd[dd.index < day]
        if len(x) < 70 or day not in med.index or len(h) < 60 or day not in dd.index: continue
        c = h.C; w = whipsaw_stats(c)
        rv = float(c.pct_change().tail(30).std() * math.sqrt(252)); ct3 = (c.iloc[-1] / c.iloc[-4] - 1) * 100
        dl = c.diff(); g = dl.clip(lower=0).ewm(alpha=1 / 14).mean(); l = (-dl.clip(upper=0)).ewm(alpha=1 / 14).mean()
        rsi = float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1]))
        react = bool(abs(gap.loc[day]) > 3 * gsd.loc[day] and vx.loc[day] > 2.5)
        gp = float(gap.loc[day]) * 100
        rel = x.V.cumsum().values / med.loc[day].reindex(x.tod).values; vw = ((x.C * x.V).cumsum() / x.V.cumsum()).values
        o = x[x.index.time < dt.time(10, 0)]; hi, lo = o.H.max(), o.L.min(); C = x.C.values; tm = x.index.time
        exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 14)
        smx = sb[sb.index.date == day]
        sh = sd_.C[[pd.Timestamp(i).date() < day for i in sd_.index]]
        smh_tr = float(sh.iloc[-1] / sh.tail(50).mean() - 1) * 100; name_tr = float(c.iloc[-1] / c.tail(20).mean() - 1) * 100
        for kind in ('call', 'put'):
            be = (C > hi) if kind == 'call' else (C < lo); run = 0
            for i in range(len(C)):
                run = run + 1 if be[i] else 0
                if tm[i] < dt.time(10, 0) or tm[i] >= dt.time(15, 0): continue
                if run >= 2 and ((C[i] > vw[i]) if kind == 'call' else (C[i] < vw[i])) and (np.isnan(rel[i]) or rel[i] >= 1.0):
                    ts = x.index[i]; S0 = C[i]; g_ = 1 if kind == 'call' else -1; T0 = T_at(ts, exp)
                    K = S0 * math.exp(g_ * 0.2 * rv * math.sqrt(T0)); p0 = opt(S0, K, T0, rv, kind)
                    sm = smx[smx.index <= ts]
                    smh_open = float(sm.C.iloc[-1] / sm.O.iloc[0] - 1) * 100 if len(sm) else 0.0
                    seg = x[x.index > ts]; path = []
                    for t, r in seg.iterrows():
                        T = T_at(t + pd.Timedelta(minutes=5), exp)
                        wv, bv = (r.L, r.H) if kind == 'call' else (r.H, r.L)
                        path.append(((t - ts).total_seconds() / 60, t.time(), opt(wv, K, T, rv, kind) / p0 - 1, opt(bv, K, T, rv, kind) / p0 - 1, opt(r.C, K, T, rv, kind) / p0 - 1))
                    blocks = []
                    if w['chop']: blocks.append('whipsaw')
                    if (kind == 'call' and ct3 < 1) or (kind == 'put' and ct3 > -1): blocks.append('ct3')
                    if (kind == 'call' and rsi > 70) or (kind == 'put' and rsi < 32): blocks.append('rsi')
                    if p0 * 100 > 1000: blocks.append('budget')
                    rows.append(dict(sym=s, day=day, ts=ts, kind=kind, prem=p0 * 100, rv=rv, ct3=ct3, rsi=rsi, rel=float(rel[i]) if not np.isnan(rel[i]) else 1.0,
                                     vwd=(S0 / vw[i] - 1) * 100 * g_, orw=(hi - lo) / S0 * 100, gap=gp * g_, react=react, smh=smh_open * g_, mins=(tm[i].hour * 60 + tm[i].minute) - 600,
                                     smh_tr=smh_tr * g_, name_tr=name_tr * g_, blocks='+'.join(blocks), path=path))
                    break
R = pd.DataFrame(rows)


def ex(P, tgt=.20, stop=.20, mh=120, end=dt.time(15, 45), trail=None):
    peak = None
    for m, t, w, b, c in P:
        if w <= -stop: return -stop
        if trail and peak is not None and (1 + w) <= (1 + peak) * (1 - trail[1]): return (1 + peak) * (1 - trail[1]) - 1
        if tgt and b >= tgt: return tgt
        if trail and b >= trail[0]: peak = b if peak is None else max(peak, b)
        if (mh and m >= mh) or t >= end: return c
    return P[-1][4] if P else 0.0


R['cur'] = [ex(p) - FR for p in R.path]
R['month'] = [d.strftime('%m') for d in R.day]
days = sorted(R.day.unique()); cut = days[len(days) // 2]
R['half'] = np.where(R.day < cut, 'IS', 'OOS')
third = [days[len(days) // 3], days[2 * len(days) // 3]]
R['third'] = np.where(R.day < third[0], 'P1', np.where(R.day < third[1], 'P2', 'P3'))
R.drop(columns='path').to_pickle(OUT + 'signals.pkl'); pd.to_pickle(R[['path']], OUT + 'paths.pkl')
print(f"periods split at {third} | ", end=''); print(f"sessions {days[0]}..{days[-1]} ({len(days)}), split at {cut} | signals {len(R)}, taken under current rules {(R.blocks == '').sum()}")


def show(n, g, col='cur'):
    i, o = g[g.half == 'IS'], g[g.half == 'OOS']
    th = ' '.join(f"{k} {v:+5.1%}({c})" for k, v, c in ((k, x[col].mean(), len(x)) for k, x in g.groupby('third')))
    print(f"  {n:46s} n={len(g):4d} win {(g[col] > 0).mean():4.0%} avg {g[col].mean():+6.1%} | IS {i[col].mean():+6.1%} ({len(i):3d}) OOS {o[col].mean():+6.1%} ({len(o):3d}) | {th} | ${(g[col] * g.prem).sum():+,.0f}")


T = R[R.blocks == '']
print('\n=== A. market by week (SMH) and the TAKEN set by month/side')
sm = sd_.C.copy(); sm.index = [pd.Timestamp(i).date() for i in sm.index]; sm = sm[sm.index >= days[0]]
wk = sm.groupby([pd.Timestamp(i).to_period('W') for i in sm.index]).last()
print('  SMH weekly closes:', ', '.join(f"{str(k)[-10:]} {v:.0f}" for k, v in wk.items()))
for m, g in T.groupby('month'): show(f'taken, month {m}', g)
for k, g in T.groupby('kind'): show(f'taken, {k}s', g)
print('\n=== B. passed signals priced as if taken (by blocking gate set)')
P_ = R[R.blocks != '']
for bl, g in P_.groupby('blocks'):
    if len(g) >= 8: show(f'blocked by {bl}', g)
for gate in ('whipsaw', 'ct3', 'rsi', 'budget'):
    show(f'blocked ONLY by {gate}', R[R.blocks == gate])
print('\n=== C. single-feature cuts on the TAKEN set (adopt only if better in BOTH halves)')
cuts = {'relvol >= 1.5': T.rel >= 1.5, 'relvol < 1.2': T.rel < 1.2, 'entry before 11:00': T.mins < 60, 'entry after 13:00': T.mins >= 180,
        'SMH moving WITH the trade (from open)': T.smh > 0, 'SMH moving AGAINST': T.smh <= 0, 'gap WITH the trade > +0.5%': T.gap > 0.5,
        'gap AGAINST the trade < -0.5%': T.gap < -0.5, 'earnings-reaction day': T.react, '|3d| >= 3%': T.ct3.abs() >= 3, '|3d| >= 5%': T.ct3.abs() >= 5,
        'opening range > 2%': T.orw > 2, 'opening range < 1%': T.orw < 1, 'VWAP distance > 1%': T.vwd > 1, 'RV30 > 50%': T.rv > .5, 'RV30 < 25%': T.rv < .25,
        'premium < $400': T.prem < 400, 'SMH trend WITH the trade (vs 50d MA)': T.smh_tr > 0, 'SMH trend AGAINST': T.smh_tr <= 0,
        'name trend WITH the trade (vs 20d MA)': T.name_tr > 0, 'name trend AGAINST': T.name_tr <= 0,
        'gap NOT against (>= -0.5%)': T.gap >= -0.5, 'gap not against AND OR >= 1%': (T.gap >= -0.5) & (T.orw >= 1), 'RV30 >= 25%': T.rv >= .25}
show('ALL taken (baseline)', T)
for n, m in cuts.items(): show(n, T[m])
print('\n=== D. exit variants on the TAKEN set')
PP = pd.read_pickle(OUT + 'paths.pkl').path
for n, kw in {'current +20/-20/120m': {}, '+30/-20/120m': dict(tgt=.3), '+20/-30/120m': dict(stop=.3), '+20/-20/60m': dict(mh=60), '+20/-20/180m': dict(mh=180),
              '+20/-20 no max hold (15:45)': dict(mh=None), 'trail: arm +15, give back 30%, -20 stop, 120m': dict(tgt=None, trail=(.15, .30)),
              'trail: arm +20, give back 25%, -20 stop, 15:45': dict(tgt=None, mh=None, trail=(.20, .25)), '+15/-15/120m': dict(tgt=.15, stop=.15)}.items():
    col = [ex(PP.loc[i], **kw) - FR for i in T.index]; t2 = T.assign(v=col); show(n, t2, 'v')
