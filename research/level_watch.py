"""Live level alerts for a name the USER is watching to trade by hand (11-19 review, MU 750P miss).

Why: the day-trade engine only speaks at CONFIRMATION (a level held 10 consecutive 1m closes). On 11-19 MU first closed
below the 731.25 opening-range low at 10:29 ET (731.05); the 10th close came at 10:38 (717.99), the engine printed at
10:39 and the user heard at ~10:40 - with MU already 1.8% through the level and only ~1.8% from the gap-fill target
($705). Nothing warned the user at the first cross, so they had no time to pull up the chain and check the spread.

This watcher prints one line per event, for a Monitor to relay:
  CROSS   first 1m close beyond a level (heads-up: open the chain, check the spread - NOT an entry)
  HOLD5   5 consecutive closes beyond it
  HOLD10  10 consecutive closes = the system's confirmation, with the room left to the target in % and in
          remaining-session sigma, so a confirmation with too little room left is flagged as LATE
  FAIL    a close back inside after a CROSS (the count resets; a later re-cross is a fresh signal)
  STALE   confirmation is > 10 minutes old (the stale-signal rule: do not chase)
It does not trade and does not change any rule. Levels are given by hand:
  python research/level_watch.py MU:753.5:up:770 MU:731.25:down:705 [--rv 0.90] [--until 15:45]
"""
import sys, time, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
import yfinance as yf

from zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')
argv = sys.argv[1:]; opt = {}; args = []
while argv:
    a = argv.pop(0)
    if a.startswith('--'): opt[a] = argv.pop(0)
    else: args.append(a)
RV = float(opt.get('--rv', 0.9)); UNTIL = dt.time(*map(int, opt.get('--until', '15:45').split(':')))
W = []
for a in args:
    s, lv, d, tg = a.split(':'); W.append(dict(sym=s.upper(), lv=float(lv), up=d == 'up', tg=float(tg), run=0, crossed=False, conf=None, said=set()))


def say(msg):
    print(f"[{dt.datetime.now(ET).strftime('%H:%M')} ET] {msg}", flush=True)


def left_sigma(S, tg, now):
    mins = max(16 * 60 - (now.hour * 60 + now.minute), 1)
    return abs(math.log(tg / S)) / (RV * math.sqrt(mins / 390 / 252))


while True:
    now_et = dt.datetime.now(ET)
    if now_et.time() >= UNTIL: say('level watch ending'); break
    for w in W:
        try:
            m = yf.Ticker(w['sym']).history(period='1d', interval='1m').between_time('09:30', '16:00')
        except Exception:
            continue
        if len(m) < 2: continue
        done = m.iloc[:-1]                       # completed bars only
        beyond = (done.Close > w['lv']) if w['up'] else (done.Close < w['lv'])
        run = 0
        for b in reversed(beyond.tolist()):
            if b: run += 1
            else: break
        S = float(m.Close.iloc[-1]); tag = f"{w['sym']} {'above' if w['up'] else 'below'} {w['lv']:g}"
        if run >= 1 and not w['crossed']:
            w['crossed'] = True; say(f"CROSS {tag}: first close {done.Close.iloc[-1]:.2f} - heads-up only, open the chain and check the spread")
        if run >= 5 and 'h5' not in w['said']:
            w['said'].add('h5'); say(f"HOLD5 {tag}: 5 closes, now {S:.2f}")
        if run >= 10 and w['conf'] is None:
            w['conf'] = done.index[len(done) - run + 9].to_pydatetime()   # the bar of the 10th close, not "now" (a mid-run start)
            room = (w['tg'] / S - 1) * (1 if w['up'] else -1)
            sg = left_sigma(S, w['tg'], now_et.time())
            flag = 'LATE - less than 0.5 sigma left to the target, skip' if sg < 0.5 else 'room ok'
            say(f"HOLD10 {tag} CONFIRMED at the {w['conf'].strftime('%H:%M')} close, now {S:.2f} | {room:+.1%} to target {w['tg']:g} = {sg:.2f} session-sigma | {flag}")
        if w['conf'] is not None and 'stale' not in w['said'] and (now_et - w['conf']).total_seconds() > 600:
            w['said'].add('stale'); say(f"STALE {tag}: confirmed > 10 min ago - do not chase")
        if run == 0 and w['crossed'] and w['conf'] is None:
            w['crossed'] = False; w['said'].discard('h5'); say(f"FAIL {tag}: close {done.Close.iloc[-1]:.2f} back inside - count reset")
    time.sleep(20)
