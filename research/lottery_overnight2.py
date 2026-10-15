"""Corrected: charge overnight variance. At the close a 1-DTE option carries one full day
of variance (overnight + session). At the next open only the session part remains:
T_open = (1 - f)/252, f = per-name overnight share of daily variance (measured). Skew:
far-OTM puts priced at IV = RV * (1 + 0.15*k) (sticky strike, same at entry and exit)."""
import math, numpy as np, pandas as pd
data=pd.read_pickle('trend_data.pkl')
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def put(S,K,T,v):
    T=max(T,1e-7); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T); return K*N(-d2)-S*N(-d1)
rows=[]; fs=[]
for s,d in data.items():
    c=d.C; gap=np.log(d.O/c.shift(1)); cc=np.log(c/c.shift(1))
    f=float((gap**2).tail(250).mean()/(cc**2).tail(250).mean()); f=min(max(f,0.05),0.9); fs.append((s,round(f,2)))
    rv=cc.rolling(30).std()*math.sqrt(252); ct3=c/c.shift(3)-1
    for i in range(40,len(d)-1):
        S=c.iloc[i]; v=rv.iloc[i]
        if not v>0: continue
        for k in (1.0,1.5,2.0):
            iv=v*(1+0.15*k); K=S*math.exp(-k*v*math.sqrt(1/252)); p0=put(S,K,1/252,iv)
            if p0<0.01: continue
            o=d.O.iloc[i+1]; lo=d.L.iloc[i+1]
            rows.append(dict(k=k,open_ret=put(o,K,(1-f)/252,iv)/p0-1,low_ret=put(lo,K,(1-f)/2/252,iv)/p0-1,down3=ct3.iloc[i]<0))
print('overnight share of daily variance (sample):',fs[:8])
R=pd.DataFrame(rows); FR=0.10
for k,g in R.groupby('k'):
    print(f"{k}σ OTM 1-DTE put n={len(g)}: sell at OPEN avg {g.open_ret.mean()-FR:+.1%} (after 3d decline {g[g.down3].open_ret.mean()-FR:+.1%}) | >=+100% {(g.open_ret>=1).mean():.1%} | >=+400% {(g.open_ret>=4).mean():.1%} | lose >80% {(g.open_ret<-0.8).mean():.0%} | median {g.open_ret.median():+.0%} || best-case LOW avg {g.low_ret.mean()-FR:+.1%}")
