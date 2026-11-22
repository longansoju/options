"""User 11-22: "can I use VWAP and BOLL to make better decisions". PRE-SPECIFIED daily test of Bollinger(20, 2) on the
27 names, 5y daily: (1) DIRECTION - close above the upper / below the lower band -> next-day and next-5-day return
in that direction vs all days; (2) TIMING - band-width squeeze (width in the bottom 10% of its last 120 days) ->
next-5-day absolute move in daily sigma vs all days. IS / OOS = first / second half of the dates."""
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, yfinance as yf
N = ['MU','NVDA','AMD','AVGO','MRVL','TSM','ASML','SMCI','DELL','NBIS','COHR','ANET','VRT','STX','WDC','MPWR','NVTS','CRDO',
     'AAPL','MSFT','AMZN','META','GOOGL','PLTR','JPM','XOM','V']
R = []
for s in N:
    d = yf.Ticker(s).history(period='5y').dropna(); c = d.Close
    if len(d) < 300: continue
    m, sd = c.rolling(20).mean(), c.rolling(20).std(); up, lo = m + 2 * sd, m - 2 * sd
    w = (up - lo) / m; sq = w <= w.rolling(120).quantile(0.10)
    dsig = np.log(c / c.shift()).rolling(30).std()
    r1 = c.shift(-1) / c - 1; r5 = c.shift(-5) / c - 1
    R.append(pd.DataFrame(dict(day=d.index, above=c > up, below=c < lo, sq=sq, r1=r1, r5=r5,
                               mv5=(np.log(c.shift(-5) / c)).abs() / (dsig * 5 ** .5))).dropna())
D = pd.concat(R); mid = D.day.sort_values().iloc[len(D) // 2]
def row(lab, x, col, sign=1):
    v = x[col] * sign; i, o = v[x.day < mid], v[x.day >= mid]
    print(f"  {lab:44s} n={len(x):6d}  {col} {v.mean():+.2%}  up-share {(v > 0).mean():.0%}  (IS {i.mean():+.2%} / OOS {o.mean():+.2%})")
print('DIRECTION (return measured in the direction of the band break)')
for col in ('r1', 'r5'):
    row('all days (long)', D, col)
    row('close ABOVE upper band -> keep going up?', D[D.above], col)
    row('close BELOW lower band -> keep going down?', D[D.below], col, -1)
print('TIMING (next-5-day absolute move in daily sigma; 2.24 = 1 x sqrt(5) would be "normal")')
for lab, x in (('all days', D), ('squeeze (width bottom 10%)', D[D.sq]), ('after a band break', D[D.above | D.below])):
    print(f"  {lab:30s} n={len(x):6d} mean |move| {x.mv5.mean():.2f} sd   big (>2 sd) {(x.mv5 > 2).mean():.0%}   "
          f"IS {x[x.day < mid].mv5.mean():.2f} / OOS {x[x.day >= mid].mv5.mean():.2f}")
