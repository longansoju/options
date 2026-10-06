"""Day-trade PAPER engine (practice mode, started 2026-10-05). Flat by the close.

Rule = the least-bad variant from the 60-session backtest (dt_backtest.py), which
is still NEGATIVE (-6.9% avg before friction). This is a forward test, not an edge.
  ENTRY  (10:00-15:00 ET) opening range = 09:30-10:00 high/low. Break held >=10
         consecutive 1m closes, right side of session VWAP, day relvol >= 1.0x
         (same clock time vs 20 sessions). Gates: whipsaw, counter-trend 3d, RSI,
         earnings before expiry. Vehicle: NEXT week's Friday (less theta per day),
         nearest strike in 0.3-0.6 sigma, 1 contract, model premium <= $1,000.
         Max 3 entries/day, one per name.
  EXIT   +30% / -30% on the 1m best/worst price (stop checked first), else 15:45.
Emits DT ENTRY / DT EXIT; Claude does every book write by protocol."""
import sys, os, json, time, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
config.YF_INTER_CALL_DELAY = 0.2

SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
TODAY = pd.Timestamp.now(tz='America/New_York').date()
EXPIRY = TODAY + dt.timedelta(days=(4 - TODAY.weekday()) % 7 + 14)      # Friday two weeks out (pen-test 10-06)
EARN = {k: dt.date.fromisoformat(v) for k, v in config.DAYTRADE_EARNINGS.items()}   # verified dates (config.py)
BUDGET, TGT, STOP, MAXHOLD = 1000.0, 0.20, 0.20, 120   # pen-test 10-06
MAXN = 10**6          # no daily cap (user decision 2026-10-07); still one trade per name per day
PRE = pd.read_pickle('sweep_pre.pkl')
ST = f'dt_state_{TODAY}.json'


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def T_at(ts):
    mins = max(16 * 60 - (ts.hour * 60 + ts.minute), 0)
    return max((mins / 390 + int(np.busday_count(ts.date(), EXPIRY))) / 252, 1e-6)


def bs(S, K, T, v, kind):
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return (S * N(d1) - K * N(d2)) if kind == 'call' else (K * N(-d2) - S * N(-d1))


def inc(S): return 10.0 if S >= 1000 else 5.0 if S >= 500 else 2.5 if S >= 200 else 1.0 if S >= 50 else 0.5


def pick(sym, S, kind, ts, rv):
    T = T_at(ts); sd = rv * math.sqrt(T); step = inc(S); sg = 1 if kind == 'call' else -1
    best = None
    for f in (0.0, 0.1, 0.2, 0.3, 0.4):
        K = round(S * math.exp(sg * f * sd) / step) * step
        sig = abs(math.log(K / S)) / sd
        if sig > 0.4: continue
        prem = bs(S, K, T, rv, kind) * 100
        if prem <= BUDGET:
            c = dict(K=K, prem=prem, sig=sig, occ=f"{sym}{EXPIRY.strftime('%y%m%d')}{'C' if kind == 'call' else 'P'}{int(round(K * 1000)):08d}")
            if best is None or abs(sig - 0.2) < abs(best['sig'] - 0.2): best = c
    return best


def gates(p, kind, sym):
    b = []
    if p['chop']: b.append(f"whipsaw {p['up5']}/{p['dn5']}")
    if kind == 'call' and p['ct3'] < 0: b.append(f"counter-trend 3d {p['ct3']:+.1f}%")
    if kind == 'put' and p['ct3'] > 0: b.append(f"counter-trend 3d {p['ct3']:+.1f}%")
    if kind == 'call' and p['rsi'] > 70: b.append(f"RSI {p['rsi']:.0f}")
    if kind == 'put' and p['rsi'] < 32: b.append(f"RSI {p['rsi']:.0f}")
    if EARN.get(sym) and TODAY <= EARN[sym] <= EXPIRY: b.append(f"earnings {EARN[sym]} before {EXPIRY}")
    if sym in config.DAYTRADE_EXPANSION and sym not in EARN: b.append('no verified earnings date')
    return b


def say(now, msg):
    print(f"[{now.strftime('%H:%M')}ET/{(now + pd.Timedelta(hours=12)).strftime('%H:%M')}SGT] {msg}", flush=True)


