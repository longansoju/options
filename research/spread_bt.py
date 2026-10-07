import math, datetime as dt
src=open('pentest_dt.py').read().split("VARIANTS = [('BASELINE', {})]")[0]
exec(src)
def inc(S): return 10.0 if S>=1000 else 5.0 if S>=500 else 2.5 if S>=200 else 1.0 if S>=50 else 0.5
def run(vehicle, fric):
    P=dict(BASE); out=[]
    for nd in ND:
        x=nd['x']; o=x[x.index.time<dt.time(10,0)]; hi,lo=o.H.max(),o.L.min()
        vw=((x.C*x.V).cumsum()/x.V.cumsum()).values; tm=x.index.time; C=x.C.values
        exp=nd['day']+dt.timedelta(days=(4-nd['day'].weekday())%7+14)
        c=[]
        for kind in ('call','put'):
            if nd['chop']: continue
            if (kind=='call' and nd['ct3']<0) or (kind=='put' and nd['ct3']>0): continue
            if (kind=='call' and nd['rsi']>70) or (kind=='put' and nd['rsi']<32): continue
            be=(C>hi) if kind=='call' else (C<lo); r=0
            for i in range(len(C)):
                r=r+1 if be[i] else 0
                if tm[i]<dt.time(10,0) or tm[i]>=dt.time(15,0): continue
                if r>=2 and ((C[i]>vw[i]) if kind=='call' else (C[i]<vw[i])) and (np.isnan(nd['rel'][i]) or nd['rel'][i]>=1.0):
                    c.append((i,kind)); break
        c.sort()
        for i,kind in c[:1]:
            ts=x.index[i]; S0=C[i]; rv=nd['rv']; T0=T_at(ts,exp); sd=rv*math.sqrt(T0); g=1 if kind=='call' else -1; st=inc(S0)
            K1=round(S0*math.exp(g*0.2*sd)/st)*st
            single=bs(S0,K1,T0,rv,kind)*100
            if vehicle=='single':
                if single>1000: continue
                legs=[(K1,1)]
            else:
                if vehicle=='spread_expensive_only' and single<=1000: continue
                K2=None
                for w in range(1,60):
                    k=K1+g*w*st
                    if k<=0: break
                    deb=(bs(S0,K1,T0,rv,kind)-bs(S0,k,T0,rv,kind))*100
                    if deb>1000: break
                    K2=k
                if K2 is None: continue
                legs=[(K1,1),(K2,-1)]
            val=lambda S,T: sum(q*bs(S,k,T,rv,kind) for k,q in legs)*100
            p0=val(S0,T0); res=None
            for j in range(i+1,len(C)):
                t2=x.index[j]; T=T_at(t2+pd.Timedelta(minutes=5),exp)
                Hj,Lj=x.H.iloc[j],x.L.iloc[j]
                worst=val(Lj if kind=='call' else Hj,T)/p0-1; best=val(Hj if kind=='call' else Lj,T)/p0-1
                if worst<=-0.2: res=-0.2;break
                if best>=0.2: res=0.2;break
                if (j-i)*5>=120 or t2.time()>=dt.time(15,45): res=val(C[j],T)/p0-1;break
            if res is not None: out.append(dict(sym=nd['sym'],oos=nd['oos'],pnl=res-fric,p0=p0))
    return pd.DataFrame(out)
for veh,fric in (('single',0.04),('spread_all',0.06),('spread_all',0.08),('spread_expensive_only',0.06),('spread_expensive_only',0.08)):
    t=run(veh,fric)
    if not len(t): print(veh,'n=0'); continue
    i,o=t[~t.oos],t[t.oos]
    print(f"{veh:22s} friction {fric:.0%} | n={len(t):3d} names={t.sym.nunique():2d} avg debit ${t.p0.mean():.0f} | IS avg {i.pnl.mean():+.1%} (n={len(i)}) | OOS avg {o.pnl.mean():+.1%} (n={len(o)}) | win {(t.pnl>0).mean():.0%} | all {t.pnl.mean():+.1%} (pre-friction {t.pnl.mean()+fric:+.1%})")
    if veh=='spread_expensive_only' and fric==0.06: print('   expensive names traded:',sorted(t.sym.unique()))
