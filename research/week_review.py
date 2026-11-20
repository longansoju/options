"""Weekly review of every day-trade signal the engine saw, priced as if taken (user 11-13: "apply it, let's see how we
perform next week"; review of the 25%-of-equity size cap + the 10% real-spread cap adopted 11-13).

Input: the engine log (signals and rejections are printed with price and the OR level) split into sessions by the
first heartbeat of each day; 1m bars from yfinance (7 days kept). Each signal is replayed on the 2-week 0.2-sigma
vehicle at RV30 (model mid path) with the live exits (+20 / -20 / 120 min / 15:45), then charged a spread:
  4%  = the pen-test friction;  8% = the median real 2-week spread logged since 11-04.
Buckets by WHY the signal was not taken: taken | budget/spread (the 11-13 rules) | gates | other.
The model has no real IV and no real fills: it answers "what did the new caps keep us out of", not "what would we have made".
  python research/week_review.py <engine log> 2026-11-16:434 2026-11-17:468 ...   (date:first log line of that session)
"""
import re, sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, yfinance as yf

LOG = sys.argv[1]
SESS = [(dt.date.fromisoformat(a.split(':')[0]), int(a.split(':')[1])) for a in sys.argv[2:]]
L = open(LOG).read().splitlines()
N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, k):
    T = max(T, 1e-7); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)


sig = []
for i, (day, start) in enumerate(SESS):
    end = SESS[i + 1][1] if i + 1 < len(SESS) else len(L) + 1
    last = None
    for l in L[start - 1:end - 1]:
        m = re.match(r'\[(\d\d):(\d\d)ET', l)
        if m: last = dt.time(int(m.group(1)), int(m.group(2)))
        m = re.search(r'DT signal (\w+) (put|call) REJECTED: (.*?) \| ([\d.]+) OR', l)
        if m: sig.append((day, m.group(1), m.group(2), m.group(3), float(m.group(4)), last)); continue
        m = re.search(r'DT ENTRY (\w+) (PUT|CALL) \S+ ~\$\d+ .*? \| \w+ ([\d.]+) broke', l)
        if m: sig.append((day, m.group(1), m.group(2).lower(), 'TAKEN', float(m.group(3)), last))

bars, rvs = {}, {}
rows = []
for day, s, k, why, px, t0 in sig:
    if s not in bars:
        h = yf.Ticker(s).history(period='7d', interval='1m').between_time('09:30', '16:00')
        bars[s] = h; d = yf.Ticker(s).history(period='3mo').Close
        rvs[s] = d
    m = bars[s][bars[s].index.date == day]
    if not len(m): continue
    d = rvs[s]; d = d[d.index.date < day]
    rv = float(np.log(d / d.shift()).dropna().tail(30).std() * 252 ** .5)
    after = m[m.index.time >= (t0 or dt.time(9, 30))]
    hit = after[(after.Close - px).abs() <= max(0.0015 * px, 0.05)]
    if not len(hit): hit = m[(m.Close - px).abs() <= max(0.0015 * px, 0.05)]
    if not len(hit): continue
    ts = hit.index[0]; S0 = float(m.Close.loc[ts]); g = 1 if k == 'call' else -1
    T0 = 10 / 252; K = S0 * math.exp(g * 0.2 * rv * math.sqrt(T0)); p0 = bs(S0, K, T0, rv, k)
    path = []
    for t, b in m[m.index > ts].iterrows():
        mins = (t - ts).seconds / 60; T = T0 - mins / 390 / 252
        path.append((mins, t.time(), bs(b.Low if g == 1 else b.High, K, T, rv, k) / p0 - 1,
                     bs(b.High if g == 1 else b.Low, K, T, rv, k) / p0 - 1, bs(b.Close, K, T, rv, k) / p0 - 1))

    def run(spread):
        f = lambda r: (1 + r) * (1 - spread / 2) / (1 + spread / 2) - 1   # mark at the bid against the ask paid
        for mins, t, w, bb, c in path:
            if f(w) <= -0.2: return -0.2
            if f(bb) >= 0.2: return 0.2
            if mins >= 120 or t >= dt.time(15, 45): return f(c)
        return f(path[-1][4]) if path else 0.0
    bucket = 'taken' if why == 'TAKEN' else 'budget/spread' if why.startswith('no 0-0.4') else \
        'gates' if any(x in why for x in ('counter-trend', 'whipsaw', 'RSI', 'earnings', 'verified')) else 'other'
    rows.append(dict(day=day, sym=s, kind=k, time=ts.strftime('%H:%M'), bucket=bucket, why=why[:30], prem=round(p0 * 100),
                     r4=run(0.04), r8=run(0.08)))

R = pd.DataFrame(rows)
pd.set_option('display.width', 220)
print(R.assign(r4=(R.r4 * 100).round(1), r8=(R.r8 * 100).round(1)).to_string(index=False))
print(f"\nsignals replayed: {len(R)} over {R.day.nunique()} sessions")
for b, x in R.groupby('bucket'):
    print(f"  {b:14s} n={len(x):3d} win(8%) {(x.r8 > 0).mean():.0%} avg @4% {x.r4.mean():+.1%} @8% {x.r8.mean():+.1%} | "
          + ' '.join(f"{d.strftime('%m-%d')} {y.r8.mean():+.0%}({len(y)})" for d, y in x.groupby('day')))
bs_ = R[R.bucket == 'budget/spread']
print(f"\nbudget/spread rejections: model premium median ${bs_.prem.median():.0f}, "
      f"{(bs_.prem <= 524).mean():.0%} would fit the old 50% cap (~$524), {(bs_.prem <= 262).mean():.0%} fit $262 "
      f"(the rest of those were the spread cap)")
for c, lab in ((262, 'current 25% cap'), (524, 'old 50% cap')):
    x = R[(R.bucket != 'gates') & (R.prem <= c)]
    print(f"  gate-passing signals within the {lab} (${c}): n={len(x)} avg @8% {x.r8.mean():+.1%} win {(x.r8 > 0).mean():.0%}")
