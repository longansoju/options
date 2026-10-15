"""Nightly 1-DTE far-OTM lottery tickets, bigger universe, last month vs every month (2y).
Buy at each close a 1.5-sigma-OTM option expiring next day, sell at the next OPEN.
Corrected pricing: overnight share of daily variance charged (per name, measured);
IV = RV30 * (1 + 0.15*k) for the far-OTM wing (sticky strike); 10% round-trip friction.
$100 per ticket. Includes today's (2026-10-15) open."""
import sys, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
config.YF_INTER_CALL_DELAY = 0.15
EXTRA = ['QCOM', 'NFLX', 'KLAC', 'MA', 'UBER', 'AXP', 'AMD', 'TSLA', 'ORCL', 'INTC', 'ARM', 'AMAT', 'LRCX',
         'GS', 'CAT', 'COIN', 'LLY', 'HIMS', 'CEG', 'VST', 'SNDK', 'NVO', 'MAR', 'HLT', 'RCL', 'BKNG', 'V', 'FCX', 'NUE', 'PLTR']
DIV = [t for ts in config.DIVERSIFICATION.values() for t in ts]
U = sorted(set(config.WATCHLIST + config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION + DIV + EXTRA) - {'SPY', 'QQQ'})
K_SIG, FR, TICKET = 1.5, 0.10, 100.0


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def opt(S, K, T, v, kind):
    T = max(T, 1e-7); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return (S * N(d1) - K * N(d2)) if kind == 'call' else (K * N(-d2) - S * N(-d1))


rows = []
for s in U:
    try:
        d = er.daily_frame(s, '2y').dropna()
    except Exception as e:
        print('skip', s, str(e)[:40]); continue
    if len(d) < 120: continue
    c = d.C; cc = np.log(c / c.shift(1)); gap = np.log(d.O / c.shift(1))
    f = float((gap ** 2).tail(250).mean() / (cc ** 2).tail(250).mean()); f = min(max(f, 0.05), 0.9)
    rv = cc.rolling(30).std() * math.sqrt(252)
    for i in range(40, len(d) - 1):
        S = c.iloc[i]; v = rv.iloc[i]
        if not v > 0: continue
        sd = v * math.sqrt(1 / 252); o = d.O.iloc[i + 1]
        for kind, g in (('put', -1), ('call', 1)):
            iv = v * (1 + 0.15 * K_SIG); K = S * math.exp(g * K_SIG * sd); p0 = opt(S, K, 1 / 252, iv, kind)
            if p0 < 0.01: continue
            r = opt(o, K, (1 - f) / 252, iv, kind) / p0 - 1
            rows.append(dict(sym=s, night=d.index[i], sell_day=d.index[i + 1], kind=kind, ret=r - FR))
R = pd.DataFrame(rows); R['month'] = pd.to_datetime(R.sell_day).dt.to_period('M')
R.to_pickle('lottery_month.pkl')
print('names', R.sym.nunique(), '| name-nights', len(R) // 2, '| last sell day', R.sell_day.max())

last = R[pd.to_datetime(R.sell_day) >= pd.Timestamp('2026-09-15')]
print('\nPAST MONTH (sell days 2026-09-15 .. 2026-10-15), $100 per ticket:')
for kind in ('put', 'call'):
    g = last[last.kind == kind]
    print(f"  {kind}s: {len(g)} tickets, spent ${len(g)*TICKET:,.0f}, P/L ${g.ret.sum()*TICKET:+,.0f} ({g.ret.mean():+.1%}/ticket) | "
          f">=5x: {(g.ret>=4).sum()} | doubled+: {(g.ret>=1).sum()}")
b = last; print(f"  both: P/L ${b.ret.sum()*TICKET:+,.0f} on ${len(b)*TICKET:,.0f}")
dd = last[last.kind == 'put'].groupby('sell_day').ret.sum() * TICKET
print('  puts, best mornings:', dd.sort_values().tail(3).round(0).to_dict())
print('  puts, P/L excluding the single best morning:', f"${dd.sum()-dd.max():+,.0f}")

print('\nEVERY MONTH, puts ($ P/L on $100/ticket, all names):')
m = R[R.kind == 'put'].groupby('month').ret.agg(['sum', 'mean', 'count'])
m['pl'] = m['sum'] * TICKET
print(m[['count', 'pl', 'mean']].round(3).to_string())
print(f"\nmonths with a profit (puts): {(m.pl>0).sum()} of {len(m)} | total 2y P/L ${m.pl.sum():+,.0f}")
mc = R[R.kind == 'call'].groupby('month').ret.sum() * TICKET
print(f"months with a profit (calls): {(mc>0).sum()} of {len(mc)} | total 2y P/L ${mc.sum():+,.0f}")