st = json.load(open(ST)) if os.path.exists(ST) else {'pos': {}, 'done': [], 'rej': [], 'hb': None}
while True:
    now = pd.Timestamp.now(tz='America/New_York')
    if now.time() > dt.time(16, 1) and not st['pos']:
        say(now, f"close — day-trade engine ending | entries today {len(st['done']) + len(st['pos'])}"); break
    try:
        live = {}
        for s in SYMS:
            x = er.fetch_chart(s, '1m', '1d')
            x = x[(x.index.time >= dt.time(9, 30)) & (x.index.time < dt.time(16, 0))].dropna()
            x = x[x.V > 0]
            if len(x): live[s] = x
        ev = []
        # ---- exits first
        for occ, p in list(st['pos'].items()):
            x = live.get(p['sym'])
            if x is None: continue
            since = x[x.index > pd.Timestamp(p['ts'])]
            kind, K, rv, e = p['kind'], p['K'], p['rv'], p['prem']
            reason = None; exitp = None
            for ts, r in since.iterrows():
                T = T_at(ts + pd.Timedelta(minutes=1))
                worst = bs(r.L if kind == 'call' else r.H, K, T, rv, kind) * 100
                best = bs(r.H if kind == 'call' else r.L, K, T, rv, kind) * 100
                if worst <= e * (1 - STOP): reason, exitp, ref = f'-{STOP:.0%} stop', e * (1 - STOP), ts; break
                if best >= e * (1 + TGT): reason, exitp, ref = f'+{TGT:.0%} target (resting limit)', e * (1 + TGT), ts; break
                if (ts - pd.Timestamp(p['ts'])).total_seconds() >= MAXHOLD * 60:
                    reason, exitp, ref = f'{MAXHOLD}-min max-hold time stop', bs(r.C, K, T, rv, kind) * 100, ts; break
                if ts.time() >= dt.time(15, 45):
                    reason, exitp, ref = '15:45 day-trade time stop', bs(r.C, K, T, rv, kind) * 100, ts; break
            if reason:
                px = float(since.loc[ref].C)
                ev.append(f"*** DT EXIT {occ} — {reason} at {ref.strftime('%H:%M')} | ~${exitp:.0f} vs entry ${e:.0f} ({(exitp/e-1)*100:+.0f}%) | {p['sym']} {px:.2f}")
                st['done'].append(occ); del st['pos'][occ]
        # ---- entries
        n_today = len(st['done']) + len(st['pos'])
        held = {p['sym'] for p in st['pos'].values()} | {o[:len(o) - 15] for o in st['done']}
        if dt.time(10, 0) <= now.time() < dt.time(15, 0) and n_today < MAXN:
            for s, x in live.items():
                if s in held or s not in PRE: continue
                p = PRE[s]; orb = x[x.index.time < dt.time(10, 0)]
                if len(orb) < 20: continue
                hi, lo = float(orb.H.max()), float(orb.L.min())
                post = x[x.index.time >= dt.time(10, 0)]
                px = float(x.C.iloc[-1]); vw = float((x.C * x.V).sum() / x.V.sum()); t = x.index[-1].time()
                ref = [float(cs[cs.index.time <= t].iloc[-1]) for cs in p['curve'].values() if (cs.index.time <= t).any()]
                rv_ = float(x.V.sum()) / max(np.median(ref), 1) if ref else 0
                for kind, beyond in (('call', post.C > hi), ('put', post.C < lo)):
                    if not len(beyond) or not beyond.iloc[-1]: continue
                    run = int(beyond[::-1].cumprod().sum())
                    if run < 10 or not (px > vw if kind == 'call' else px < vw) or rv_ < 1.0: continue
                    key = f'{s}:{kind}'
                    g = gates(p, kind, s)
                    c = pick(s, px, kind, x.index[-1], p['rv']) if not g else None
                    if not g and c is None: g.append('no 0-0.4 sigma strike within $1,000')
                    if g:
                        if key not in st['rej']:
                            ev.append(f"DT signal {s} {kind} REJECTED: {'; '.join(g)} | {px:.2f} OR {lo:.2f}-{hi:.2f} held {run}m relvol {rv_:.2f}x")
                            st['rej'].append(key)
                        continue
                    if len(st['done']) + len(st['pos']) >= MAXN: break
                    st['pos'][c['occ']] = dict(sym=s, kind=kind, K=c['K'], prem=c['prem'], rv=p['rv'], ts=x.index[-1].isoformat(), px=px)
                    ev.append(f"*** DT ENTRY {s} {kind.upper()} {c['occ']} ~${c['prem']:.0f} ({c['sig']:.2f} sigma, RV {p['rv']:.0%}) | {s} {px:.2f} "
                              f"broke OR {'high' if kind == 'call' else 'low'} {hi if kind == 'call' else lo:.2f}, held {run}m, VWAP {vw:.2f}, relvol {rv_:.2f}x | "
                              f"gates PASS (whipsaw {p['up5']}/{p['dn5']}, 3d {p['ct3']:+.1f}%, RSI {p['rsi']:.0f}) | "
                              f"exits +{TGT:.0%} ${c['prem']*(1+TGT):.0f} / -{STOP:.0%} ${c['prem']*(1-STOP):.0f} / max hold {MAXHOLD}m / 15:45")
                    break
        # ---- marks + heartbeat
        marks = []
        for occ, p in st['pos'].items():
            x = live.get(p['sym'])
            if x is None: continue
            cur = bs(float(x.C.iloc[-1]), p['K'], T_at(x.index[-1]), p['rv'], p['kind']) * 100
            marks.append(f"{occ} ~${cur:.0f} ({(cur/p['prem']-1)*100:+.0f}%)")
        hb = pd.Timestamp(st['hb']) if st.get('hb') else None
        if ev or hb is None or (now - hb).total_seconds() >= 1800:
            say(now, f"day-trade engine | open: {', '.join(marks) if marks else 'none'} | entries today {len(st['done']) + len(st['pos'])} (no cap)"
                     + ('' if ev else ' (heartbeat)'))
            for e_ in ev: print('   ' + e_, flush=True)
            st['hb'] = now.isoformat()
        json.dump(st, open(ST, 'w'))
    except Exception as e:
        say(now, f"engine error {type(e).__name__}: {str(e)[:80]}")
    time.sleep(60)
