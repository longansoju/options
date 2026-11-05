"""Replay every 11-04 day-trade signal (taken, voided, rejected) on 1m bars with the v2 exits
(+20% / -20% / 120-min max hold / 15:45), 0.2-sigma 2-week (11-20) vehicle. Priced two ways:
IV = RV30 (the backtest convention) and IV = 1.25 x RV30 with a 4% round-trip spread (closer to today's real quotes)."""
import sys, re, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er, option_quotes as oq
LOG = '/tmp/claude-0/-home-user-options/1900b617-71ad-55f2-b6c2-442b5e790faa/scratchpad/dt_engine.log'
D = dt.date(2026, 11, 4); EXP = dt.date(2026, 11, 20)
def inc(S): return 10.0 if S >= 1000 else 5.0 if S >= 500 else 2.5 if S >= 200 else 1.0 if S >= 50 else 0.5
def T_at(ts): return max((max(16*60-(ts.hour*60+ts.minute),0)/390 + int(np.busday_count(ts.date(), EXP)))/252, 1e-6)
sig = []; clock = None
for line in open(LOG):
    m = re.match(r'\[(\d\d):(\d\d)ET', line)
    if m: clock = dt.time(int(m.group(1)), int(m.group(2)))
    m = re.search(r'DT (?:signal|ENTRY) (\w+) (call|put|CALL|PUT)', line)
    if m and clock and clock >= dt.time(10, 0):
        s, k = m.group(1), m.group(2).lower()
        why = 'TAKEN' if 'DT ENTRY' in line else (line.split('REJECTED: ')[1].split(' | ')[0] if 'REJECTED' in line else 'MISSED')
        if s == 'TSM' and 'DT ENTRY' in line: why = 'VOIDED (stale 39m)'
        sig.append((clock, s, k, why))
bars = {}; rows = []
for clock, s, k, why in sig:
    if s not in bars:
        b = er.fetch_chart(s, '1m', '1d'); b = b[(b.index.time >= dt.time(9, 30)) & (b.index.time < dt.time(16, 0))].dropna()
        d = er.daily_frame(s, '6mo').dropna(); d = d[pd.to_datetime(d.index).date < D]
        bars[s] = (b, float(np.log(d.C / d.C.shift(1)).tail(30).std() * math.sqrt(252)))
    b, rv = bars[s]
    i = int(np.searchsorted(b.index.time, clock)); i = min(i, len(b) - 1)
    ts0 = b.index[i]; S = float(b.C.iloc[i]); sg = 1 if k == 'call' else -1
    K = round(S * math.exp(sg * 0.2 * rv * math.sqrt(T_at(ts0))) / inc(S)) * inc(S)
    out = {}
    for lab, ivm, spr in (('rv', 1.0, 0.0), ('real', 1.25, 0.04)):
        v = rv * ivm; e = oq.bs(S, K, T_at(ts0), v, k) * 100; res = None
        for ts, r in b.iloc[i + 1:].iterrows():
            T = T_at(ts + pd.Timedelta(minutes=1))
            w = oq.bs(r.L if k == 'call' else r.H, K, T, v, k) * 100; bb = oq.bs(r.H if k == 'call' else r.L, K, T, v, k) * 100
            if w <= e * 0.8: res = (-0.20, ts); break
            if bb >= e * 1.2: res = (0.20, ts); break
            if (ts - ts0).total_seconds() >= 7200 or ts.time() >= dt.time(15, 45):
                res = (oq.bs(r.C, K, T, v, k) * 100 / e - 1, ts); break
        out[lab] = (res[0] - spr) if res else None; out['prem'] = out.get('prem', e)
        out['t_' + lab] = res[1].strftime('%H:%M') if res else '-'
    rows.append(dict(time=clock.strftime('%H:%M'), sym=s, side=k, why=why[:48], S=round(S, 2), prem=round(out['prem']), pnl_rv=out['rv'], exit_rv=out['t_rv'], pnl_real=out['real'], exit_real=out['t_real']))
R = pd.DataFrame(rows)
pd.set_option('display.width', 250)
print(R.to_string(index=False, formatters={'pnl_rv': '{:+.0%}'.format, 'pnl_real': '{:+.0%}'.format}))
def grp(m): x = R[m]; return f"n={len(x):2d}  win {(x.pnl_real > 0).mean():.0%}  avg @RV {x.pnl_rv.mean():+.1%}  avg @1.25xRV-4% {x.pnl_real.mean():+.1%}"
print('\nALL signals        ', grp(R.sym.notna()))
print('taken (3)          ', grp(R.why == 'TAKEN'))
print('counter-trend only ', grp(R.why.str.startswith('counter-trend')))
print('slots full         ', grp(R.why.str.startswith('no 0-0.4')))
print('calls              ', grp(R.side == 'call'))
print('puts               ', grp(R.side == 'put'))
R.to_csv('/tmp/claude-0/-home-user-options/1900b617-71ad-55f2-b6c2-442b5e790faa/scratchpad/review/review_1104.csv', index=False)
