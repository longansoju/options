"""Focus-list sweep — every 5 min from 09:35 ET, all 21 names. Emits only events.

Events (each emitted once per name unless it escalates):
  CONFIRMED  broke 20d high/low, held >=10 consecutive 1m closes beyond it,
             on the right side of VWAP, relvol >= 1.0x (same-window vs 20
             sessions), AND the gates pass (whipsaw, counter-trend, RSI,
             earnings inside the Oct 2 weekly). Gate failures are printed.
  BREAK      level taken out but not yet held / volume not confirmed.
  OUTLIER    moving >= 2.5 pts away from SMH (DELL rule: investigate, don't score).
  HEARTBEAT  every 30 min: top movers + breadth, so silence is never ambiguous.
State persists to disk across 30-min monitor re-arms.
"""
import sys, os, json, time, math, datetime as dt
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
import config
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats, counter_trend, rsi
config.YF_INTER_CALL_DELAY = 0.3

SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
EXPIRY = dt.date(2026, 10, 2)
# next report dates: verified 09-27 where noted, else reporting cadence (all well after Oct 2)
EARN = {'MU': dt.date(2026, 9, 30)}
# extra user-requested levels: (symbol, side, level, label) — info events, gates still apply
CUSTOM = []
TODAY = pd.Timestamp.now(tz='America/New_York').date()   # sessions strictly before this are 'prior'
ST = 'sweep_state.json'
PRE = 'sweep_pre.pkl'


def precompute():
    rows = {}
    for s in SYMS:
        d = er.daily_frame(s, '1y')
        d = d[d.index < TODAY]
        c = d.C
        w = whipsaw_stats(c)
        h5 = er.fetch_chart(s, '5m', '1mo')
        h5 = h5[(h5.index.time >= dt.time(9, 30)) & (h5.index.time < dt.time(16, 0))]
        curve = {day: g.V.cumsum() for day, g in h5.groupby(h5.index.date) if day < TODAY}
        rows[s] = dict(prior=float(c.iloc[-1]), hi20=float(d.H.tail(20).max()), lo20=float(d.L.tail(20).min()),
                       chop=bool(w['chop']), up5=w['up5'], dn5=w['down5'], ct3=counter_trend(c, 'call')['ret'],
                       rsi=float(rsi(c).iloc[-1]), rv=float(c.pct_change().tail(30).std() * math.sqrt(252)),
                       curve={str(k): v for k, v in sorted(curve.items())[-20:]})
    pd.to_pickle(rows, PRE)
    return rows


def relvol(pre, today):
    t = today.index[-1].time()
    ref = [float(cs[cs.index.time <= t].iloc[-1]) for cs in pre['curve'].values() if (cs.index.time <= t).any()]
    return float(today.V.sum()) / max(np.median(ref), 1) if ref else float('nan')


def gates(p, side):
    blocks = []
    if p['chop']:
        blocks.append(f"whipsaw {p['up5']}up/{p['dn5']}dn")
    if side == 'call' and p['ct3'] < 0:
        blocks.append(f"counter-trend 3d {p['ct3']:+.1f}%")
    if side == 'put' and p['ct3'] > 0:
        blocks.append(f"counter-trend 3d {p['ct3']:+.1f}%")
    if side == 'call' and p['rsi'] > 70:
        blocks.append(f"RSI {p['rsi']:.0f}")
    if side == 'put' and p['rsi'] < 32:
        blocks.append(f"RSI {p['rsi']:.0f}")
    return blocks


def main():
    pre = pd.read_pickle(PRE) if os.path.exists(PRE) else precompute()
    st = json.load(open(ST)) if os.path.exists(ST) else {'seen': {}, 'hb': None}
    while True:
        now_et = pd.Timestamp.now(tz='America/New_York')
        if now_et.time() < dt.time(9, 35):
            time.sleep(30); continue
        if now_et.time() > dt.time(16, 1):
            print(f"{now_et.strftime('%H:%M')}ET close — sweep ending", flush=True); return
        try:
            poll(pre, st, now_et, fetch_live)
        except Exception as e:
            print(f"sweep error: {type(e).__name__}: {str(e)[:80]}", flush=True)
        time.sleep(300)


def fetch_live(s):
    x = er.fetch_chart(s, '1m', '1d')
    return x[(x.index.time >= dt.time(9, 30)) & (x.index.time < dt.time(16, 0))]


