"""User 11-21: "verify that your triggers have good coverage, you shouldn't miss out on such opportunities".
PRE-SPECIFIED coverage test of the reversal-ticket trigger (5 variants, written down before running).
OPPORTUNITY = a night where a ~1.0 daily-sigma OTM option, bought at the close and sold at the NEXT close, returned
>= 4x (+300%) priced at IV = RV30 (put side: next day fell; call side: next day rose). For every variant:
  coverage  = share of opportunities the trigger flagged the night before
  n / avg   = how many signals and what they returned on average (10% round-trip friction) at IV = 1.0 / 1.1 / 1.3x RV,
              split IS / OOS by date (first / second half of the 5 years)
Vehicle note: the next-session expiry exists every night only on M/W/F-expiry names; on other nights we test the
NEAREST Friday (T up to 5 sessions, sold at the next close with its remaining time value).
Variants:
  V0  current:  gap >= +3%, closes below prior close, in bottom 10% of range -> put
  V1  looser:   gap >= +2%, closes below prior close, bottom 20%             -> put
  V2  mirror:   gap <= -3%, closes above prior close, top 10%               -> call
  V3  V0 + V2 (both directions of the same failed-gap reversal)
  V4  any close at the extreme (bottom/top 10%) on volume > 1.5x and range > 2 sd -> put / call (direction of the close)
Also: quarter-Kelly size per IV bucket for V3, for the sizing question ("make the cap more loose")."""
import math, warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, yfinance as yf
N = ['MU','NVDA','AMD','AVGO','MRVL','TSM','ASML','SMCI','DELL','NBIS','COHR','ANET','VRT','STX','WDC','MPWR','NVTS','CRDO',
     'AAPL','MSFT','AMZN','META','GOOGL','PLTR','JPM','XOM','V']
DAILY = {'NVDA','AAPL','MSFT','AMZN','META','GOOGL','MU'}
Nc = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    if T <= 1e-9: return max(S - K, 0) if k == 'call' else max(K - S, 0)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * Nc(d1) - K * Nc(d2) if k == 'call' else K * Nc(-d2) - S * Nc(-d1)
rows = []
for s in N:
    d = yf.Ticker(s).history(period='5y').dropna()
    if len(d) < 300: continue
    pc = d.Close.shift(); lr = np.log(d.Close / pc)
    rv = lr.rolling(30).std().shift() * 252 ** .5
    rng = (d.High - d.Low) / pc; rsd = rng.rolling(30).std().shift(); rmu = rng.rolling(30).mean().shift()
    vol = d.Volume / d.Volume.rolling(20).mean().shift()
    pos = (d.Close - d.Low) / (d.High - d.Low).replace(0, np.nan)
    gap = d.Open / pc - 1
    for i in range(31, len(d) - 1):
        if not rv.iloc[i] > 0: continue
        day = d.index[i]; wd = day.weekday()
        if s in DAILY: nxt_days = 1 if wd in (1, 3, 4) else 2          # next session is Mon/Wed/Fri -> 1, else 2
        else: nxt_days = {0: 4, 1: 3, 2: 2, 3: 1, 4: 5}[wd]             # weekly-only: the coming Friday
        rows.append(dict(day=day, sym=s, S0=d.Close.iloc[i], S1=d.Close.iloc[i + 1], rv=rv.iloc[i], gap=gap.iloc[i],
                         chg=d.Close.iloc[i] / pc.iloc[i] - 1, pos=pos.iloc[i], vol=vol.iloc[i],
                         big=(rng.iloc[i] - rmu.iloc[i]) / rsd.iloc[i] > 2, Tn=nxt_days))
D = pd.DataFrame(rows).dropna(subset=['pos'])
def ret(e, k, mult, nearest=False):
    T0 = (e.Tn if nearest else 1) / 252; sd = e.rv / math.sqrt(252); v = e.rv * mult
    K = e.S0 * math.exp((-1 if k == 'put' else 1) * sd)
    return bs(e.S1, K, T0 - 1 / 252, v, k) * 0.95 / (bs(e.S0, K, T0, v, k) * 1.05) - 1
