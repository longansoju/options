"""User 10-29: "be more accepting to 1-day ticket bets, they're low cost so they deserve a chance."
Earlier tests (lottery_overnight2.py, lottery_month.py) bought 1-DTE far-OTM tickets EVERY night:
~-30%/night. Never tested: only on EVENT nights, and holding into the next session with a resting
limit (the way the MU 960C actually paid - it kept rising after the open).
Ticket = 1-DTE call and/or put at k daily-sigma OTM, bought at the close, priced with the
overnight-variance correction (lottery_overnight2.py) and put skew; IV = RV30 x m.
Exits: OPEN = sell at the next open; LIMIT = resting +100% limit through the next session (filled if
the day's high/low reaches it, valued mid-session), else held to the close (expiry = intrinsic).
10% friction. Conditions are known at the entry close. IS/OOS split by date."""
import sys, math, json, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
config.YF_INTER_CALL_DELAY = 0.15
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    if T <= 0: return max(S - K, 0) if k == 'call' else max(K - S, 0)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
M = json.load(open('/home/user/options/research/strangle_model.json')); W, MU_, SD_ = map(np.array, (M['w'], M['mu'], M['sd']))
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION + ['SNDK']
MEM = {'MU', 'WDC', 'STX', 'SNDK'}
# memory-peer report days (same inference as peer_event.py; approximate +-1 day)
peer = set()
for tk, lo, hi in (('000660.KS', 19, 31), ('005930.KS', 3, 10)):
    k = er.daily_frame(tk, '5y').dropna(); k.index = pd.to_datetime(k.index); kq = k[k.index.month.isin([1, 4, 7, 10])]
    for (y, m), g in kq.groupby([kq.index.year, kq.index.month]):
        w = g[(g.index.day >= lo) & (g.index.day <= hi)]
        if len(w): peer.add(w.V.idxmax().date())
smh, qqq = er.daily_frame('SMH', '5y'), er.daily_frame('QQQ', '5y')
rows = []
for s in SYMS:
    try: d = er.daily_frame(s, '5y').dropna()
    except Exception as e: print('skip', s, e); continue
    F = er.overnight_features(d, smh, qqq); X = F[M['feats']].astype(float).fillna(0).values
    score = er._logit_pred(W, (X - MU_) / SD_)
    c = d.C; cc = np.log(c / c.shift(1)); gp = np.log(d.O / c.shift(1))
    f = float(np.clip((gp ** 2).tail(500).mean() / (cc ** 2).tail(500).mean(), 0.05, 0.9))
    rv = cc.rolling(30).std() * math.sqrt(252); volx = d.V / d.V.rolling(20).mean(); rz = ((d.H - d.L) / c) / c.pct_change().rolling(20).std()
    idx = list(d.index)
    for i in range(60, len(idx) - 1):
        S, v = float(c.iloc[i]), float(rv.iloc[i])
        if not v > 0: continue
        nx = pd.Timestamp(idx[i + 1]).date(); O, H, L, C1 = (float(d[x].iloc[i + 1]) for x in ('O', 'H', 'L', 'C'))
        r = dict(sym=s, day=pd.Timestamp(idx[i]).date(), score=float(score[i]), fomc=bool(F.fomc.iloc[i]),
                 peer=(s in MEM and nx in peer), big=bool(volx.iloc[i] > 1.5 and rz.iloc[i] > 2), prem=0.0)
        sd = v * math.sqrt(1 / 252)
        for kk in (1.0,):
            for m in (1.0, 1.15, 1.3, 1.5):
                for side, g_ in (('call', 1), ('put', -1)):
                    K = S * math.exp(g_ * kk * sd); iv = v * m * ((1 + 0.15 * kk) if side == 'put' else 1)
                    p0 = bs(S, K, 1 / 252, iv, side)
                    if p0 < 0.02: r[f'{side}{kk}_{m}_open'] = r[f'{side}{kk}_{m}_lim'] = np.nan; continue
                    r[f'{side}{kk}_{m}_open'] = bs(O, K, (1 - f) / 252, iv, side) / p0 - 1 - 0.10
                    vo = bs(O, K, (1 - f) / 252, iv, side) / p0 - 1; best = max(vo, bs(H if side == 'call' else L, K, (1 - f) / 2 / 252, iv, side) / p0 - 1)
                    r[f'{side}{kk}_{m}_lim'] = (max(vo, 1.0) if best >= 1.0 else bs(C1, K, 0, iv, side) / p0 - 1) - 0.10
                    if kk == 1.0 and m == 1.0: r[f'{side}_px'] = p0 * 100
        rows.append(r)
R = pd.DataFrame(rows); R.to_pickle('/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/lottery_event.pkl')
days = sorted(R.day.unique()); cut = days[len(days) // 2]
thr = np.quantile(R.score, 0.9)
CONDS = {'every night': R.index == R.index, 'strangle-model top 10% (in-sample weights)': R.score >= thr,
         'FOMC nights': R.fomc, 'memory-peer report nights': R.peer, 'volume > 1.5x AND range > 2 sd': R.big}
print(f"{len(R)} name-nights {days[0]}..{days[-1]} | median 1-sigma ticket: call ${R.call_px.median():.0f}, put ${R.put_px.median():.0f}")
for col, lab in (('{s}1.0_{m}_open', '1.0σ sell at OPEN'), ('{s}1.0_{m}_lim', '1.0σ +100% resting limit, else to close'),
):
    print(f"\n=== {lab}")
    for name, msk in CONDS.items():
        g = R[msk]; out = []
        for m in (1.0, 1.15, 1.3, 1.5):
            both = (g[col.format(s='call', m=m)] + g[col.format(s='put', m=m)]) / 2
            E = both.groupby(g.day).mean()     # one bet per night (names move together)
            i, o = E[E.index < cut], E[E.index >= cut]
            out.append(f"IV {m}x: pair {both.mean():+6.1%} | per-night {E.mean():+6.1%} (IS {i.mean():+6.1%} / OOS {o.mean():+6.1%}) "
                       f"hit+100% {(both >= 0.9).mean():.0%}")
        c1 = g[col.format(s='call', m=1.0)]; p1 = g[col.format(s='put', m=1.0)]
        print(f"  {name:44s} n={len(g):6d} nights={g.day.nunique():4d} | calls {c1.mean():+6.1%} puts {p1.mean():+6.1%}\n      " + "\n      ".join(out))
