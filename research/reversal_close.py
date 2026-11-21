"""User 11-21 (MU 261120 680P, bought 1.50, sold 10.00 on 11-19, expired at 88.01): "could there have been signs it
would go way below 680?" On 11-19 MU gapped UP +5% (740), ran to 760, then reversed to CLOSE AT THE LOW (690.44, -2.1%)
on 35M shares. PRE-SPECIFIED question: after a gap-up that fails and closes at the day's low, is the NEXT day unusually
bearish? 5y daily, 27 names. Condition A: gap >= +3% AND close < prior close AND close in the bottom 10% of the day's range.
Baseline = every day. Next-day close/close return, P(next day <= -5%), P(next day >= +5%). IS/OOS halves by date."""
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, yfinance as yf
N = ['MU','NVDA','AMD','AVGO','MRVL','TSM','ASML','SMCI','DELL','NBIS','COHR','ANET','VRT','STX','WDC','MPWR','NVTS','CRDO',
     'AAPL','MSFT','AMZN','META','GOOGL','PLTR','JPM','XOM','V']
rows = []
for s in N:
    d = yf.Ticker(s).history(period='5y').dropna()
    if len(d) < 300: continue
    pc = d.Close.shift(); gap = d.Open / pc - 1; ret = d.Close / pc - 1
    pos = (d.Close - d.Low) / (d.High - d.Low).replace(0, np.nan)
    nxt = d.Close.shift(-1) / d.Close - 1
    f = pd.DataFrame(dict(sym=s, gap=gap, ret=ret, pos=pos, nxt=nxt)).dropna()
    rows.append(f)
D = pd.concat(rows); cut = D.index.sort_values()[len(D) // 2]
A = D[(D.gap >= 0.03) & (D.ret < 0) & (D.pos <= 0.10)]
B = D[(D.gap >= 0.03) & (D.ret < 0)]                      # failed gap-up, any close
C = D[(D.pos <= 0.10) & (D.ret <= -0.02)]                 # closed at the low on a down day, no gap condition
def line(lab, x):
    i, o = x[x.index < cut], x[x.index >= cut]
    print(f"{lab:46s} n={len(x):5d} next-day avg {x.nxt.mean():+.2%} (IS {i.nxt.mean():+.2%} / OOS {o.nxt.mean():+.2%}) "
          f"| down>=5% {(x.nxt <= -0.05).mean():5.1%} | up>=5% {(x.nxt >= 0.05).mean():5.1%} | down at all {(x.nxt < 0).mean():.0%}")
line('every day (baseline)', D)
line('B failed gap-up (gap>=3%, closed red)', B)
line('A same + closed in bottom 10% of range', A)
line('C closed at the low on a >=2% down day', C)
print('\nMU only:'); line('  MU baseline', D[D.sym == 'MU']); line('  MU condition A', A[A.sym == 'MU'])
