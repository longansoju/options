"""User 11-23: "attempt to trade MU tonight and see how well you do". A one-day, user-requested MU paper test.
Rules fixed BEFORE the open (09:3x ET), so the result can be scored honestly:
  TRIGGER  the day-trade engine's own MU confirmation (opening-range break held 10 consecutive 1m closes, right side of
           VWAP, relvol >= 1.0x same-clock), read from its log line "DT signal MU <side> REJECTED: ...".
  GATES    the engine blocks MU both ways today. Waived here: ONLY the RSI gate (the 10-06 pen-test found it neutral).
           Kept: counter-trend (3d -16.6% -> no MU CALL today), whipsaw, earnings, the 10% spread cap, stale signal
           (enter within 10 minutes of confirmation), no real quote -> no trade.
  VEHICLE  the engine's vehicle: Friday two weeks out (12-11), strike nearest 0.2 sigma within 0-0.4 sigma, 1 contract,
           real Yahoo ask. NOT funded from the November $1,000 book (a 2-week MU contract costs thousands) -> booked as
           book=watch, strategy=daytrade, tagged "MU TEST".
  EXITS    the engine's: +20% / -20% on the bid-IV mark / 120-min max hold / 15:45 ET; booked at the real bid.
  python -u research/mu_test.py <engine log>
"""
import sys, time, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er
from analysis import option_quotes as oq

LOG = sys.argv[1]
TODAY = dt.date.today()
EXPIRY = TODAY + dt.timedelta(days=(4 - TODAY.weekday()) % 7 + 14)
TGT, STOP, MAXHOLD = 0.20, 0.20, 120
N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, k):
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)


def T_at(ts):
    return max((max(16 * 60 - (ts.hour * 60 + ts.minute), 0) / 390 + int(np.busday_count(ts.date(), EXPIRY))) / 252, 1e-6)


def say(m): print(f"[{pd.Timestamp.now(tz='America/New_York'):%H:%M}ET] {m}", flush=True)


d = er.daily_frame('MU', '3mo').dropna(); c = d.C.iloc[:-1] if pd.Timestamp(d.index[-1]).date() == TODAY else d.C
RV = float(c.pct_change().tail(30).std() * math.sqrt(252)); CT3 = (c.iloc[-1] / c.iloc[-4] - 1) * 100
say(f"MU test armed | RV30 {RV:.0%} | 3d {CT3:+.1f}% -> calls blocked (counter-trend kept), puts allowed (RSI waived) | expiry {EXPIRY}")
seen = len(open(LOG).read().splitlines())   # only signals from now on
pos = None
while True:
    now = pd.Timestamp.now(tz='America/New_York')
    if pos is None:
        if now.time() >= dt.time(15, 0): say('MU test: no confirmed MU put by 15:00 ET - no trade today'); break
        L = open(LOG).read().splitlines()
        for l in L[seen:]:
            if 'DT signal MU put REJECTED' in l or 'DT signal MU call REJECTED' in l or 'DT ENTRY MU' in l:
                say('engine: ' + l.strip())
                if 'MU put REJECTED' not in l: continue
                why = l.split('REJECTED: ')[1].split(' | ')[0]
                if [w for w in why.split('; ') if not w.startswith('RSI')]:
                    say(f'MU put not taken - blocked by a kept rule: {why}'); continue
                S, age = er.live_price('MU')
                if age > 10: say(f'MU put not taken - spot {age:.0f} min old'); continue
                T = T_at(now); sd = RV * math.sqrt(T); best = None
                for f in (0.0, 0.1, 0.2, 0.3, 0.4):
                    K = oq.snap('MU', EXPIRY, S * math.exp(-f * sd))
                    sg = abs(math.log(K / S)) / sd
                    if sg > 0.4: continue
                    occ = f"MU{EXPIRY:%y%m%d}P{int(round(K * 1000)):08d}"
                    q = oq.fill(occ, 'buy', S, oq.spot_at('MU') or S, rv=RV, T=T, spot_at_age=lambda m_: oq.spot_at('MU', m_))
                    if not q or q.get('spread', 1) > 0.10: continue
                    if best is None or abs(sg - 0.2) < abs(best[2] - 0.2): best = (occ, K, sg, q)
                if not best: say('MU put not taken - no listed 0-0.4 sigma strike with a real quote and spread <= 10%'); continue
                occ, K, sg, q = best
                pos = dict(occ=occ, K=K, prem=q['prem'], iv=q['iv_bid'] or q['iv_ask'], ts=now, S=S)
                say(f"*** MU TEST ENTRY {occ} PUT ${q['prem']:.0f} ({sg:.2f} sigma) | MU {S:.2f} | exits +20% ${q['prem'] * 1.2:.0f} / "
                    f"-20% ${q['prem'] * 0.8:.0f} / 120m / 15:45 | REAL ASK [{q['note']}]")
                break
        seen = len(L)
    else:
        try:
            x = er.fetch_chart('MU', '1m', '1d').dropna(); x = x[x.index > pos['ts']]
        except Exception: x = pd.DataFrame()
        for ts, r in x.iterrows():
            T = T_at(ts + pd.Timedelta(minutes=1))
            worst, bestv = bs(r.H, pos['K'], T, pos['iv'], 'put') * 100, bs(r.L, pos['K'], T, pos['iv'], 'put') * 100
            why = None
            if worst <= pos['prem'] * (1 - STOP): why = '-20% stop'
            elif bestv >= pos['prem'] * (1 + TGT): why = '+20% target'
            elif (ts - pos['ts']).total_seconds() >= MAXHOLD * 60: why = '120-min max hold'
            elif ts.time() >= dt.time(15, 45): why = '15:45 time stop'
            if why:
                S, _ = er.live_price('MU')
                q = oq.fill(pos['occ'], 'sell', S, oq.spot_at('MU') or S, rv=RV, T=T_at(now), spot_at_age=lambda m_: oq.spot_at('MU', m_))
                px = q['prem'] if q else bs(S, pos['K'], T_at(now), pos['iv'], 'put') * 100
                say(f"*** MU TEST EXIT {pos['occ']} {why} at the {ts:%H:%M} bar | MU {S:.2f} | ${px:.0f} vs entry ${pos['prem']:.0f} "
                    f"({px / pos['prem'] - 1:+.0%}) | {'REAL BID [' + q['note'] + ']' if q else 'NO QUOTE - model'}")
                sys.exit()
    time.sleep(30)
