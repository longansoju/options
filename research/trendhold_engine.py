"""Paper TREND-HOLD engine (user OK 2026-10-23: "try your proposed strategies").
Run once per session at ~15:50 ET, after strangle_engine.py:  python trendhold_engine.py
Entry (research/hold_entry.py, the only cut positive in both halves at 1.15x RV):
  CALL only, when today's close is above the prior 20-session high AND
  SMH is above its 50-day MA AND today's volume >= 1.5x the 20-day average
  (volume at 15:50 is scaled by 390/380 to a full day), plus the standard gates:
  not chop (whipsaw), 3-day move >= 0, RSI <= 70; one signal per name per 5 sessions;
  earnings must fall AFTER expiry (multi-day hold - the strict rule).
Vehicle: 0.2-sigma call, expiry 2 Fridays out (>= 3 days), 1 contract, <= $1,000, max 3 new/night.
Exit (the adopted swing/momentum trailing exit), checked each session on the day's high/low:
  -50% stop; once the premium has been +50%, exit when its value falls 30% from the peak;
  otherwise out at the close when <= 2 business days to expiry. Stop is checked before trail.
Backtest caveats: n=55, picked from ~40 cuts, a 2025-26 chip bull market - a forward test.
State (peak premium per position) is kept in research/trendhold_state.json so it survives resets."""
import sys, os, json, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats
STATE = '/home/user/options/research/trendhold_state.json'
SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
EARN = {k: dt.date.fromisoformat(v) for k, v in config.DAYTRADE_EARNINGS.items()}
BUDGET, MAXN, SIG = 1000.0, 3, 0.2


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, k):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)


def inc(S): return 10.0 if S >= 1000 else 5.0 if S >= 500 else 2.5 if S >= 200 else 1.0 if S >= 50 else 0.5


def T_at(now, exp, mins_left=None):
    m = max(16 * 60 - (now.hour * 60 + now.minute), 0) if mins_left is None else mins_left
    return (m / 390 + int(np.busday_count(now.date(), exp))) / 252


