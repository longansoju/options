"""User 11-28: "backtest the split rule" - half the position at the EARLY signal (first 5m close back across VWAP after
trading on the wrong side of it), half at CONFIRMATION (opening-range break held 2 consecutive 5m closes ~= the engine's 10
one-minute closes). Rules fixed BEFORE running (from the 11-28 chat):
  CALL side (PUT side mirrored):
    setup  : at least one 5m close BELOW VWAP from 09:35 on
    E1     : first 5m close back ABOVE VWAP at/after 09:45 and before 14:00, after the setup
    E2     : first time (10:00-15:00) two consecutive 5m closes are above the opening-range high AND above VWAP
    exits  : any open leg is sold at the first 5m close back BELOW VWAP, else at the 15:45 bar (the last bar on a half day);
             E1 is also sold if price trades below the morning low (lowest low before E1) - the "stop under the low"
  strategies (one trade per name / side / day): S1 confirmed only (full size at E2) | S2 early only (full size at E1) |
             S3 split (half at E1, half at E2; a leg that never fires is simply not bought)
  filters  : A = Friday's set-up: gap in the trade's direction (open beyond prior close) AND the morning low/high never
             crossed the prior close before E1;  B = no gap filter (every day)
Vehicle: the 2-week 0.2-sigma option (Friday two weeks out), Black-Scholes at RV30, 8% round-trip spread (pay 4% over mid,
sell 4% under). Underlying % moves are reported alongside. IS / OOS = first / second half of the sessions.
Data: research/month_review-style 5m bars (scratchpad mr/data_merged2.pkl), 26 names, 2026-08-12 -> 2026-11-27.
  python research/split_entry_bt.py <scratchpad>/mr/"""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

D = sys.argv[1]
data = pd.read_pickle(D + 'data_merged2.pkl')
N = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
SPREAD = 0.08
import os; HOLD_TO_CLOSE = os.environ.get("EXIT") == "close"   # robustness: ignore the VWAP exit, hold every leg to 15:45


def bs(S, K, T, v, k):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)


def T_at(ts, exp):
    close = 13 * 60 if ts.date() == dt.date(2026, 11, 27) else 16 * 60
    return (max(close - (ts.hour * 60 + ts.minute + 5), 0) / 390 + int(np.busday_count(ts.date(), exp, holidays=['2026-11-26']))) / 252


rows = []
for s, (b, d) in data.items():
    if s == 'SMH': continue
    dd = d.copy(); dd.index = [pd.Timestamp(i).date() for i in dd.index]
    for day, x in b.groupby(b.index.date):
        if len(x) < 40: continue
        h = dd[dd.index < day]
        if len(h) < 31: continue
        pc = float(h.C.iloc[-1]); rv = float(h.C.pct_change().tail(30).std() * math.sqrt(252))
        vw = ((x.C * x.V).cumsum() / x.V.cumsum()).values
        C, H, L, t = x.C.values, x.H.values, x.L.values, x.index
        o = x[x.index.time < dt.time(10, 0)]; orh, orl = o.H.max(), o.L.min(); op = x.O.iloc[0]
        exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 14)
        last = len(x) - 1
        for i in range(len(x)):
            if t[i].time() >= dt.time(15, 45): last = i; break
        for k, g in (('call', 1), ('put', -1)):
            above = lambda i: (C[i] - vw[i]) * g > 0
            # E1
            seen_wrong, e1 = False, None
            for i in range(len(x)):
                if t[i].time() < dt.time(9, 35): continue
                if not above(i): seen_wrong = True
                elif seen_wrong and dt.time(9, 45) <= t[i].time() < dt.time(14, 0):
                    e1 = i; break
            # E2
            e2 = None
            for i in range(1, len(x)):
                if not (dt.time(10, 0) <= t[i].time() < dt.time(15, 0)): continue
                lv = orh if g == 1 else orl
                if all((C[j] - lv) * g > 0 and above(j) for j in (i - 1, i)) and t[i - 1].time() >= dt.time(10, 0):
                    e2 = i; break
            gapdir = (op - pc) * g > 0
            held = e1 is not None and ((min(L[:e1 + 1]) > pc) if g == 1 else (max(H[:e1 + 1]) < pc))

            def leg(i, stop_low=False):
                if i is None: return None
                S0 = C[i]; T0 = T_at(t[i], exp); K = S0 * math.exp(g * 0.2 * rv * math.sqrt(T0)); p0 = bs(S0, K, T0, rv, k) * (1 + SPREAD / 2)
                mlow = min(L[:i + 1]) if g == 1 else max(H[:i + 1])
                for j in range(i + 1, last + 1):
                    if stop_low and (L[j] < mlow if g == 1 else H[j] > mlow):
                        Sx, tx = mlow, t[j]; break
                    if not above(j) and not HOLD_TO_CLOSE: Sx, tx = C[j], t[j]; break
                else:
                    j = last; Sx, tx = C[j], t[j]
                px = bs(Sx, K, T_at(tx, exp), rv, k) * (1 - SPREAD / 2)
                return px / p0 - 1, (Sx / S0 - 1) * g
            r1, r2 = leg(e1, stop_low=True), leg(e2)
            rows.append(dict(sym=s, day=day, kind=k, gapA=gapdir and held, e1=r1[0] if r1 else np.nan, u1=r1[1] if r1 else np.nan,
                             e2=r2[0] if r2 else np.nan, u2=r2[1] if r2 else np.nan))
