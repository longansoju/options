import sys, math, datetime as dt
sys.path.insert(0,'/home/user/options')
import numpy as np, pandas as pd
data=pd.read_pickle('dt_data.pkl')
def t(x): x=np.asarray(x); return x.mean()/(x.std()/math.sqrt(len(x))) if len(x)>2 else float('nan')
# TEST 1: daily. After a big (>5%) day, does a CHOP name reverse more than a non-chop name?
R=[]
for s,(b,d) in data.items():
    r=d.C.pct_change()
    up=(r>0.05).rolling(30).sum().shift(1); dn=(r<-0.05).rolling(30).sum().shift(1)
    chop=((up+dn)>=4)&((up-dn).abs()<=1)
    for i in range(31,len(d)-3):
        if abs(r.iloc[i])>0.05:
            sg=np.sign(r.iloc[i])
            R.append(dict(chop=bool(chop.iloc[i]),fade1=-sg*(d.C.iloc[i+1]/d.C.iloc[i]-1)*100,fade3=-sg*(d.C.iloc[i+3]/d.C.iloc[i]-1)*100,
                          gapfade=-sg*(d.O.iloc[i+1]/d.C.iloc[i]-1)*100))
R=pd.DataFrame(R)
for c,g in R.groupby('chop'):
    print(f"DAILY big-move days, chop={c}: n={len(g)} | fade next day {g.fade1.mean():+.2f}% (t {t(g.fade1):+.2f}, hit {(g.fade1>0).mean():.0%}) | fade 3 days {g.fade3.mean():+.2f}% (t {t(g.fade3):+.2f}) | overnight gap fade {g.gapfade.mean():+.2f}%")
# TEST 2: intraday. Opening-range break -> 15:45, continuation return, split by chop
I=[]
for s,(b,d) in data.items():
    days=sorted(set(b.index.date))
    for day in days[20:]:
        x=b[b.index.date==day]; h=d[d.index<day]
        if len(x)<30 or len(h)<40: continue
        r=h.C.pct_change().tail(30); up,dn=(r>0.05).sum(),(r<-0.05).sum(); chop=(up+dn>=4) and abs(up-dn)<=1
        o=x[x.index.time<dt.time(10,0)]; hi,lo=o.H.max(),o.L.min(); post=x[(x.index.time>=dt.time(10,0))&(x.index.time<dt.time(15,0))]
        ex=x[x.index.time<=dt.time(15,45)].C.iloc[-1]
        for kind,be in (('call',post.C>hi),('put',post.C<lo)):
            run=be.groupby((~be).cumsum()).cumsum(); e=post.index[(run>=2).values]
            if len(e):
                p0=post.C[e[0]]; I.append(dict(chop=chop,cont=(ex/p0-1)*100*(1 if kind=='call' else -1))); break
I=pd.DataFrame(I)
for c,g in I.groupby('chop'):
    print(f"INTRADAY OR-break -> 15:45, chop={c}: n={len(g)} continuation {g.cont.mean():+.3f}% (t {t(g.cont):+.2f}, hit {(g.cont>0).mean():.0%}) -> fading it = {-g.cont.mean():+.3f}%")