D['rp'] = [ret(e, 'put', 1.0) for e in D.itertuples()]; D['rc'] = [ret(e, 'call', 1.0) for e in D.itertuples()]
opp_p, opp_c = D.rp >= 3, D.rc >= 3
print(f"name-nights {len(D):,}; opportunities (>= 4x at IV=RV): puts {opp_p.sum()} ({opp_p.mean():.1%}), calls {opp_c.sum()} ({opp_c.mean():.1%})")
mid = D.day.sort_values().iloc[len(D) // 2]
sigP = {'V0': (D.gap >= .03) & (D.chg < 0) & (D.pos <= .10),
        'V1': (D.gap >= .02) & (D.chg < 0) & (D.pos <= .20),
        'V4': (D.pos <= .10) & (D.vol > 1.5) & D.big}
sigC = {'V2': (D.gap <= -.03) & (D.chg > 0) & (D.pos >= .90),
        'V4': (D.pos >= .90) & (D.vol > 1.5) & D.big}
def report(name, mp, mc):
    sp = D[mp] if mp is not None else D.iloc[0:0]; sc = D[mc] if mc is not None else D.iloc[0:0]
    cov = ((mp if mp is not None else False) & opp_p).sum() + ((mc if mc is not None else False) & opp_c).sum()
    out = f"{name:34s} n={len(sp)+len(sc):4d} ({(len(sp)+len(sc))/5:4.0f}/yr) coverage {cov / (opp_p.sum() + opp_c.sum()):5.1%}"
    for mult in (1.0, 1.1, 1.3):
        for nearest in (False,):
            r = pd.concat([pd.Series([ret(e, 'put', mult) for e in sp.itertuples()], index=sp.day, dtype=float),
                           pd.Series([ret(e, 'call', mult) for e in sc.itertuples()], index=sc.day, dtype=float)])
            out += f" | {mult:.1f}x {r.mean():+5.0%} (IS {r[r.index < mid].mean():+4.0%} / OOS {r[r.index >= mid].mean():+4.0%})"
    print(out); return pd.concat([sp.assign(k='put'), sc.assign(k='call')])
print('\nvariant                             signals            coverage   avg at IV = k x RV (IS / OOS), next-session expiry')
report('V0 current: failed gap-up -> put', sigP['V0'], None)
report('V1 looser: gap>=2%, bottom 20%', sigP['V1'], None)
report('V2 mirror: failed gap-down -> call', None, sigC['V2'])
S3 = report('V3 = V0 + V2', sigP['V0'], sigC['V2'])
report('V4 big-volume close at extreme', sigP['V4'], sigC['V4'])
# nearest-expiry vehicle for V3
print('\nV3 with the NEAREST listed expiry (non-daily names off-Thursday hold a Friday 2-5 sessions out):')
for mult in (1.0, 1.1, 1.3):
    r = pd.Series([ret(e, e.k, mult, nearest=True) for e in S3.itertuples()])
    print(f"   {mult:.1f}x RV: avg {r.mean():+.0%}  median {r.median():+.0%}  win {(r > 0).mean():.0%}")
print(f"   share of V3 signals where the next-session expiry exists: {(S3.Tn == 1).mean():.0%}")
# what the opportunities were, if not reversal signals
O = D[opp_p | opp_c]
print(f"\nthe {len(O)} opportunities: big-volume day the night before {(O.vol > 1.5).mean():.0%} (all nights {(D.vol > 1.5).mean():.0%}); "
      f"range > 2 sd {O.big.mean():.0%} (all {D.big.mean():.0%}); closed in the bottom/top 10% {((O.pos <= .1) | (O.pos >= .9)).mean():.0%} (all {((D.pos <= .1) | (D.pos >= .9)).mean():.0%})")
# Kelly by IV bucket
print('\nsizing (V3, next-session vehicle): growth-optimal fraction of equity per ticket, and a quarter of it')
for mult in (0.8, 0.9, 1.0, 1.1, 1.2):
    r = np.array([ret(e, e.k, mult) for e in S3.itertuples()])
    fs = np.linspace(0, 0.3, 301); g = [np.mean(np.log1p(f * r)) for f in fs]; fk = fs[int(np.argmax(g))]
    bt = []
    rng_ = np.random.default_rng(0)
    for _ in range(300):
        rb = rng_.choice(r, len(r)); bt.append(fs[int(np.argmax([np.mean(np.log1p(f * rb)) for f in fs[::10]]) * 10)])
    print(f"   IV {mult:.1f}x RV: avg {r.mean():+5.0%}, full Kelly {fk:5.1%}, quarter {fk/4:5.1%}; bootstrap Kelly = 0 in {np.mean(np.array(bt) == 0):.0%} of resamples")

# ---- follow-up (same run, appended before looking at anything new): the set to adopt = V0 put + V4 both sides
S5 = pd.concat([D[sigP['V0'] | sigP['V4']].assign(k='put'), D[sigC['V4']].assign(k='call')])
print(f"\nV0 + V4 combined: n={len(S5)} ({len(S5)/5:.0f}/yr), coverage {((sigP['V0'] | sigP['V4']) & opp_p).sum() + (sigC['V4'] & opp_c).sum()} opps")
for nearest in (False, True):
    for mult in (0.9, 1.0, 1.1, 1.2, 1.3):
        r = pd.Series([ret(e, e.k, mult, nearest) for e in S5.itertuples()], index=S5.day)
        fs = np.linspace(0, 0.3, 301); fk = fs[int(np.argmax([np.mean(np.log1p(f * r.values)) for f in fs]))]
        print(f"   {'nearest expiry ' if nearest else 'next-session   '} {mult:.1f}x: avg {r.mean():+5.0%} (IS {r[r.index < mid].mean():+4.0%} / OOS {r[r.index >= mid].mean():+4.0%}) "
              f"median {r.median():+4.0%} win {(r > 0).mean():3.0%} | full Kelly {fk:5.1%}  longest losing run {max(len(x) for x in ''.join('L' if v <= 0 else 'W' for v in r.sort_index()).split('W')):d}")
