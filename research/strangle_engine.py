"""Paper STRANGLE engine (user 10-20: "paper trade the strangle model as well").
Run once per session at ~15:50 ET:  python strangle_engine.py [fit]
  1. EXIT: every paper strangle opened on the previous session is marked at the current price
     (the backtest's "sell at next close" exit) and printed as SG EXIT lines.
  2. ENTER: scores the 26 names with the walk-forward-validated logistic model (research/
     strangle_bt.py, target = next-close strangle profit, OOS AUC 0.65), and for names above
     the model's top-decile line prints SG ENTRY: 0.2-sigma call + 0.2-sigma put, Friday
     >= 7 days out, both legs together <= $1,000, max 3 per night.
Backtest verdict (CLAUDE.md, 10-19): the top decile loses ~7%/night once IV is 1.15x RV, and
only breaks even if real IV is below ~1.1x RV30 - so this is a FORWARD TEST to compare
model fills against the real moomoo chain, not a claimed edge. Paper fills are BS at RV30,
the same convention as every other paper fill. Blocks: earnings today or next session (an
overnight hold through a print is a different trade), no verified earnings date.
`fit` refits weights from strangle_rows.pkl (run strangle_bt.py first) -> strangle_model.json."""
import sys, os, json, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join('/home/user/options/research', 'strangle_model.json')
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
FEATS = ['z_r1', 'z_gap', 'z_id', 'clv', 'z_rng', 'z_r3', 'z_r5', 'z_r10', 'ma20', 'ma50', 'volx',
         'smh_r1', 'smh_clv', 'rel_r1', 'qqq_r1', 'fomc', 'fri', 'rv']
TARGET, BUDGET, MAXN, SIG = 'close1_1.15', 1000.0, 3, 0.2
EARN = {k: dt.date.fromisoformat(v) for k, v in config.DAYTRADE_EARNINGS.items()}


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, k):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)


def inc(S): return 10.0 if S >= 1000 else 5.0 if S >= 500 else 2.5 if S >= 200 else 1.0 if S >= 50 else 0.5


def friday_after(day):
    e = day + dt.timedelta(days=(4 - day.weekday()) % 7)
    return e if (e - day).days >= 7 else e + dt.timedelta(days=7)


def T_at(now, exp):
    return (max(16 * 60 - (now.hour * 60 + now.minute), 0) / 390 + int(np.busday_count(now.date(), exp))) / 252


def fit():
    R = pd.read_pickle(os.path.join(HERE, 'strangle_rows.pkl'))
    X = R[FEATS].astype(float).fillna(0).values; mu, sd = X.mean(0), X.std(0) + 1e-9
    y = (R[TARGET] > 0).values.astype(float)
    w = er._logit_fit((X - mu) / sd, y, 5.0)
    p = er._logit_pred(w, (X - mu) / sd)
    thr = float(np.quantile(p[(R.year == R.year.max()).values], 0.9))   # top-decile line, latest year
    json.dump(dict(w=w.tolist(), mu=mu.tolist(), sd=sd.tolist(), thr=thr, feats=FEATS, target=TARGET,
                   fitted=str(dt.date.today()), rows=len(R)), open(MODEL, 'w'), indent=1)
    print(f"fitted on {len(R)} name-nights, top-decile threshold {thr:.3f} -> {MODEL}")


def run():
    M = json.load(open(MODEL)); w, mu, sd = np.array(M['w']), np.array(M['mu']), np.array(M['sd'])
    now = pd.Timestamp.now(tz='America/New_York'); today = now.date()
    nxt = pd.Timestamp(np.busday_offset(today, 1, roll='forward')).date()
    smh, qqq = er.daily_frame('SMH', '1y'), er.daily_frame('QQQ', '1y')
    book = pd.read_csv('/home/user/options/data/recommendations.csv')
    openr = book[(book.strategy == 'strangle') & (book.status == 'open') & (book.book == 'paper')]
    px = {}
    for _, r in openr.iterrows():                                   # ---- exits first
        s = r.symbol
        if s not in px: px[s] = float(er.fetch_chart(s, '1m', '1d').C.dropna().iloc[-1])
        exp = dt.date.fromisoformat(r.expiry); d0 = dt.date.fromisoformat(r.created_date)
        if d0 >= today: continue
        rv = float(r.thesis.split('RV30 ')[1].split('%')[0]) / 100
        p = bs(px[s], float(r.strike), T_at(now, exp), rv, r.direction) * 100
        print(f"SG EXIT {r.occ_code} | {s} {px[s]:.2f} | ~${p:.0f} vs entry ${r.entry_premium:.0f} ({p / r.entry_premium - 1:+.0%}) | next-close exit")
    cands = []
    for s in SYMS:                                                   # ---- entries
        try:
            d = er.daily_frame(s, '1y').dropna(); F = er.overnight_features(d, smh, qqq)
        except Exception as e:
            print(f"   skip {s}: {str(e)[:40]}"); continue
        x = F[FEATS].astype(float).fillna(0).iloc[-1].values
        score = float(er._logit_pred(w, ((x - np.array(mu)) / sd)[None, :])[0])
        why = []
        if s not in EARN: why.append('no verified earnings date')
        elif today <= EARN[s] <= nxt: why.append(f'earnings {EARN[s]} before the exit')
        cands.append((score, s, float(d.C.iloc[-1]), float(F.rv.iloc[-1]), why))
    cands.sort(reverse=True)
    print(f"[{now:%H:%M}ET] strangle model | line {M['thr']:.3f} | top scores: " + ', '.join(f"{s} {sc:.2f}" for sc, s, *_ in cands[:6]))
    n = 0
    for score, s, S, rv, why in cands:
        if score < M['thr'] or n >= MAXN: break
        if why: print(f"   SG signal {s} score {score:.2f} REJECTED: {'; '.join(why)}"); continue
        exp = friday_after(today); T = T_at(now, exp); sdv = rv * math.sqrt(T); st = inc(S)
        Kc = math.ceil(S * math.exp(SIG * sdv) / st) * st; Kp = math.floor(S * math.exp(-SIG * sdv) / st) * st
        pc, pp = bs(S, Kc, T, rv, 'call') * 100, bs(S, Kp, T, rv, 'put') * 100
        if pc + pp > BUDGET: print(f"   SG signal {s} score {score:.2f} REJECTED: strangle ${pc + pp:.0f} > ${BUDGET:.0f}"); continue
        occ = lambda k, K: f"{s}{exp.strftime('%y%m%d')}{k}{int(round(K * 1000)):08d}"
        print(f"*** SG ENTRY {s} score {score:.2f} | {s} {S:.2f} RV30 {rv:.0%} | CALL {occ('C', Kc)} ~${pc:.0f} + PUT {occ('P', Kp)} ~${pp:.0f}"
              f" = ${pc + pp:.0f} | exit at next close ({nxt})")
        n += 1
    if n == 0: print("   no strangle tonight")


if __name__ == '__main__':
    fit() if len(sys.argv) > 1 and sys.argv[1] == 'fit' else run()
