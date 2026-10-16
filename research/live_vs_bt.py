"""30-trade checkpoint: does the v2 backtest, run on the SAME sessions the live engine
traded (10-05..10-14), also show the live win rate? If yes -> regime, not engine luck/pricing."""
import sys, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
exec(open('bounce_ml.py').read().split("rows = []")[0].replace("if len(sys.argv) < 2:", "if False:"))
from analysis.harvest import whipsaw_stats
def opt(S,K,T,v,kind):
    T=max(T,1e-6); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T)
    return S*N(d1)-K*N(d2) if kind=='call' else K*N(-d2)-S*N(-d1)
out=[]
for s in SYMS:
    b,d=data[s]; b=b.copy(); b['tod']=b.index.time
    cum=b.groupby(b.index.date).V.cumsum()
    piv=pd.DataFrame({'d':b.index.date,'t':b.tod,'c':cum.values}).pivot_table(index='d',columns='t',values='c'); med=piv.rolling(20).median().shift(1)
    for day in [x for x in DAYS if dt.date(2026,9,1)<=x<=dt.date(2026,10,14)]:
        x=b[b.index.date==day]; h=d[d.index<day]
        if len(x)<70 or day not in med.index: continue
        c=h.C; rv=float(c.pct_change().tail(30).std()*math.sqrt(252)); ct3=c.iloc[-1]/c.iloc[-4]-1
        if whipsaw_stats(c)['chop']: continue
        dl=c.diff(); g=dl.clip(lower=0).ewm(alpha=1/14).mean(); l=(-dl.clip(upper=0)).ewm(alpha=1/14).mean(); rsi=float(100-100/(1+g.iloc[-1]/l.iloc[-1]))
        rel=x.V.cumsum().values/med.loc[day].reindex(x.tod).values; vw=((x.C*x.V).cumsum()/x.V.cumsum()).values
        o=x[x.index.time<dt.time(10,0)]; hi,lo=o.H.max(),o.L.min(); C=x.C.values; tm=x.index.time
        exp=day+dt.timedelta(days=(4-day.weekday())%7+14); cands=[]
        for kind in ('call','put'):
            if (kind=='call' and (ct3<0 or rsi>70)) or (kind=='put' and (ct3>0 or rsi<32)): continue
            be=(C>hi) if kind=='call' else (C<lo); run=0
            for i in range(len(C)):
                run=run+1 if be[i] else 0
                if tm[i]<dt.time(10,0) or tm[i]>=dt.time(15,0): continue
                if run>=2 and ((C[i]>vw[i]) if kind=='call' else (C[i]<vw[i])) and (np.isnan(rel[i]) or rel[i]>=1.0): cands.append((i,kind)); break
        for i,kind in cands:
            ts=x.index[i]; S0=C[i]; T0=T_at(ts,exp); g_=1 if kind=='call' else -1
            K=S0*math.exp(g_*0.2*rv*math.sqrt(T0)); p0=opt(S0,K,T0,rv,kind)
            if p0*100>1000: continue
            res=None
            for j in range(i+1,len(C)):
                t2=x.index[j]; T=T_at(t2+pd.Timedelta(minutes=5),exp)
                wpx,bpx=(x.L.iloc[j],x.H.iloc[j]) if kind=='call' else (x.H.iloc[j],x.L.iloc[j])
                if opt(wpx,K,T,rv,kind)/p0-1<=-0.2: res=-0.2; break
                if opt(bpx,K,T,rv,kind)/p0-1>=0.2: res=0.2; break
                if (t2-ts).total_seconds()>=7200 or t2.time()>=dt.time(15,45): res=opt(C[j],K,T,rv,kind)/p0-1; break
            if res is not None: out.append(dict(day=day,sym=s,kind=kind,pnl=res))
t=pd.DataFrame(out); t['live_window']=t.day>=dt.date(2026,10,5)
for k,g in t.groupby('live_window'):
    print(('LIVE WINDOW 10-05..10-14' if k else 'prior month 09-01..10-02'), f"n={len(g)} win {(g.pnl>0).mean():.0%} avg {g.pnl.mean():+.1%} | puts {g[g.kind=='put'].pnl.mean():+.1%} n={int((g.kind=='put').sum())} calls {g[g.kind=='call'].pnl.mean():+.1%}")
L=pd.read_csv('/home/user/options/data/recommendations.csv'); L=L[(L.strategy=='daytrade')&(L.book=='paper')&(L.status=='closed')]
L['d']=pd.to_datetime(L.created_date).dt.date; L=L[L.d<=dt.date(2026,10,14)]
print(f"LIVE 10-05..10-14 n={len(L)} win {(L.pnl_pct>0).mean():.0%} avg {L.pnl_pct.mean()/100:+.1%} | puts {L[L.direction=='put'].pnl_pct.mean()/100:+.1%} calls {L[L.direction=='call'].pnl_pct.mean()/100:+.1%}")
