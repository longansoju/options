"""User 10-28: MU 261028 960C went $2.43 (10-27 close) -> MU +4.4% pre-market on SK Hynix's
results. Rule candidate: PEER-CATALYST NIGHTS - a memory peer (SK Hynix, Samsung) reports in
the Korean morning = during the US night. Do MU/WDC/STX/SNDK gap bigger those nights, and does
a 1-DTE strangle/call/put bought at the close pay at the next open (corrected pricing)?
Peer report days are inferred from the Korean stock's own volume spike inside the usual
windows (SK Hynix: ~20th-31st Jan/Apr/Jul/Oct; Samsung prelim: 3rd-10th Jan/Apr/Jul/Oct)."""
import sys, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er
def N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def bs(S,K,T,v,k):
    T=max(T,1e-7); d1=(math.log(S/K)+v*v/2*T)/(v*math.sqrt(T)); d2=d1-v*math.sqrt(T)
    return S*N(d1)-K*N(d2) if k=='call' else K*N(-d2)-S*N(-d1)
ev={}
for tk,lo,hi in (('000660.KS',19,31),('005930.KS',3,10)):
    k=er.daily_frame(tk,'10y').dropna(); k.index=pd.to_datetime(k.index)
    kq=k[k.index.month.isin([1,4,7,10])]
    for (y,m),g in kq.groupby([kq.index.year,kq.index.month]):
        w=g[(g.index.day>=lo)&(g.index.day<=hi)]
        if len(w): ev[w.V.idxmax().date()]=tk
print('peer report days found:',len(ev),'last 4:',sorted(ev)[-4:])
rows=[]
for s in ['MU','WDC','STX','SNDK']:
    try: d=er.daily_frame(s,'10y').dropna()
    except Exception as e: print('skip',s,e); continue
    c=d.C; idx=list(d.index); cc=np.log(c/c.shift(1)); gp=np.log(d.O/c.shift(1))
    f=float(np.clip((gp**2).tail(500).mean()/(cc**2).tail(500).mean(),0.05,0.9)); rv=cc.rolling(30).std()*math.sqrt(252); gsd=gp.rolling(60).std()
    for i in range(60,len(idx)-1):
        nxt=idx[i+1]; event=nxt in ev            # Korean report morning = US date of the next session
        S=c.iloc[i]; v=rv.iloc[i]; O=d.O.iloc[i+1]
        if not v>0: continue
        sd=v*math.sqrt(1/252); r={'sym':s,'day':idx[i],'event':event,'gapz':(O/S-1)/ (gsd.iloc[i] or np.nan)}
        for k,gsign in (('call',1),('put',-1)):
            K=S*math.exp(gsign*1.0*sd)                 # ~1 daily sigma OTM (the 960C was ~1.3 sigma)
            for ivm in (1.0,1.3,1.6):
                p0=bs(S,K,1/252,v*ivm,k); p1=bs(O,K,(1-f)/252,v,k)   # IV premium lost by the open
                r[f'{k}_{ivm}']=p1/p0-1-0.10 if p0>0.005 else np.nan
        rows.append(r)
R=pd.DataFrame(rows); R['strad_1.0']=(R['call_1.0']+R['put_1.0'])/2
for ivm in (1.0,1.3,1.6): R[f'strangle_{ivm}']=(R[f'call_{ivm}']+R[f'put_{ivm}'])/2
cut=R.day.sort_values().iloc[len(R)//2]
for name,g in (('all nights',R),('PEER-REPORT nights',R[R.event])):
    print(f"\n=== {name}: n={len(g)} | mean |gap| {g.gapz.abs().mean():.2f} gap-sd | big gap (>1 sd) {(g.gapz.abs()>1).mean():.0%} | up {(g.gapz>0).mean():.0%}")
    for col in ('call','put','strangle'):
        for ivm in (1.0,1.3,1.6):
            x=g[f'{col}_{ivm}'].dropna(); i,o=x[g.day<cut],x[g.day>=cut]
            print(f"   {col:8s} IV={ivm}xRV  avg {x.mean():+6.1%}  med {x.median():+6.1%}  >=+200%: {(x>=2).mean():.0%} | IS {i.mean():+6.1%} OOS {o.mean():+6.1%}")
E=R[R.event&(R.sym=='MU')].tail(12)[['day','gapz','call_1.0','put_1.0','strangle_1.3']]
print('\nMU, last 12 peer nights:\n',E.round(2).to_string(index=False))
