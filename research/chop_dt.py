import sys, math, datetime as dt
sys.path.insert(0,'.'); sys.path.insert(0,'/home/user/options')
import numpy as np, pandas as pd
import dt_backtest as B
data=pd.read_pickle('dt_data.pkl')
def run(fade, tgt, stop, nextweek=True, spread=0.04):
    out=[]
    for s,(b,d) in data.items():
        days=sorted(set(b.index.date))
        for day in days[20:]:
            x=b[b.index.date==day]; h=d[d.index<day]
            if len(x)<30 or len(h)<60: continue
            r=h.C.pct_change().tail(30); up,dn=(r>0.05).sum(),(r<-0.05).sum(); chop=(up+dn>=4) and abs(up-dn)<=1
            rv=float(h.C.pct_change().tail(30).std()*math.sqrt(252))
            o=x[x.index.time<dt.time(10,0)]; hi,lo=o.H.max(),o.L.min()
            post=x[(x.index.time>=dt.time(10,0))&(x.index.time<dt.time(15,0))]
            cum=x.V.cumsum(); vw=(x.C*x.V).cumsum()/cum
            exp=day+dt.timedelta(days=(4-day.weekday())%7+(7 if nextweek else 0))
            ent=None
            for side,be in (('up',post.C>hi),('dn',post.C<lo)):
                run_=be.groupby((~be).cumsum()).cumsum()
                ok=(run_>=2)&(((post.C>vw[post.index]) if side=='up' else (post.C<vw[post.index])))
                if ok.any():
                    ts=post.index[ok.values][0]
                    if ent is None or ts<ent[0]: ent=(ts,side)
            if ent is None: continue
            ts,side=ent
            kind=('call' if side=='up' else 'put') if not fade else ('put' if side=='up' else 'call')
            S0=float(x.C[ts]); T0=B.T_at(ts,exp); sd=rv*math.sqrt(T0)
            K=S0*math.exp((0.4 if kind=='call' else -0.4)*sd); p0=B.bs(S0,K,T0,rv,kind)
            res=None
            for t2,rw in x[x.index>ts].iterrows():
                T=B.T_at(t2+pd.Timedelta(minutes=5),exp)
                worst=B.bs(rw.L if kind=='call' else rw.H,K,T,rv,kind)/p0-1; best=B.bs(rw.H if kind=='call' else rw.L,K,T,rv,kind)/p0-1
                if worst<=-stop: res=-stop;break
                if best>=tgt: res=tgt;break
                if t2.time()>=dt.time(15,45): res=B.bs(rw.C,K,T,rv,kind)/p0-1;break
            if res is not None: out.append(dict(sym=s,chop=chop,pnl=res))
    return pd.DataFrame(out)
for fade in (False,True):
    for tgt,stop in ((0.3,0.3),(0.5,0.5),(0.2,0.2)):
        t=run(fade,tgt,stop)
        for c,g in t.groupby('chop'):
            print(f"{'FADE ' if fade else 'FOLLOW'} +{tgt:.0%}/-{stop:.0%} chop={'Y' if c else 'N'} n={len(g):3d} win {(g.pnl>0).mean():.0%} avg {g.pnl.mean():+.1%} after 4% spread {(g.pnl-0.04).mean():+.1%} | worst name {g.groupby('sym').pnl.mean().min():+.0%} best name {g.groupby('sym').pnl.mean().max():+.0%}")
