"""Review the signals the engine PASSED on (10-15, 10-16): what would each have done if
taken on the v2 rules (0.2 sigma, 2 Fridays out, +20/-20, 120m, 15:45)? 1m bars, BS at RV30."""
import sys, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def opt(S,K,T,v,k):
    T=max(T,1e-6); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T)
    return S*N(d1)-K*N(d2) if k=='call' else K*N(-d2)-S*N(-d1)
def T_at(ts,exp): return (max(16*60-(ts.hour*60+ts.minute),0)/390+int(np.busday_count(ts.date(),exp)))/252
P=[('2026-10-15','10:15','GOOGL','call','counter-trend + earnings'),('2026-10-15','10:18','MU','call','counter-trend (+ budget)'),
   ('2026-10-15','10:46','AAPL','put','counter-trend'),('2026-10-15','10:48','AVGO','call','counter-trend'),('2026-10-15','10:48','NVDA','call','counter-trend'),
   ('2026-10-15','10:48','NVTS','call','whipsaw+ct+no date'),('2026-10-15','10:48','XOM','put','counter-trend + earnings'),
   ('2026-10-15','10:50','TSM','call','counter-trend + earnings day'),('2026-10-15','10:50','ASML','call','counter-trend'),('2026-10-15','10:50','CRDO','call','whipsaw+ct+no date'),
   ('2026-10-15','11:21','NBIS','call','whipsaw+ct+earnings'),('2026-10-15','11:23','MRVL','call','whipsaw+ct+no date'),
   ('2026-10-15','12:26','MSFT','call','counter-trend + earnings'),('2026-10-15','12:35','V','call','earnings'),('2026-10-15','12:53','PLTR','call','counter-trend'),
   ('2026-10-16','10:14','META','put','earnings'),('2026-10-16','10:28','NVDA','call','counter-trend'),('2026-10-16','11:03','NBIS','put','whipsaw + earnings'),
   ('2026-10-16','11:08','MSFT','put','earnings'),('2026-10-16','11:15','STX','put','whipsaw+RSI+earnings'),('2026-10-16','11:23','SMCI','put','whipsaw'),
   ('2026-10-16','11:23','NVTS','put','whipsaw+RSI+no date'),('2026-10-16','12:37','AMZN','put','earnings'),('2026-10-16','13:23','XOM','call','earnings'),
   ('2026-10-16','14:29','AAPL','put','counter-trend'),('2026-10-16','14:36','V','put','counter-trend + earnings'),('2026-10-16','14:40','MRVL','put','whipsaw + no date'),
   ('2026-10-16','14:55','MU','put','budget'),('2026-10-16','14:55','ASML','put','budget'),('2026-10-16','14:59','COHR','put','no date'),('2026-10-16','14:59','WDC','put','whipsaw+RSI+earnings')]
cache={}; rows=[]
for day,t,s,k,why in P:
    if s not in cache:
        b=er.fetch_chart(s,'1m','7d'); b=b[(b.index.time>=dt.time(9,30))&(b.index.time<dt.time(16,0))].dropna()
        cache[s]=(b, er.daily_frame(s,'6mo'))
    b,d=cache[s]; D=dt.date.fromisoformat(day); x=b[b.index.date==D]; h=d[d.index<D]
    rv=float(h.C.pct_change().tail(30).std()*math.sqrt(252)); exp=D+dt.timedelta(days=(4-D.weekday())%7+14)
    hh,mm=map(int,t.split(':')); i=int(np.searchsorted(x.index.time, dt.time(hh,mm)))
    if i>=len(x): continue
    ts=x.index[i]; S0=x.C.iloc[i]; g=1 if k=='call' else -1; K=S0*math.exp(g*0.2*rv*math.sqrt(T_at(ts,exp))); p0=opt(S0,K,T_at(ts,exp),rv,k)
    res,how=None,None
    for j in range(i+1,len(x)):
        t2=x.index[j]; T=T_at(t2,exp)
        w,bst=(x.L.iloc[j],x.H.iloc[j]) if k=='call' else (x.H.iloc[j],x.L.iloc[j])
        if opt(w,K,T,rv,k)/p0-1<=-0.2: res,how=-0.2,'stop'; break
        if opt(bst,K,T,rv,k)/p0-1>=0.2: res,how=0.2,'target'; break
        if (t2-ts).total_seconds()>=7200 or t2.time()>=dt.time(15,45): res,how=opt(x.C.iloc[j],K,T,rv,k)/p0-1,'time'; break
    rows.append(dict(day=day[5:],time=t,sym=s,side=k,why=why,prem=round(p0*100),pnl=res,exit=how,usd=round(res*p0*100) if res is not None else None))
R=pd.DataFrame(rows); pd.set_option('display.width',200)
print(R.to_string(index=False))
R['gate']=R.why.str.split(r' \+ |\+').str[0].str.strip()
inb=R[R.prem<=1000]
print('\nall passed (in budget):', len(inb), 'win', f"{(inb.pnl>0).mean():.0%}", 'avg', f"{inb.pnl.mean():+.1%}", '$', inb.usd.sum())
for lab,m in (('counter-trend ONLY',R.why=='counter-trend'),('earnings ONLY',R.why=='earnings'),('any whipsaw',R.why.str.contains('whipsaw')),('counter-trend involved',R.why.str.contains('counter-trend|ct'))):
    g=R[m & (R.prem<=1000)]
    if len(g): print(f"  {lab:24s} n={len(g)} win {(g.pnl>0).mean():.0%} avg {g.pnl.mean():+.1%} ${g.usd.sum()}")
R.to_csv('passed_review.csv',index=False)
