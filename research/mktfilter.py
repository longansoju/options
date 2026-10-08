import math, datetime as dt
src=open('pentest_dt.py').read().split("VARIANTS = [('BASELINE', {})]")[0]
src=src.replace("if t2.time() >= P['tstop']:","if t2.time() >= P['tstop'] or (j - i) * 5 >= P.get('maxhold', 9999):")
exec(src)
from analysis import event_radar as er
smh=er.fetch_chart('SMH','5m','60d'); smh=smh[(smh.index.time>=dt.time(9,30))&(smh.index.time<dt.time(16,0))].dropna()
g=smh.groupby(smh.index.date)
smh['vw']=(smh.C*smh.V).groupby(smh.index.date).cumsum()/smh.V.groupby(smh.index.date).cumsum()
smh['up']=smh.C>smh.vw
MK=smh['up']
orig_sim=sim
def sim_mkt(P, mode):
    # rerun sim but drop trades whose entry bar disagrees with SMH-vs-VWAP
    out=[]
    for nd in ND:
        x=nd['x']; o=x[x.index.time<dt.time(10,0)]; hi,lo=o.H.max(),o.L.min()
        vw=((x.C*x.V).cumsum()/x.V.cumsum()).values; tm=x.index.time; C=x.C.values
        exp=nd['day']+dt.timedelta(days=(4-nd['day'].weekday())%7+14); cands=[]
        for kind in ('call','put'):
            if nd['chop']: continue
            if (kind=='call' and nd['ct3']<0) or (kind=='put' and nd['ct3']>0): continue
            if (kind=='call' and nd['rsi']>70) or (kind=='put' and nd['rsi']<32): continue
            be=(C>hi) if kind=='call' else (C<lo); r=0
            for i in range(len(C)):
                r=r+1 if be[i] else 0
                if tm[i]<dt.time(10,0) or tm[i]>=dt.time(15,0): continue
                if r>=2 and ((C[i]>vw[i]) if kind=='call' else (C[i]<vw[i])) and (np.isnan(nd['rel'][i]) or nd['rel'][i]>=1.0):
                    if mode=='mkt':
                        m=MK.get(x.index[i])
                        if m is None or (kind=='call' and not m) or (kind=='put' and m): continue
                    cands.append((i,kind)); break
        cands.sort()
        for i,kind in cands[:1]:
            ts=x.index[i]; S0=C[i]; rv=nd['rv']; T0=T_at(ts,exp); sd=rv*math.sqrt(T0)
            K=S0*math.exp((0.2 if kind=='call' else -0.2)*sd); p0=bs(S0,K,T0,rv,kind)
            if p0*100>1000: continue
            res=None
            for j in range(i+1,len(C)):
                t2=x.index[j]; T=T_at(t2+pd.Timedelta(minutes=5),exp); Hj,Lj=x.H.iloc[j],x.L.iloc[j]
                w=bs(Lj if kind=='call' else Hj,K,T,rv,kind)/p0-1; b=bs(Hj if kind=='call' else Lj,K,T,rv,kind)/p0-1
                if w<=-0.2: res=-0.2;break
                if b>=0.2: res=0.2;break
                if (j-i)*5>=120 or t2.time()>=dt.time(15,45): res=bs(C[j],K,T,rv,kind)/p0-1;break
            if res is not None: out.append(dict(oos=nd['oos'],pnl=res-0.04,kind=kind,late=x.index[i].time()>=dt.time(12,0)))
    return pd.DataFrame(out)
for mode in ('base','mkt'):
    t=sim_mkt(BASE,mode); i,o=t[~t.oos],t[t.oos]
    print(f"{mode:5s} n={len(t)} IS {i.pnl.mean():+.1%} (n={len(i)}) OOS {o.pnl.mean():+.1%} (n={len(o)}) win {(t.pnl>0).mean():.0%} | entries after 12:00: n={t.late.sum()} avg {t[t.late].pnl.mean():+.1%} vs before {t[~t.late].pnl.mean():+.1%}")
