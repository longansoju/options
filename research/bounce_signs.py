"""User 11-11 (MU 800C $1.01 -> $23.20): "research harder so you can get signs for these bounces".
Pre-specified test on 5y daily bars: for names in a deep drawdown, does anything KNOWN AT THE OPEN (gap, sector gap,
yesterday's move, days since the low) predict the open->close move? Outcome = underlying open->close, plus a 0.2-sigma
2-week call bought at the open and sold at the close (BS, IV = 1.0x / 1.3x RV30, 4% friction). IS/OOS = halves by date."""
import sys, math, time, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, yfinance as yf, config
from analysis import option_quotes as oq
NAMES = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION + ['AMD', 'SNDK']
def hist(s):
    for a in range(4):
        try:
            h = yf.Ticker(s).history(period='5y', interval='1d', auto_adjust=True)
            if len(h) > 200: h.index = h.index.tz_localize(None); return h
        except Exception: pass
        time.sleep(5)
    return None
smh = hist('SMH'); sg = (smh.Open / smh.Close.shift(1) - 1)
rows = []
for s in NAMES:
    h = hist(s)
    if h is None: print('skip', s); continue
    C, O, H, L = h.Close, h.Open, h.High, h.Low
    pc = C.shift(1); rv = np.log(C / pc).rolling(30).std().shift(1) * math.sqrt(252)
    dd = pc / C.shift(1).rolling(20).max() - 1
    r1 = pc / C.shift(2) - 1
    dsl = L.shift(1).rolling(10).apply(lambda x: len(x) - 1 - int(np.argmin(x)), raw=True)
    df = pd.DataFrame(dict(s=s, gap=O / pc - 1, oc=C / O - 1, oh=H / O - 1, ol=L / O - 1, dd=dd, r1=r1, dsl=dsl, rv=rv, O=O, C=C,
                           sgap=sg.reindex(h.index))).dropna()
    T0, T1 = 10 / 252, (10 - 1 + 0.02) / 252
    for m, lab in ((1.0, 'c10'), (1.3, 'c13')):
        v = df.rv * m; K = df.O * np.exp(0.2 * v * math.sqrt(T0))
        df[lab] = [oq.bs(c, k, T1, vv, 'call') / oq.bs(o, k, T0, vv, 'call') - 1 - 0.04 for o, c, k, vv in zip(df.O, df.C, K, v)]
    rows.append(df)
D = pd.concat(rows); D['date'] = D.index; cut = D.date.sort_values().iloc[len(D) // 2]
def rep(name, x):
    if len(x) < 15: print(f"{name:46s} n={len(x)} (too few)"); return
    i, o = x[x.date < cut], x[x.date >= cut]
    print(f"{name:46s} n={len(x):5d} days={x.date.nunique():4d} | o->c {x.oc.mean():+.2%} med {x.oc.median():+.2%} up {(x.oc>0).mean():.0%} | >=+3% {(x.oc>=.03).mean():.0%} <=-3% {(x.oc<=-.03).mean():.0%} | "
          f"IS {i.oc.mean():+.2%} OOS {o.oc.mean():+.2%} | call 1.0x {x.c10.mean():+.1%} 1.3x {x.c13.mean():+.1%} (med {x.c13.median():+.0%})")
B = D[D.dd <= -0.20]
print(f"{len(D)} name-days, {D.s.nunique()} names, {D.date.min().date()}..{D.date.max().date()}, IS/OOS cut {cut.date()}")
rep('A all days', D)
rep('B drawdown <= -20% (vs 20d high)', B)
rep('C B + gap up >= +2%', B[B.gap >= .02])
rep('D B + gap up >= +2% + SMH gap >= +1%', B[(B.gap >= .02) & (B.sgap >= .01)])
rep('E B + gap up >= +2% + yesterday >= +3%', B[(B.gap >= .02) & (B.r1 >= .03)])
rep('F B + gap up >= +2% + yesterday down', B[(B.gap >= .02) & (B.r1 < 0)])
rep('G B + gap up >= +2% + low >= 3 days old', B[(B.gap >= .02) & (B.dsl >= 3)])
rep('I B + gap up >= +4%', B[B.gap >= .04])
rep('H B + gap DOWN <= -2%', B[B.gap <= -.02])
rep('J no drawdown (> -5%) + gap up >= +2%', D[(D.dd > -.05) & (D.gap >= .02)])
D.to_pickle('/tmp/claude-0/-home-user-options/1900b617-71ad-55f2-b6c2-442b5e790faa/scratchpad/bounce_signs.pkl')
