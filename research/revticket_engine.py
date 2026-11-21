"""REVERSAL TICKET engine - the MU 261120 680P setup, as a fixed-rule paper strategy (user 11-21: "fix the rules based on
how you want me to do it properly and add it as a strategy"). Run once per session at ~15:50 ET, after the other close
engines:  python research/revticket_engine.py

Evidence (research/repeat_lottery.py, 27 names, 5y daily, 101 signal nights, 10% round-trip friction): a ~1 daily-sigma put
expiring the next session, bought at the close of a FAILED GAP-UP that closes at the day's low and sold at the next close:
  IV = 1.0x RV30: +71% per ticket   |   1.3x: -14%   |   1.6x: -45%   (median -100%, win 14-17%, 4-13% of tickets >= 5x)
The next day itself is a coin flip in direction (research/reversal_close.py: P(-5%) 19.6% vs P(+5%) 17.6%); the edge, if
any, exists ONLY when the real option is cheap relative to realized vol. Real 1-day readings logged so far: 1.35-2.1x.
So this is a forward test of one question: how often is the real ticket cheap enough, and does it pay when it is?

RULES (fixed in advance; revised 11-21 after research/revticket_coverage.py, user: "verify coverage", "make the cap looser"):
  SIGNAL A gap up >= 3% AND price below yesterday's close AND in the bottom 10% of today's range -> PUT (the MU 680P night).
  SIGNAL B volume > 1.5x the 20-day average (scaled to a full day) AND today's range > 2 sd above its 30-day mean AND price
           in the bottom / top 10% of today's range -> PUT / CALL in the direction of the close.
           5y test, 10% friction, nearest listed expiry, sold next close: A+B n=493 (~99/yr), IV=1.0x RV +83% (IS +130 /
           OOS +45), 1.1x +49% (+87 / +19), 1.2x +27% (+58 / +2), 1.3x +11% (+38 / -10); median -80%, win ~24%,
           longest losing run 20. A looser A (gap 2%, bottom 20%) and the call mirror of A both FAILED and are not used.
  COVERAGE >= 4x next-day tickets happen on ~8% of name-nights; the night before looks like any night (extreme close
           25% vs 24%), so A+B flag ~1% of them. No price/volume trigger catches most of these - catching more means
           buying nearly every night, which loses (-16% a night at IV = RV, the 1-day ticket test).
  VEHICLE  1+ contracts, ~1.0 daily-sigma OTM (listed strike), the NEAREST listed expiry after today within 7 days
           (the next session where listed; else the coming Friday). Sold at the NEXT session's ~15:50 run either way.
  PRICE    real Yahoo quote required. FUNDED only if IV at the ask <= 1.10x RV30 (OOS turns ~0 at 1.2x):
             IV <= 1.00x RV -> up to 5% of equity;  1.00-1.10x -> up to 2.5%   (about half the growth-optimal fraction)
           contracts = as many as fit, max 3 (so the 2-part exit is possible); max 2 funded names per night.
           Everything else is logged as book=watch with its real IV.
  BLOCKS   earnings today or the next session; no verified earnings date; spot older than er.STALE_SPOT_MIN.
Review at 30 signals: real IV/RV distribution, how many were fundable, and the funded P&L vs the test.
"""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, yfinance as yf, config
from analysis import event_radar as er
from analysis import bankroll
from analysis import option_quotes as oq

SYMS = config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION
EARN = {k: dt.date.fromisoformat(v) for k, v in config.DAYTRADE_EARNINGS.items()}
HOLIDAYS = ['2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15']   # NYSE full closures
GAP, POS, SIG, MAXN, MAXQ = 0.03, 0.10, 1.0, 2, 3
TIERS = ((1.00, 0.05), (1.10, 0.025))            # IV/RV30 at the ask <= x -> cap as a fraction of equity


def qty_of(r):
    try: return int(str(r.thesis).split('qty ')[1].split()[0])
    except Exception: return 1


