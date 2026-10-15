"""User's pattern: buy a 1-day-to-expiry far-OTM PUT at the close, sell next morning.
Daily bars, 2y, 27 names. BS at RV30 (understates real OTM-put prices -> optimistic).
Sell at next OPEN (realistic for GMT+8) and, as an upper bound, at next-day LOW."""
import math, datetime as dt
import numpy as np, pandas as pd
data=pd.read_pickle('trend_data.pkl')
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def put(S,K,T,v):
    T=max(T,1e-6); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T); return K*N(-d2)-S*N(-d1)
rows=[]
for s,d in data.items():
    c=d.C; rv=c.pct_change().rolling(30).std()*math.sqrt(252); ct3=c/c.shift(3)-1
    for i in range(40,len(d)-1):
        S=c.iloc[i]; v=rv.iloc[i]
        if not v>0: continue
        sd=v*math.sqrt(1/252)
        for k in (1.0,1.5,2.0):
            K=S*math.exp(-k*sd); p0=put(S,K,1/252,v)
            if p0<0.01: continue
            o=d.O.iloc[i+1]; lo=d.L.iloc[i+1]
            rows.append(dict(sym=s,day=d.index[i],k=k,open_ret=put(o,K,1/252,v)/p0-1,low_ret=put(lo,K,0.5/252,v)/p0-1,
                             gap=(o/S-1)*100,down3=ct3.iloc[i]<0,ai=s not in ('JPM','V','XOM','AAPL','AMZN','MSFT','GOOGL','META')))
R=pd.DataFrame(rows); FR=0.10
for k,g in R.groupby('k'):
    print(f"\n{k}σ OTM 1-DTE put, n={len(g)} name-nights")
    for lab,h in (('every night',g),('only after a 3-day decline',g[g.down3]),('AI-hardware names only',g[g.ai])):
        print(f"  {lab:28s} sell at OPEN avg {h.open_ret.mean()-FR:+.1%} | >=+100% {(h.open_ret>=1).mean():.1%} | >=+400% {(h.open_ret>=4).mean():.1%} | expired-ish (<-80%) {(h.open_ret<-0.8).mean():.0%} || best case sell at LOW avg {h.low_ret.mean()-FR:+.1%}")
g=R[R.k==1.5]; print('\nhow often the next open gaps down >=4%:',f"{(g.gap<=-4).mean():.1%}", '| on those nights, 1.5σ put at open avg',f"{g[g.gap<=-4].open_ret.mean():+.0%}")