def poll(pre, st, now_et, fetch):
    if True:
        if True:
            live = {}
            for s in SYMS + ['SMH']:
                x = fetch(s)
                if len(x):
                    live[s] = x
            smh = live['SMH']
            smh_prior = st.get('smh_prior')
            if smh_prior is None:
                sd_ = er.daily_frame('SMH', '1mo'); smh_prior = float(sd_[sd_.index < TODAY].C.iloc[-1])
                st['smh_prior'] = smh_prior
            smh_pct = (float(smh.C.iloc[-1]) / smh_prior - 1) * 100
            out, movers = [], []
            for s in SYMS:
                if s not in live:
                    continue
                x, p = live[s], pre[s]
                px = float(x.C.iloc[-1]); pct = (px / p['prior'] - 1) * 100
                vwap = float((x.C * x.V).sum() / max(x.V.sum(), 1))
                rv_ = relvol(p, x)
                rel = pct - smh_pct
                movers.append((s, pct, rel, rv_))
                for side, lvl, beyond in [('call', p['hi20'], x.C > p['hi20']), ('put', p['lo20'], x.C < p['lo20'])]:
                    if not beyond.iloc[-1]:
                        continue
                    run = int((beyond[::-1].cumprod()).sum())          # consecutive minutes beyond, ending now
                    vw_ok = px > vwap if side == 'call' else px < vwap
                    key = f"{s}:{side}"
                    if run >= 10 and vw_ok and rv_ >= 1.0:
                        g = gates(p, side)
                        earn = EARN.get(s)
                        if earn and earn <= EXPIRY:
                            g.append(f"earnings {earn} inside Oct 2 weekly")
                        tag = 'CONFIRMED — gates PASS' if not g else 'CONFIRMED break, gates BLOCK: ' + '; '.join(g)
                        if st['seen'].get(key) != 'confirmed':
                            out.append(f"*** {s} {side.upper()} {tag} | ${px:.2f} {pct:+.2f}% (SMH {smh_pct:+.2f}%) "
                                       f"level {lvl:.2f} held {run}m relvol {rv_:.2f}x RSI {p['rsi']:.0f}")
                            st['seen'][key] = 'confirmed'
                    elif st['seen'].get(key) is None:
                        out.append(f"BREAK {s} {side} {'>' if side=='call' else '<'} {lvl:.2f} — NOT confirmed "
                                   f"(held {run}m, VWAP {'ok' if vw_ok else 'wrong side'}, relvol {rv_:.2f}x) | ${px:.2f} {pct:+.2f}%")
                        st['seen'][key] = 'break'
                for cs, cside, clvl, clab in CUSTOM:
                    if cs != s:
                        continue
                    cb = (x.C < clvl) if cside == 'put' else (x.C > clvl)
                    ckey = f"{s}:custom:{clvl}"
                    if cb.iloc[-1] and st['seen'].get(ckey) is None:
                        crun = int((cb[::-1].cumprod()).sum())
                        if crun >= 5:
                            g = gates(p, cside)
                            if EARN.get(s) and EARN[s] <= EXPIRY:
                                g.append(f"earnings {EARN[s]} inside Oct 2 weekly")
                            out.append(f"LEVEL {s} {'<' if cside=='put' else '>'} {clvl:.2f} ({clab}) held {crun}m relvol {rv_:.2f}x | "
                                       f"${px:.2f} {pct:+.2f}% | gates: {'PASS' if not g else '; '.join(g)}")
                            st['seen'][ckey] = 'hit'
                okey = f"{s}:outlier"
                if abs(rel) >= 2.5 and abs(rel) >= st['seen'].get(okey, 0) + 1.0:
                    out.append(f"OUTLIER {s} {pct:+.2f}% vs SMH {smh_pct:+.2f}% ({rel:+.1f} pts) relvol {rv_:.2f}x — investigate before scoring")
                    st['seen'][okey] = abs(rel)
            last = pd.Timestamp(st['hb']) if st.get('hb') else None
            if out or last is None or (now_et - last).total_seconds() >= 1800:
                sgt = (now_et + pd.Timedelta(hours=12)).strftime('%H:%M')
                movers.sort(key=lambda m: m[1])
                up = sum(1 for m in movers if m[1] > 0)
                head = (f"[{now_et.strftime('%H:%M')}ET/{sgt}SGT] SMH {smh_pct:+.2f}% | breadth {up}/{len(movers)} up | "
                        f"worst {movers[0][0]} {movers[0][1]:+.1f}% {movers[1][0]} {movers[1][1]:+.1f}% | "
                        f"best {movers[-1][0]} {movers[-1][1]:+.1f}% {movers[-2][0]} {movers[-2][1]:+.1f}%")
                print(head + ('' if out else '  (heartbeat — no events)'), flush=True)
                for o in out:
                    print('   ' + o, flush=True)
                st['hb'] = now_et.isoformat()
            json.dump(st, open(ST, 'w'))



if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'precompute':
        r = precompute()
        for s, p in r.items():
            print(f"{s:5s} prior {p['prior']:9.2f} hi20 {p['hi20']:9.2f} lo20 {p['lo20']:9.2f} "
                  f"{'CHOP' if p['chop'] else 'ok  '} {p['up5']}/{p['dn5']} 3d {p['ct3']:+6.2f}% RSI {p['rsi']:5.1f}")
    else:
        main()
