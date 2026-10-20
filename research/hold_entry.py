"""Which ENTRY works for a 1-4 week hold? 20d closing-break signals (all gates), exit FIXED =
the adopted trailing exit (-50 stop, trail 30% after +50, out at 2 DTE). Split signals by what
was known at the entry close; IS/OOS halves by date; 4% friction; IV = RV and IV = 1.15 RV."""
import sys, math, datetime as dt
sys.path.insert(0,'.'); sys.path.insert(0,'/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er
import trend_bt
exec(open('exit_grid.py').read().split("RULES = [")[0])
smh=er.daily_frame('SMH','2y'); smh_ma=smh.C.rolling(50).mean()
feat={}
for s,d in data.items():
    c=d.C; v=d.V; sd=c.pct_change().rolling(20).std()
    feat[s]=pd.DataFrame({'volx':v/v.rolling(20).mean(),'clv':((c-d.L)/(d.H-d.L)).where(d.H>d.L,0.5),
        'ma50':c/c.rolling(50).mean()-1,'r20':c/c.shift(20)-1,'brk':(c-c.shift(1))/c.shift(1)/sd})
for ivp in (1.0,1.15):
    orig=trend_bt.bs
    globals()['bs']=lambda S,K,T,v,kind,_o=orig: _o(S,K,T,v*ivp,kind)
    for wk in (2,4):
        Ps=paths(wk,0.2); rows=[]
        for p in Ps:
            f=feat[p['sym']].loc[p['day']]; sm=smh.C.get(p['day']); sma=smh_ma.get(p['day'])
            r,_=ex(p['P'],None,0.5,(0.5,0.3),2)
            rows.append(dict(day=p['day'],kind=p['kind'],pnl=r-0.04,volx=f.volx,clv=f.clv,ma50=f.ma50,r20=f.r20,
                smh_up=(sm>sma) if sm and sma else np.nan))
        t=pd.DataFrame(rows); cut=sorted(t.day)[len(t)//2]
        C=t.kind=='call'; P_=t.kind=='put'; up=t.smh_up==True
        al=(C&up)|(P_&~up)   # trade WITH the sector trend
        conds={'all':t.index==t.index,'calls':C,'puts':P_,'with sector trend (SMH vs 50d MA)':al,'against sector trend':~al,
               'volume >= 1.5x':t.volx>=1.5,'close in top/bottom 20% of range':(C&(t.clv>=.8))|(P_&(t.clv<=.2)),
               'calls, SMH up, vol>=1.5x':C&up&(t.volx>=1.5),'with trend + vol>=1.5x + strong close':al&(t.volx>=1.5)&((C&(t.clv>=.8))|(P_&(t.clv<=.2))),
               'with trend, first break (r20 < 15%)':al&(t.r20.abs()<.15)}
        print(f"\n=== {wk}-week expiry, 0.2σ, trailing exit, IV = {ivp} x RV ===")
        for k,m in conds.items():
            g=t[m]; i,o=g[g.day<cut],g[g.day>=cut]
            print(f"  {k:42s} n={len(g):4d} win {(g.pnl>0).mean():.0%} avg {g.pnl.mean():+6.1%} med {g.pnl.median():+6.1%} | IS {i.pnl.mean():+6.1%} (n={len(i)}) OOS {o.pnl.mean():+6.1%} (n={len(o)})")