def run():
    now = pd.Timestamp.now(tz='America/New_York'); today = now.date()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    book = pd.read_csv('/home/user/options/data/recommendations.csv')
    openr = book[(book.strategy == 'trendhold') & (book.status == 'open') & (book.book == 'paper')]
    frames = {}
    for _, r in openr.iterrows():                                     # ---- exits
        s = r.symbol; d = frames.setdefault(s, er.daily_frame(s, '6mo'))
        if dt.date.fromisoformat(r.created_date) >= today: continue
        bar = d.iloc[-1]; exp = dt.date.fromisoformat(r.expiry); K = float(r.strike); p0 = float(r.entry_premium) / 100
        rv = float(r.thesis.split('RV30 ')[1].split('%')[0]) / 100
        T = T_at(now, exp); bd = int(np.busday_count(today, exp))
        worst = bs(float(bar.L), K, T, rv, 'call') / p0 - 1; best = bs(float(bar.H), K, T, rv, 'call') / p0 - 1
        close = bs(float(bar.C), K, T, rv, 'call') / p0 - 1
        key = f"{r.occ_code}|{r.created_date}"; peak = st.get(key, {}).get('peak')
        out = None
        if worst <= -0.5: out = (-0.5, '-50% stop')
        elif peak is not None and (1 + worst) <= (1 + peak) * 0.7: out = ((1 + peak) * 0.7 - 1, f'trail: 30% off the +{peak:.0%} peak')
        else:
            if best >= 0.5: peak = best if peak is None else max(peak, best)
            if bd <= 2: out = (close, '2-DTE time stop')
        if out:
            r_, why = out
            print(f"*** TH EXIT {r.occ_code} | {s} {float(bar.C):.2f} | ~${(1 + r_) * p0 * 100:.0f} vs entry ${r.entry_premium:.0f} ({r_:+.0%}) | {why}")
            st.pop(key, None)
        else:
            st[key] = {'peak': peak}
            print(f"   TH hold {r.occ_code} | {s} {float(bar.C):.2f} | ~${(1 + close) * p0 * 100:.0f} ({close:+.0%}) | peak {'none' if peak is None else f'+{peak:.0%}'} | {bd} bd to expiry")
    smh = er.daily_frame('SMH', '1y'); smh_up = float(smh.C.iloc[-1]) > float(smh.C.rolling(50).mean().iloc[-1])
    print(f"[{now:%H:%M}ET] trend-hold scan | SMH {float(smh.C.iloc[-1]):.2f} vs 50d MA {float(smh.C.rolling(50).mean().iloc[-1]):.2f} -> {'UP' if smh_up else 'DOWN (no entries)'}")
    held = set(openr.symbol)
    recent = {r.symbol for r in book[book.strategy == 'trendhold'].itertuples()
              if np.busday_count(dt.date.fromisoformat(r.created_date), today) < 5}
    n = 0
    for s in SYMS:                                                    # ---- entries
        try:
            d = frames[s] if s in frames else er.daily_frame(s, '6mo')
        except Exception as e:
            print(f"   skip {s}: {str(e)[:40]}"); continue
        d = d.dropna(); c = d.C; S = float(c.iloc[-1])
        hi20 = float(d.H.iloc[-21:-1].max())
        if S <= hi20: continue
        why = []
        vol = float(d.V.iloc[-1]) * (390 / max(390 - max(16 * 60 - (now.hour * 60 + now.minute), 0), 1))
        volx = vol / float(d.V.iloc[-21:-1].mean())
        rv = float(c.pct_change().tail(30).std() * math.sqrt(252)); ct3 = (S / float(c.iloc[-4]) - 1) * 100
        dl = c.diff(); g = dl.clip(lower=0).ewm(alpha=1 / 14).mean(); l = (-dl.clip(upper=0)).ewm(alpha=1 / 14).mean()
        rsi = float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1])); w = whipsaw_stats(c.iloc[:-1])
        exp = today + dt.timedelta(days=(4 - today.weekday()) % 7 + 14)
        if (exp - today).days < 3: exp += dt.timedelta(days=7)
        if not smh_up: why.append('SMH below 50d MA')
        if volx < 1.5: why.append(f'volume {volx:.2f}x < 1.5x')
        if w['chop']: why.append(f"whipsaw {w['up5']}/{w['dn5']}")
        if ct3 < 0: why.append(f'counter-trend 3d {ct3:+.1f}%')
        if rsi > 70: why.append(f'RSI {rsi:.0f}')
        if s not in EARN: why.append('no verified earnings date')
        elif today <= EARN[s] <= exp: why.append(f'earnings {EARN[s]} before expiry {exp}')
        if s in held or s in recent: why.append('already signalled in the last 5 sessions')
        T = T_at(now, exp); K = math.ceil(S * math.exp(SIG * rv * math.sqrt(T)) / inc(S)) * inc(S); p = bs(S, K, T, rv, 'call') * 100
        if p > BUDGET: why.append(f'call ${p:.0f} > ${BUDGET:.0f}')
        tag = f"{s} {S:.2f} > 20d high {hi20:.2f} | vol {volx:.2f}x | 3d {ct3:+.1f}% | RSI {rsi:.0f} | RV30 {rv:.0%}"
        if why: print(f"   TH signal {tag} REJECTED: {'; '.join(why)}"); continue
        if n >= MAXN: print(f"   TH signal {tag} SKIPPED: max {MAXN} new per night"); continue
        occ = f"{s}{exp.strftime('%y%m%d')}C{int(round(K * 1000)):08d}"
        print(f"*** TH ENTRY {s} CALL {occ} ~${p:.0f} ({SIG} sigma) | {tag} | exits -50% stop / trail 30% after +50% / 2 DTE ({exp})")
        n += 1
    json.dump(st, open(STATE, 'w'), indent=1)
    if n == 0: print('   no trend-hold entry tonight')


if __name__ == '__main__':
    run()
