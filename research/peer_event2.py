"""Follow-up to peer_event.py (user 10-28: "is the peer-report strangle good? any solid MU rule?").
A) Strangle robustness: break-even IV multiple, MU-only, event-level clustering (one average per
   event so 4 correlated names are not counted as 4 trades), IS/OOS.
B) Direction: the Korean peer closes (02:30 ET) BEFORE the US open, so its reaction to its own
   report is known pre-market. Does it predict MU's gap, and MU's move AFTER the open (open->close)?"""
import sys, math
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def bs(S,K,T,v,k):
    T=max(T,1e-7); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T)
    return S*N(d1)-K*N(d2) if k=='call' else K*N(-d2)-S*N(-d1)
ev={}; kr={}
for tk,lo,hi in (('000660.KS',19,31),('005930.KS',3,10)):
    k=er.daily_frame(tk,'10y').dropna(); k.index=pd.to_datetime(k.index); kret=k.C.pct_change()
    kq=k[k.index.month.isin([1,4,7,10])]
    for (y,m),g in kq.groupby([kq.index.year,kq.index.month]):
        w=g[(g.index.day>=lo)&(g.index.day<=hi)]
        if len(w): dd=w.V.idxmax(); ev[dd.date()]=tk; kr[dd.date()]=float(kret.loc[dd])
IVS=[1.0,1.05,1.1,1.15,1.2,1.25,1.3]; rows=[]
for s in ['MU','WDC','STX','SNDK']:
    try: d=er.daily_frame(s,'10y').dropna()
    except Exception as e: print('skip',s,e); continue
    d.index=pd.to_datetime(d.index); c=d.C; cc=np.log(c/c.shift(1)); gp=np.log(d.O/c.shift(1))
    f=float(np.clip((gp**2).tail(500).mean()/(cc**2).tail(500).mean(),0.05,0.9)); rv=cc.rolling(30).std()*math.sqrt(252)
    for i in range(60,len(d)-1):
        nx=d.index[i+1].date()
        if nx not in ev: continue
        S=c.iloc[i]; v=rv.iloc[i]; O=d.O.iloc[i+1]; C1=c.iloc[i+1]
        if not v>0: continue
        sd=v*math.sqrt(1/252); r=dict(sym=s,ev=nx,peer=ev[nx],kret=kr[nx],gap=O/S-1,oc=C1/O-1)
        for m in IVS:
            tot=0
            for k,g_ in (('call',1),('put',-1)):
                K=S*math.exp(g_*sd); p0=bs(S,K,1/252,v*m,k); p1=bs(O,K,(1-f)/252,v,k); tot+=p1/p0-1-0.10
            r[m]=tot/2
        rows.append(r)
R=pd.DataFrame(rows); evs=sorted(R.ev.unique()); cut=evs[len(evs)//2]
print(f"events {len(evs)} ({evs[0]}..{evs[-1]}), name-nights {len(R)}\n\nA) strangle avg by IV multiple (10% friction)")
for m in IVS:
    E=R.groupby('ev')[m].mean(); i,o=E[E.index<cut],E[E.index>=cut]; mu=R[R.sym=='MU'][m]
    print(f"  IV {m:.2f}x RV | name-nights {R[m].mean():+6.1%} | per-event {E.mean():+6.1%} t {E.mean()/E.std()*math.sqrt(len(E)):+.1f} "
          f"win {(E>0).mean():.0%} med {E.median():+6.1%} | IS {i.mean():+6.1%} OOS {o.mean():+6.1%} | MU only {mu.mean():+6.1%} (n={len(mu)})")
for p in ('000660.KS','005930.KS'):
    E=R[R.peer==p].groupby('ev')[1.0].mean(); print(f"  by peer {p}: n={len(E)} avg {E.mean():+.1%} at IV=RV, {R[R.peer==p].groupby('ev')[1.15].mean().mean():+.1%} at 1.15x")
M=R[R.sym=='MU']
print(f"\nB) direction, MU on peer days (n={len(M)})")
print(f"  corr(Korean peer day return, MU gap)       {M.kret.corr(M.gap):+.2f} | same sign {(np.sign(M.kret)==np.sign(M.gap)).mean():.0%}")
print(f"  corr(Korean peer day return, MU open->close) {M.kret.corr(M.oc):+.2f} | same sign {(np.sign(M.kret)==np.sign(M.oc)).mean():.0%}")
for lab,g in (('peer up > +3%',M[M.kret>.03]),('peer down < -3%',M[M.kret<-.03])):
    print(f"  {lab:16s} n={len(g):2d} MU gap {g.gap.mean():+.2%} | MU open->close {g.oc.mean():+.2%} (up {(g.oc>0).mean():.0%})")
print('\nMU last 8 peer days:\n', M.tail(8)[['ev','peer','kret','gap','oc',1.0,1.15]].round(3).to_string(index=False))
