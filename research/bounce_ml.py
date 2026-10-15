"""Bounce model: use ALL the intraday information, not the clock.
Candidates: name-days that are down over 3 days OR gapped down >= 1% (the bounce setups
the counter-trend gate blocks). Every 5m bar 10:00-14:30 is a decision point with features:
gap, return from open, distance off the day low (in daily sigmas), position in the day's
range, distance to prior close (gap-fill room), VWAP distance, last-30m return, volume
(cum relvol vs same clock 20d, and last-30m volume vs day avg), 3d decline, prior RSI,
sector (SMH) return from open + last 30m, relative strength vs SMH, bars since the low,
higher-low count. Label = the actual v2 call trade from that bar (0.2 sigma, 2 Fridays
out, +20/-20, 120m max, 15:45, 4% spread) -> win = P&L > 0.
Walk-forward both ways: train on the first half of sessions, test on the second, and
vice versa. Rule: per name-day, buy at the FIRST bar the model score exceeds the
train-half's 80th/90th percentile."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score
config.YF_INTER_CALL_DELAY = 0.15
TODAY = dt.date(2026, 10, 15)
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); return S * N(d1) - K * N(d1 - v * math.sqrt(T))


def T_at(ts, exp):
    return (max(16 * 60 - (ts.hour * 60 + ts.minute), 0) / 390 + int(np.busday_count(ts.date(), exp))) / 252


def bars(s):
    b = er.fetch_chart(s, '5m', '60d')
    return b[(b.index.time >= dt.time(9, 30)) & (b.index.time < dt.time(16, 0))].dropna()


if len(sys.argv) < 2:
    data = {s: (bars(s), er.daily_frame(s, '2y')) for s in SYMS + ['SMH']}
    pd.to_pickle(data, 'bounce_ml_data.pkl')
data = pd.read_pickle('bounce_ml_data.pkl')
smh_b = data['SMH'][0]
DAYS = sorted(set(smh_b.index.date))
print('sessions', len(DAYS), DAYS[0], '->', DAYS[-1], flush=True)


def trade(x, i, rv, day):
    C = x.C.values; ts = x.index[i]; S0 = C[i]
    exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 14)
    T0 = T_at(ts, exp); K = S0 * math.exp(0.2 * rv * math.sqrt(T0)); p0 = bs(S0, K, T0, rv)
    for j in range(i + 1, len(C)):
        t2 = x.index[j]; T = T_at(t2 + pd.Timedelta(minutes=5), exp)
        if bs(x.L.iloc[j], K, T, rv) / p0 - 1 <= -0.2: return -0.2
        if bs(x.H.iloc[j], K, T, rv) / p0 - 1 >= 0.2: return 0.2
        if (t2 - ts).total_seconds() >= 7200 or t2.time() >= dt.time(15, 45): return bs(C[j], K, T, rv) / p0 - 1
    return np.nan


rows = []
for s in SYMS:
    b, d = data[s]
    b = b.copy(); b['tod'] = b.index.time
    cum = b.groupby(b.index.date).V.cumsum()
    piv = pd.DataFrame({'d': b.index.date, 't': b.tod, 'c': cum.values}).pivot_table(index='d', columns='t', values='c')
    med = piv.rolling(20).median().shift(1)
    for day in DAYS[20:]:
        x = b[b.index.date == day]; h = d[d.index < day]; sm = smh_b[smh_b.index.date == day]
        if len(x) < 30 or len(h) < 60 or day not in med.index or len(sm) < 30: continue
        c = h.C; pc = c.iloc[-1]; ct3 = pc / c.iloc[-4] - 1; gap = x.O.iloc[0] / pc - 1
        if not (ct3 < 0 or gap <= -0.01): continue
        rv = float(c.pct_change().tail(30).std() * math.sqrt(252)); dsd = rv / math.sqrt(252)
        dl = c.diff(); g = dl.clip(lower=0).ewm(alpha=1 / 14).mean(); l = (-dl.clip(upper=0)).ewm(alpha=1 / 14).mean()
        rsi = float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1]))
        rel = x.V.cumsum().values / med.loc[day].reindex(x.tod).values
        vw = ((x.C * x.V).cumsum() / x.V.cumsum()).values
        C, H, L, V, O = x.C.values, x.H.values, x.L.values, x.V.values, x.O.iloc[0]
        smC = sm.C.reindex(x.index).ffill().values; smO = sm.O.iloc[0]
        lows = np.minimum.accumulate(L); highs = np.maximum.accumulate(H)
        for i in range(6, len(C)):
            t = x.index[i].time()
            if t < dt.time(10, 0) or t > dt.time(14, 30): continue
            lo_i = int(np.argmin(L[:i + 1]))
            swing = L[lo_i:i + 1]
            hl = int(sum(1 for k in range(1, len(swing)) if swing[k] > swing[k - 1]))
            smo = smC[i] / smO - 1 if not np.isnan(smC[i]) else np.nan
            rows.append(dict(
                sym=s, day=day, i=i, today=day == TODAY,
                gap=gap, ret_open=C[i] / O - 1, off_low=(C[i] - lows[i]) / (pc * dsd),
                range_pos=(C[i] - lows[i]) / max(highs[i] - lows[i], 1e-9), to_pc=C[i] / pc - 1,
                vwap=C[i] / vw[i] - 1, r30=C[i] / C[i - 6] - 1,
                relvol=min(rel[i], 10) if not np.isnan(rel[i]) else np.nan,
                v30=V[i - 5:i + 1].mean() / V[:i + 1].mean(), ct3=ct3, rsi=rsi,
                smh_open=smo, smh30=smC[i] / smC[i - 6] - 1 if not np.isnan(smC[i - 6]) else np.nan,
                rs=(C[i] / O - 1) - smo, since_low=i - lo_i, higher_lows=hl,
                pnl=np.nan if day == TODAY else trade(x, i, rv, day) - 0.04))
R = pd.DataFrame(rows)
R.to_pickle('bounce_ml_rows.pkl')
F = ['gap', 'ret_open', 'off_low', 'range_pos', 'to_pc', 'vwap', 'r30', 'relvol', 'v30', 'ct3', 'rsi',
     'smh_open', 'smh30', 'rs', 'since_low', 'higher_lows']
H_ = R[~R.today].dropna(subset=['pnl']).fillna(0); H_['win'] = (H_.pnl > 0).astype(int)
sess = sorted(H_.day.unique()); half = sess[len(sess) // 2]
A, B = H_[H_.day < half], H_[H_.day >= half]
print(f"candidate name-days {H_.groupby(['sym','day']).ngroups} | decision bars {len(H_)} | sessions {len(sess)} (split {half})")
print(f"baseline: every bar avg {H_.pnl.mean():+.1%} win {H_.win.mean():.0%} | first bar per name-day avg "
      f"{H_.sort_values('i').groupby(['sym','day']).first().pnl.mean():+.1%}\n")

models = {'logistic': lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=500)),
          'boosted trees': lambda: GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.7, random_state=0)}
for mname, mk in models.items():
    for tr, te, lab in ((A, B, 'train 1st half -> test 2nd'), (B, A, 'train 2nd half -> test 1st')):
        m = mk().fit(tr[F], tr.win); p_tr = m.predict_proba(tr[F])[:, 1]; p = m.predict_proba(te[F])[:, 1]
        te = te.assign(p=p)
        out = [f"{mname:13s} {lab}: OOS AUC {roc_auc_score(te.win, p):.3f}"]
        for q in (0.8, 0.9):
            thr = np.quantile(p_tr, q)
            first = te[te.p > thr].sort_values('i').groupby(['sym', 'day']).first()
            out.append(f"top{int(round((1-q)*100))}%: n={len(first)} avg {first.pnl.mean():+.1%} win {(first.pnl>0).mean():.0%}")
        print(' | '.join(out))
    if mname == 'boosted trees':
        m = mk().fit(H_[F], H_.win)
        imp = pd.Series(m.feature_importances_, F).sort_values(ascending=False)
        print('  importance (fit on all):', ', '.join(f"{k} {v:.2f}" for k, v in imp.head(6).items()))
        T = R[R.today].fillna(0)
        if len(T):
            T = T.assign(p=m.predict_proba(T[F])[:, 1]); thr = np.quantile(m.predict_proba(H_[F])[:, 1], 0.9)
            print(f"\nTODAY (10-15), latest bar per name, score vs top-10% line {thr:.2f}:")
            last = T.sort_values('i').groupby('sym').last().sort_values('p', ascending=False)
            print(last[['p', 'ret_open', 'to_pc', 'off_low', 'vwap', 'relvol', 'rs']].round(3).head(10).to_string())
            hit = T[T.p > thr].sort_values('i').groupby('sym').first()
            print('first top-10% bar today per name:', {k: str(v) for k, v in data['MU'][0].index[0:0].to_series().items()} or '',
                  {s: (data[s][0][data[s][0].index.date == TODAY].index[r.i].strftime('%H:%M'), round(r.p, 2)) for s, r in hit.iterrows()})
