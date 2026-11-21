"""REVERSAL TICKET engine - the MU 261120 680P setup, as a fixed-rule paper strategy (user 11-21: "fix the rules based on
how you want me to do it properly and add it as a strategy"). Run once per session at ~15:50 ET, after the other close
engines:  python research/revticket_engine.py

Evidence (research/repeat_lottery.py, 27 names, 5y daily, 101 signal nights, 10% round-trip friction): a ~1 daily-sigma put
expiring the next session, bought at the close of a FAILED GAP-UP that closes at the day's low and sold at the next close:
  IV = 1.0x RV30: +71% per ticket   |   1.3x: -14%   |   1.6x: -45%   (median -100%, win 14-17%, 4-13% of tickets >= 5x)
The next day itself is a coin flip in direction (research/reversal_close.py: P(-5%) 19.6% vs P(+5%) 17.6%); the edge, if
any, exists ONLY when the real option is cheap relative to realized vol. Real 1-day readings logged so far: 1.35-2.1x.
So this is a forward test of one question: how often is the real ticket cheap enough, and does it pay when it is?

RULES (all fixed in advance):
  SIGNAL   gap up >= 3% (today's open vs yesterday's close) AND price below yesterday's close AND price in the bottom 10%
           of today's high-low range at ~15:50 ET.  Universe: config.FOCUS_AI_SEMI_IT + DAYTRADE_EXPANSION.
  VEHICLE  1 put, strike ~1.0 daily-sigma below the price (listed strike, snapped down), expiring the NEXT session - only if
           that expiry is actually listed (Yahoo's expiry list).
  PRICE    a real Yahoo quote is required. FUNDED only if IV at the ask <= 1.10 x RV30 (the break-even zone of the test)
           AND the ask fits the cap; otherwise logged as book=watch with its real IV so the data still accumulates.
  SIZE     <= 2% of November equity per ticket (bankroll.CAP['revticket']), max 2 funded per night.
  BLOCKS   earnings today or the next session; no verified earnings date; spot older than er.STALE_SPOT_MIN.
  EXIT     sold at the NEXT session's ~15:50 ET run at the real bid (the test's exit).
Review at 30 signals: real IV/RV distribution, how many were fundable, and the funded P&L vs the test's +71%/-14% rows.
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
GAP, POS, SIG, IV_MAX, MAXN = 0.03, 0.10, 1.0, 1.10, 2


def run():
    now = pd.Timestamp.now(tz='America/New_York'); today = now.date()
    nxt = pd.Timestamp(np.busday_offset(today, 1, roll='forward', holidays=HOLIDAYS)).date()
    book = pd.read_csv(bankroll.BOOK)
    # ---- exits: yesterday's tickets (funded and watch) sold at today's close, real bid
    for _, r in book[(book.strategy == 'revticket') & (book.status == 'open')].iterrows():
        if dt.date.fromisoformat(r.created_date) >= today: continue
        try: S, age = er.live_price(r.symbol)
        except Exception as e: print(f"   RT EXIT {r.occ_code}: no spot ({str(e)[:40]})"); continue
        rv = float(r.thesis.split('RV30 ')[1].split('%')[0]) / 100
        q = oq.fill(r.occ_code, 'sell', S, oq.spot_at(r.symbol) or S, rv=rv, patient=True,
                    spot_at_age=lambda m_, s_=r.symbol: oq.spot_at(s_, m_))
        K = float(r.strike); intr = max(K - S, 0) * 100
        px = q['prem'] if q else intr
        src = f"REAL BID [{q['note']}]" if q else f"NO QUOTE - intrinsic ${intr:.0f} (expiring today)"
        print(f"*** RT EXIT {r.occ_code} [{r.book}] | {r.symbol} {S:.2f} | ${px:.0f} vs entry ${r.entry_premium:.0f} "
              f"({px / r.entry_premium - 1:+.0%}) | next-close exit | {src}")
    # ---- signals
    print(f"[{now:%H:%M}ET] reversal-ticket scan (failed gap-up >= {GAP:.0%}, closing in the bottom {POS:.0%} of the range) | next session {nxt}")
    hits = []
    for s in SYMS:
        try: d = er.daily_frame(s, '3mo').dropna()
        except Exception as e: print(f"   skip {s}: {str(e)[:40]}"); continue
        if len(d) < 35 or pd.Timestamp(d.index[-1]).date() != today: continue
        pc = float(d.C.iloc[-2]); O, H, L = float(d.O.iloc[-1]), float(d.H.iloc[-1]), float(d.L.iloc[-1])
        try: S, age = er.live_price(s)
        except Exception: S, age = float(d.C.iloc[-1]), 99
        H, L = max(H, S), min(L, S)
        gap = O / pc - 1; pos = (S - L) / (H - L) if H > L else 1.0
        if not (gap >= GAP and S < pc and pos <= POS): continue
        rv = float(np.log(d.C / d.C.shift()).iloc[:-1].tail(30).std() * math.sqrt(252))
        hits.append((s, S, age, pc, O, H, L, gap, pos, rv))
    if not hits: print('   no signal tonight'); print('   ' + bankroll.summary()); return
    n = 0; spent = 0.0
    for s, S, age, pc, O, H, L, gap, pos, rv in hits:
        tag = f"{s} {S:.2f} | gap {gap:+.1%} (open {O:.2f} vs prior close {pc:.2f}), now {S / pc - 1:+.1%}, {pos:.0%} of range {L:.2f}-{H:.2f} | RV30 {rv:.0%}"
        why = []
        if age > er.STALE_SPOT_MIN: why.append(f'spot print {age:.0f} min old')
        if s not in EARN: why.append('no verified earnings date')
        elif today <= EARN[s] <= nxt: why.append(f'earnings {EARN[s]}')
        try: listed = nxt.isoformat() in yf.Ticker(s).options
        except Exception: listed = False
        if not listed: why.append(f'no listed expiry on {nxt}')
        if why: print(f"   RT signal {tag} REJECTED: {'; '.join(why)}"); continue
        T = (max(16 * 60 - (now.hour * 60 + now.minute), 0) / 390 + 1) / 252
        K = oq.snap(s, nxt, S * math.exp(-SIG * rv * math.sqrt(1 / 252)), 'down')
        occ = f"{s}{nxt.strftime('%y%m%d')}P{int(round(K * 1000)):08d}"
        q = oq.fill(occ, 'buy', S, oq.spot_at(s) or S, rv=rv, T=T, patient=True, spot_at_age=lambda m_, s_=s: oq.spot_at(s_, m_))
        if not q or not q.get('iv_ask'):
            print(f"   RT signal {tag} REJECTED: no real quote on {occ}"); continue
        ivr = q['iv_ask'] / rv; sig = abs(math.log(K / S)) / (rv * math.sqrt(1 / 252))
        cap = bankroll.budget('revticket', unbooked=spent)
        base = f"{tag} | PUT {occ} ${q['prem']:.0f} ({sig:.2f} daily-sigma) | IV ask {q['iv_ask']:.2f} = {ivr:.2f}x RV30 | spread {q['spread']:.0%}"
        if ivr <= IV_MAX and q['prem'] <= cap and n < MAXN:
            print(f"*** RT ENTRY {base} | FUNDED (cap ${cap:.0f}) | sell at the {nxt} close\n      REAL ASK [{q['note']}]")
            n += 1; spent += q['prem']
        else:
            r_ = 'IV ' + (f'{ivr:.2f}x > {IV_MAX}x RV' if ivr > IV_MAX else 'ok') + ('' if q['prem'] <= cap else f'; ${q["prem"]:.0f} > ${cap:.0f} cap') + ('' if n < MAXN else '; max funded tonight')
            print(f"*** RT LOG {base} | WATCH ONLY ({r_}) | sell at the {nxt} close\n      REAL ASK [{q['note']}]")
    print('   ' + bankroll.summary())


if __name__ == '__main__':
    run()
