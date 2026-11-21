"""User 11-21: "if I took 1.5k and bought 10 of that contract ... 69k profit. If we can repeat this consistently it would
be very good passive income." PRE-SPECIFIED test of the exact setup, so the answer is a number, not an opinion:
signal day = gap up >= 3%, closes red, close in the bottom 10% of the day's range (11-19 MU). At that close buy a put
~1 daily-sigma OTM expiring the NEXT session (the MU 680P was ~1.3 daily sigma at the 690 close), sell at the next
close (expiry). Priced with Black-Scholes at IV = k x RV30 (real short-dated readings logged 1.3-2.1x), plus a 10%
round-trip friction. Also the mirror (call) and a straddle, because the next day is a coin flip in direction.
27 names, 5y daily. Prints the distribution and what a fixed $150/ticket bankroll would have done."""
import math, warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, yfinance as yf
N = ['MU','NVDA','AMD','AVGO','MRVL','TSM','ASML','SMCI','DELL','NBIS','COHR','ANET','VRT','STX','WDC','MPWR','NVTS','CRDO',
     'AAPL','MSFT','AMZN','META','GOOGL','PLTR','JPM','XOM','V']
Nc = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    if T <= 0: return max(S - K, 0) if k == 'call' else max(K - S, 0)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * Nc(d1) - K * Nc(d2) if k == 'call' else K * Nc(-d2) - S * Nc(-d1)
ev = []
for s in N:
    d = yf.Ticker(s).history(period='5y').dropna()
    if len(d) < 300: continue
    pc = d.Close.shift(); rv = np.log(d.Close / pc).rolling(30).std().shift() * 252 ** .5
    pos = (d.Close - d.Low) / (d.High - d.Low).replace(0, np.nan)
    sig = (d.Open / pc - 1 >= 0.03) & (d.Close / pc - 1 < 0) & (pos <= 0.10)
    for i in np.where(sig.values)[0]:
        if i + 1 >= len(d) or not rv.iloc[i] > 0: continue
        ev.append((d.index[i], s, float(d.Close.iloc[i]), float(d.Close.iloc[i + 1]), float(rv.iloc[i])))
E = pd.DataFrame(ev, columns=['day', 'sym', 'S0', 'S1', 'rv'])
T = 1 / 252
print(f"signal nights: {len(E)} over 5 years, 27 names (~{len(E)/5:.0f} a year)")
for mult in (1.0, 1.3, 1.6):
    for kind in ('put', 'call', 'straddle'):
        r = []
        for e in E.itertuples():
            v = e.rv * mult; sd = e.rv * math.sqrt(T)
            legs = ['put', 'call'] if kind == 'straddle' else [kind]
            cost = val = 0
            for k in legs:
                K = e.S0 * math.exp((-1 if k == 'put' else 1) * 1.0 * sd)
                cost += bs(e.S0, K, T, v, k); val += bs(e.S1, K, 0, v, k)
            r.append(val * 0.95 / (cost * 1.05) - 1)   # 10% round trip: pay ~5% over mid, sell ~5% under
        r = pd.Series(r)
        bank = 150 * len(r) + (150 * r).sum()
        print(f"  IV={mult:.1f}x RV  {kind:8s} avg {r.mean():+7.1%}  median {r.median():+6.1%}  win {(r > 0).mean():3.0%}  "
              f">=5x {(r >= 4).mean():4.1%}  lost >80% {(r <= -0.8).mean():3.0%}  | $150/ticket x {len(r)}: "
              f"spent ${150*len(r):,}, back ${bank:,.0f} ({(r.mean()):+.0%})")
