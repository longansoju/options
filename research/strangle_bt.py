"""Event-night STRANGLE test (user 10-19: "train yourself to catch this").
At a session close buy a 0.2-sigma OTM call + 0.2-sigma OTM put (expiry: the Friday
>= 7 days out), sell BOTH at (A) the next open, (B) the next close, (C) the close two
sessions later. Direction-free: pays if the next move is big either way.
Pricing (corrected, per the 10-15 artifact lesson): vol = RV30 at entry; entry IV =
vol x K_IV (real IV sits above realized, more so after selloffs), exit IV = vol (the
premium is lost); overnight-only exits charge the name's measured overnight share of
daily variance; 4% round-trip friction on the strangle. 26 names + SMH/QQQ, 5y daily.
Conditions are fixed rules; then a walk-forward logistic model (expanding window,
refit yearly, features known at the close = analysis/event_radar.overnight_features)
learns which nights the strangle pays - the 'train yourself' part. IS/OOS by date."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
config.YF_INTER_CALL_DELAY = 0.15
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
FR, SIG = 0.04, 0.2

if len(sys.argv) < 2:
    raw = {s: er.daily_frame(s, '5y') for s in SYMS + ['SMH', 'QQQ']}
    pd.to_pickle(raw, 'strangle_data.pkl')
raw = pd.read_pickle('strangle_data.pkl')
smh, qqq = raw['SMH'], raw['QQQ']


def friday_after(day):
    e = day + dt.timedelta(days=(4 - day.weekday()) % 7)
    return e if (e - day).days >= 7 else e + dt.timedelta(days=7)


rows = []
for s in SYMS:
    d = raw[s].dropna()
    if len(d) < 300: continue
    F = er.overnight_features(d, smh, qqq)
    c, o = d.C, d.O
    cc = np.log(c / c.shift(1)); gp = np.log(o / c.shift(1))
    f_on = float(np.clip((gp ** 2).tail(500).mean() / (cc ** 2).tail(500).mean(), 0.05, 0.9))
    idx = list(d.index)
    for i in range(60, len(idx) - 2):
        day = idx[i]; vol = F.rv.iloc[i]
        if not vol > 0: continue
        exp = friday_after(day); bd = int(np.busday_count(day, exp)); T0 = bd / 252
        S0 = c.iloc[i]
        Kc, Kp = S0 * math.exp(SIG * vol * math.sqrt(T0)), S0 * math.exp(-SIG * vol * math.sqrt(T0))
        rec = dict(sym=s, day=day, **{k: F[k].iloc[i] for k in F.columns if k not in ('C', 'gap_next', 'big_up', 'big_dn')})
        for kiv in (1.0, 1.15):
            p0 = float(er._bs(S0, Kc, T0, vol * kiv, True) + er._bs(S0, Kp, T0, vol * kiv, False))
            for lab, S1, T1 in (('open', o.iloc[i + 1], T0 - f_on / 252), ('close1', c.iloc[i + 1], T0 - 1 / 252),
                                ('close2', c.iloc[i + 2], T0 - 2 / 252)):
                p1 = float(er._bs(S1, Kc, max(T1, 1e-5), vol, True) + er._bs(S1, Kp, max(T1, 1e-5), vol, False))
                rec[f'{lab}_{kiv}'] = p1 / p0 - 1 - FR
        rows.append(rec)
R = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
R['year'] = pd.to_datetime(R.day).dt.year
R.to_pickle('strangle_rows.pkl')
cut = sorted(R.day.unique())[len(R.day.unique()) // 2]
print(f"name-nights {len(R)} | {R.day.min()} -> {R.day.max()} | IS/OOS split {cut}\n")

smh_r = smh.C.pct_change(); smh_2d = smh.C.pct_change(2)
R['smh1'] = R.day.map(smh_r); R['smh2'] = R.day.map(smh_2d)
COND = {'every night': R.index == R.index,
        'Fridays (weekend hold)': R.fri.astype(bool),
        'FOMC nights': R.fomc.astype(bool),
        'name moved > 2 sd today': R.z_r1.abs() > 2,
        'SMH day <= -2%': R.smh1 <= -0.02,
        'SMH 2-day <= -4% (10-15/16 type)': R.smh2 <= -0.04,
        'SMH 2-day <= -4% AND Friday': (R.smh2 <= -0.04) & R.fri.astype(bool),
        'volume > 1.5x and range > 2 sd': (R.volx > np.log(1.5)) & (R.z_rng > 2)}


def line(name, g, col):
    i, o = g[g.day < cut][col], g[g.day >= cut][col]
    nights = g.day.nunique()
    return (f"  {name:34s} n={len(g):5d} ({nights:4d} nights) | win {(g[col] > 0).mean():.0%} avg {g[col].mean():+6.1%} "
            f"med {g[col].median():+6.1%} | IS {i.mean():+6.1%} OOS {o.mean():+6.1%}")


for col in ('open_1.0', 'close1_1.0', 'close2_1.0', 'close1_1.15', 'close2_1.15'):
    print(f"=== exit {col.split('_')[0]}, entry IV = RV x {col.split('_')[1]} ===")
    for name, m in COND.items():
        print(line(name, R[m], col))
    print()

# ---- walk-forward: learn which nights pay (label = strangle P&L > 0), refit yearly on all prior years
FEATS = ['z_r1', 'z_gap', 'z_id', 'clv', 'z_rng', 'z_r3', 'z_r5', 'z_r10', 'ma20', 'ma50', 'volx',
         'smh_r1', 'smh_clv', 'rel_r1', 'qqq_r1', 'fomc', 'fri', 'rv']
X = R[FEATS].astype(float).fillna(0).values
mu, sd_ = X.mean(0), X.std(0) + 1e-9
Xs = (X - mu) / sd_
for col in ('close1_1.15', 'close2_1.15', 'open_1.0'):
    y = (R[col] > 0).values.astype(float)
    score = np.full(len(R), np.nan)
    yrs = sorted(R.year.unique())
    for yr in yrs[2:]:
        tr = (R.year < yr).values; te = (R.year == yr).values
        w = er._logit_fit(Xs[tr], y[tr], 5.0)
        score[te] = er._logit_pred(w, Xs[te])
    T = R.assign(score=score).dropna(subset=['score'])
    print(f"=== WALK-FORWARD model, target = {col} profitable (test years {yrs[2]}..{yrs[-1]}) ===")
    print(f"  OOS AUC {er._auc(T[col] > 0, T.score):.3f}")
    for yr, g in T.groupby('year'):
        top = g[g.score >= g.score.quantile(0.9)]
        print(f"  {yr}: all {g[col].mean():+6.1%} | model top 10% {top[col].mean():+6.1%} (n={len(top)}, win {(top[col]>0).mean():.0%})")
    top = T[T.score >= T.groupby('year').score.transform(lambda s: s.quantile(0.9))]
    print(f"  ALL TEST YEARS: model top 10% avg {top[col].mean():+.1%} med {top[col].median():+.1%} win {(top[col]>0).mean():.0%} n={len(top)}"
          f" | everything {T[col].mean():+.1%}")
    w = er._logit_fit(Xs, y, 5.0)
    imp = sorted(zip(FEATS, w[1:]), key=lambda t: -abs(t[1]))[:6]
    print('  strongest features:', ', '.join(f"{k} {v:+.2f}" for k, v in imp))
    last = R[R.day == R.day.max()]
    print(f"  {R.day.max()} close scores (top 5):",
          [(r.sym, round(float(p), 2)) for p, r in sorted(zip(er._logit_pred(w, (last[FEATS].astype(float).fillna(0).values - mu) / sd_), last.itertuples()), key=lambda t: -t[0])[:5]])
    print()
# the 10-16 -> 10-19 weekend specifically
fri = R[R.day == dt.date(2026, 10, 16)]
if len(fri):
    print('10-16 close -> 10-19 (Friday weekend strangle):', f"open {fri['open_1.0'].mean():+.1%}", f"close1 IV1.15 {fri['close1_1.15'].mean():+.1%}")
