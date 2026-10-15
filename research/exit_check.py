import sys; sys.path.insert(0,'.')
exec(open('exit_grid.py').read().split("RULES = [")[0])
import trend_bt
MEM={'MU','SNDK','WDC','STX'}
R=[('hold to expiry',None,None,None,0),('no target/no stop, out 2DTE',None,None,None,2),('no stop, trail +100/40%',None,None,(1.0,0.4),2),('+50/-50 (current)',0.5,0.5,None,2)]
for ivp in (1.0,1.15):
    orig=trend_bt.bs
    # entry priced at IV = RV*ivp (real IV usually above realized); marks keep the same ratio
    def bs2(S,K,T,v,kind,_o=orig): return _o(S,K,T,v*ivp,kind)
    globals()['bs']=bs2
    Ps=paths(4,0.2); fr=0.04
    print(f"\n### 4wk 0.2σ, IV = RV x {ivp}")
    for name,tg,st,tr,ts in R:
        t=pd.DataFrame([dict(day=p['day'],kind=p['kind'],mem=p['sym'] in MEM,sym=p['sym'],pnl=ex(p['P'],tg,st,tr,ts)[0]-fr) for p in Ps])
        t['yr']=pd.to_datetime(t.day).dt.to_period('Q')
        top=t.pnl.sort_values().iloc[:-10].mean()
        q=t.groupby('yr').pnl.mean()
        print(f" {name:28s} all {t.pnl.mean():+.1%} | calls {t[t.kind=='call'].pnl.mean():+.1%} puts {t[t.kind=='put'].pnl.mean():+.1%} | memory {t[t.mem].pnl.mean():+.1%} non-mem {t[~t.mem].pnl.mean():+.1%} | w/o top10 {top:+.1%} | +quarters {(q>0).sum()}/{len(q)}")
    if ivp==1.0:
        t=pd.DataFrame([dict(sym=p['sym'],kind=p['kind'],pnl=ex(p['P'],None,None,None,0)[0]-fr) for p in Ps])
        print(' top10 hold-to-expiry:', t.sort_values('pnl').tail(10)[['sym','kind','pnl']].round(1).values.tolist())
        print(' non-memory calls/puts:', round(t[(~t.sym.isin(MEM))&(t.kind=='call')].pnl.mean(),3), round(t[(~t.sym.isin(MEM))&(t.kind=='put')].pnl.mean(),3))