R = pd.DataFrame(rows)
days = sorted(R.day.unique()); mid = days[len(days) // 2]; t3 = [days[len(days) // 3], days[2 * len(days) // 3]]
print(f"name-day-sides {len(R)} | sessions {days[0]} -> {days[-1]} | 2-week 0.2-sigma option at RV30, 8% spread\n")


def report(lab, X):
    s1 = X.e2; s2 = X.e1; s3 = 0.5 * X.e1.fillna(0) + 0.5 * X.e2.fillna(0)
    s3 = s3.where(X.e1.notna() | X.e2.notna())
    print(f"{lab}")
    for nm, sr, size in (('S1 confirmed only', s1, 1.0), ('S2 early only', s2, 1.0), ('S3 split 50/50', s3, None)):
        z = sr.dropna(); d = X.loc[z.index, 'day']
        per = lambda m: f"{z[m].mean():+6.1%}" if m.sum() else '   n/a'
        print(f"   {nm:18s} trades {len(z):4d} | win {(z > 0).mean():3.0%} | avg {z.mean():+6.1%} per trade (premium) | total {z.sum():+7.1f} units | "
              f"IS {per(d < mid)} OOS {per(d >= mid)} | P1 {per(d < t3[0])} P2 {per((d >= t3[0]) & (d < t3[1]))} P3 {per(d >= t3[1])}")
    both = X[X.e1.notna() & X.e2.notna()]
    print(f"   days where BOTH fired: {len(both)} | E1 leg {both.e1.mean():+.1%}, E2 leg {both.e2.mean():+.1%} | days E1 fired but no confirmation: "
          f"{(X.e1.notna() & X.e2.isna()).sum()} (E1 avg there {X[X.e1.notna() & X.e2.isna()].e1.mean():+.1%})")
    print(f"   underlying move, E1 legs {X.u1.mean():+.2%} | E2 legs {X.u2.mean():+.2%}\n")


for flt, lab in ((R.gapA, 'A  Friday set-up (gap in the trade direction that HELD the prior close before E1)'), (R.index == R.index, 'B  every day (no gap filter)')):
    for k in ('call', 'put'):
        report(f"{lab} - {k.upper()}S", R[flt & (R.kind == k)])
fri = R[(R.sym == 'MU') & (R.day == dt.date(2026, 11, 27)) & (R.kind == 'call')]
print('check - MU calls Fri 11-27:', fri[['gapA', 'e1', 'e2', 'u1', 'u2']].round(3).to_dict('records'))
