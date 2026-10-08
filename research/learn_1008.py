import sys, math, datetime as dt
sys.path.insert(0,'/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def bs(S,K,T,v,k):
    T=max(T,1e-6); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T)
    return S*N(d1)-K*N(d2) if k=='call' else K*N(-d2)-S*N(-d1)
EXP=dt.date(2026,10,23)
def T_at(ts): return (max(16*60-(ts.hour*60+ts.minute),0)/390+int(np.busday_count(ts.date(),EXP)))/252
pre=pd.read_pickle('sweep_pre.pkl')
# A) today's put signals blocked only by counter-trend (or budget): what would they have done?
print('A) blocked puts today, simulated with v2 rules (+20/-20/120m/15:45):')
for s,et in [('MSFT','12:57'),('MRVL','12:59'),('MU','12:59'),('ANET','13:00'),('AMZN','13:10'),('PLTR','13:33'),('META','12:57')]:
    x=er.fetch_chart(s,'1m','1d').dropna(); x=x[(x.V>0)&(x.index.time>=dt.time(9,30))]
    ts=x.index[x.index.strftime('%H:%M')>=et][0]; S0=float(x.C[ts]); rv=pre[s]['rv']
    sd=rv*math.sqrt(T_at(ts)); K=S0*math.exp(-0.2*sd); p0=bs(S0,K,T_at(ts),rv,'put')*100; res=None
    for t2,r in x[x.index>ts].iterrows():
        T=T_at(t2+pd.Timedelta(minutes=1)); w=bs(r.H,K,T,rv,'put')*100; b=bs(r.L,K,T,rv,'put')*100
        if w<=0.8*p0: res=('stop',-20);break
        if b>=1.2*p0: res=('target',20);break
        if (t2-ts).total_seconds()>=7200 or t2.time()>=dt.time(15,45): res=('time',round((bs(r.C,K,T,rv,'put')*100/p0-1)*100,1));break
    print(f"   {s:5s} {et} S {S0:8.2f} prem ${p0:5.0f}{' (over budget)' if p0>1000 else ''} -> {res}  3d {pre[s]['ct3']:+.1f}%")