def run():
    now = pd.Timestamp.now(tz='America/New_York'); today = now.date()
    nxt = pd.Timestamp(np.busday_offset(today, 1, roll='forward', holidays=HOLIDAYS)).date()
    book = pd.read_csv(bankroll.BOOK)
    # ---- exits: earlier tickets (funded and watch) sold at today's close, real bid
    for _, r in book[(book.strategy == 'revticket') & (book.status == 'open')].iterrows():
        if dt.date.fromisoformat(r.created_date) >= today: continue
        try: S, age = er.live_price(r.symbol)
        except Exception as e: print(f"   RT EXIT {r.occ_code}: no spot ({str(e)[:40]})"); continue
        rv = float(r.thesis.split('RV30 ')[1].split('%')[0]) / 100; qn = qty_of(r)
        exp = dt.date.fromisoformat(str(r.expiry)[:10])
        Tx = (np.busday_count(today, exp, holidays=HOLIDAYS) + max(16 * 60 - (now.hour * 60 + now.minute), 0) / 390) / 252
        q = oq.fill(r.occ_code, 'sell', S, oq.spot_at(r.symbol) or S, rv=rv, T=Tx, patient=True,
                    spot_at_age=lambda m_, s_=r.symbol: oq.spot_at(s_, m_))
        K = float(r.strike); call = r.direction == 'call'
        intr = max((S - K) if call else (K - S), 0) * 100
        if q: px, src = q['prem'], f"REAL BID [{q['note']}]"
        elif exp <= today: px, src = intr, f"NO QUOTE - intrinsic ${intr:.0f} (expiring today)"
        else: print(f"   RT EXIT {r.occ_code}: NO QUOTE and not expiring - re-fetch before booking"); continue
        print(f"*** RT EXIT {r.occ_code} [{r.book}] x{qn} | {r.symbol} {S:.2f} | ${px * qn:.0f} (${px:.0f}/contract) vs entry "
              f"${r.entry_premium:.0f} ({px * qn / r.entry_premium - 1:+.0%}) | next-close exit | {src}")
    # ---- signals
    print(f"[{now:%H:%M}ET] reversal-ticket scan (A: failed gap-up >= {GAP:.0%} at the low | B: big-volume, big-range close at "
          f"the low/high) | next session {nxt}")
    mins = max(16 * 60 - (now.hour * 60 + now.minute), 0)
    hits = []
    for s in SYMS:
        try: d = er.daily_frame(s, '3mo').dropna()
        except Exception as e: print(f"   skip {s}: {str(e)[:40]}"); continue
        if len(d) < 35 or pd.Timestamp(d.index[-1]).date() != today: continue
        pc = float(d.C.iloc[-2]); O, H, L = float(d.O.iloc[-1]), float(d.H.iloc[-1]), float(d.L.iloc[-1])
        try: S, age = er.live_price(s)
        except Exception: S, age = float(d.C.iloc[-1]), 99
        H, L = max(H, S), min(L, S)
        gap = O / pc - 1; pos = (S - L) / (H - L) if H > L else 0.5
        rg = (d.H - d.L) / d.C.shift(); rz = (float((H - L) / pc) - rg.iloc[-31:-1].mean()) / rg.iloc[-31:-1].std()
        volx = float(d.V.iloc[-1]) * 390 / max(390 - mins, 1) / float(d.V.iloc[-21:-1].mean())
        kind = None
        if gap >= GAP and S < pc and pos <= POS: kind, trig = 'put', 'A failed gap-up'
        elif volx > 1.5 and rz > 2 and pos <= POS: kind, trig = 'put', 'B big-volume close at the low'
        elif volx > 1.5 and rz > 2 and pos >= 1 - POS: kind, trig = 'call', 'B big-volume close at the high'
        if not kind: continue
        rv = float(np.log(d.C / d.C.shift()).iloc[:-1].tail(30).std() * math.sqrt(252))
        hits.append((s, S, age, pc, O, H, L, gap, pos, rv, kind, trig, volx, rz))
    if not hits: print('   no signal tonight'); print('   ' + bankroll.summary()); return
    n = 0; spent = 0.0
    for s, S, age, pc, O, H, L, gap, pos, rv, kind, trig, volx, rz in hits:
        tag = (f"{s} {S:.2f} | {trig} | gap {gap:+.1%} (open {O:.2f} vs prior close {pc:.2f}), now {S / pc - 1:+.1%}, "
               f"{pos:.0%} of range {L:.2f}-{H:.2f}, vol {volx:.1f}x, range {rz:+.1f} sd | RV30 {rv:.0%}")
        why = []
        if age > er.STALE_SPOT_MIN: why.append(f'spot print {age:.0f} min old')
        if s not in EARN: why.append('no verified earnings date')
        elif today <= EARN[s] <= nxt: why.append(f'earnings {EARN[s]}')
        try: exps = [dt.date.fromisoformat(x) for x in yf.Ticker(s).options]
        except Exception: exps = []
        exps = [x for x in exps if today < x <= today + dt.timedelta(days=7)]
        if not exps: why.append('no listed expiry within 7 days')
        if why: print(f"   RT signal {tag} REJECTED: {'; '.join(why)}"); continue
        exp = exps[0]; ns = int(np.busday_count(today, exp, holidays=HOLIDAYS))
        T = (ns - 1 + mins / 390 + 1) / 252 if ns >= 1 else 1 / 252
        g = -1 if kind == 'put' else 1
        K = oq.snap(s, exp, S * math.exp(g * SIG * rv * math.sqrt(1 / 252)), 'down' if kind == 'put' else 'up')
        occ = f"{s}{exp.strftime('%y%m%d')}{'P' if kind == 'put' else 'C'}{int(round(K * 1000)):08d}"
        q = oq.fill(occ, 'buy', S, oq.spot_at(s) or S, rv=rv, T=T, patient=True, spot_at_age=lambda m_, s_=s: oq.spot_at(s_, m_))
        if not q or not q.get('iv_ask'):
            print(f"   RT signal {tag} REJECTED: no real quote on {occ}"); continue
        ivr = q['iv_ask'] / rv; sg = abs(math.log(K / S)) / (rv * math.sqrt(1 / 252))
        frac = next((f for x, f in TIERS if ivr <= x), 0.0)
        cap = min(frac * bankroll.state()['equity'], bankroll.budget('revticket', unbooked=spent, open_now=0))
        qn = min(MAXQ, int(cap // q['prem'])) if q['prem'] > 0 else 0
        base = (f"{tag} | {kind.upper()} {occ} ${q['prem']:.0f}/contract ({sg:.2f} daily-sigma, expiry {exp}, {ns} session(s)) | "
                f"IV ask {q['iv_ask']:.2f} = {ivr:.2f}x RV30 | spread {q['spread']:.0%}")
        if frac > 0 and qn >= 1 and n < MAXN:
            print(f"*** RT ENTRY {base} | FUNDED qty {qn} = ${q['prem'] * qn:.0f} (tier {frac:.1%} of equity, cap ${cap:.0f}) | "
                  f"sell at the {nxt} close\n      REAL ASK [{q['note']}]")
            n += 1; spent += q['prem'] * qn
        else:
            r_ = (f'IV {ivr:.2f}x > 1.10x RV' if frac == 0 else f'${q["prem"]:.0f} > ${cap:.0f} cap' if qn < 1 else 'max funded tonight')
            print(f"*** RT LOG {base} | WATCH ONLY qty 1 ({r_}) | sell at the {nxt} close\n      REAL ASK [{q['note']}]")
    print('   ' + bankroll.summary())


if __name__ == '__main__':
    run()
