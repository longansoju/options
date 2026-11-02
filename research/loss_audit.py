"""User 11-02: "for the losses made throughout our record, was there a way to prevent them?"
Every closed swing / momentum / day trade in the book (paper, real and the 09-14 watch basket) is
re-scored at its entry date with TODAY's rules - strike distance in sigma, whipsaw, 3-day counter-
trend, RSI - and its daily premium path (BS at RV30, the book's own pricing) is re-run under today's
exits (resting -50% stop, trailing after +50%, 21-DTE swing / 2-DTE momentum). Winners are scored the
same way, so a rule only counts if it removes more losing dollars than winning dollars (hindsight check).
Strangles / 1-day tickets are excluded: direction-free volatility bets with no entry gate to audit."""
import sys, math, re, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er
from analysis.harvest import whipsaw_stats
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
b = pd.read_csv('/home/user/options/data/recommendations.csv')
c = b[(b.status == 'closed') & b.strategy.isin(['swing', 'momentum', 'daytrade'])].copy()
c['usd'] = c.exit_premium - c.entry_premium
cache = {}
rows = []
for r in c.itertuples():
    if r.symbol not in cache:
        try: d = er.daily_frame(r.symbol, '2y').dropna(); d.index = [pd.Timestamp(i).date() for i in d.index]; cache[r.symbol] = d
        except Exception as e: cache[r.symbol] = None; print('skip', r.symbol, e)
    d = cache[r.symbol]
    if d is None: continue
    day = dt.date.fromisoformat(r.created_date); exp = dt.date.fromisoformat(r.expiry)
    h = d[[i <= day for i in d.index]]; cl = h.C
    if len(cl) < 40: continue
    S = float(r.entry_ref_price) if r.entry_ref_price == r.entry_ref_price else float(cl.iloc[-1])
    rv = float(cl.pct_change().tail(30).std() * math.sqrt(252)); T = max(np.busday_count(day, exp), 1) / 252
    sig = abs(math.log(r.strike / S)) / (rv * math.sqrt(T))
    prior = cl.iloc[:-1] if r.strategy == 'daytrade' else cl          # day trades decide intraday on prior closes
    w = whipsaw_stats(prior); ct3 = (prior.iloc[-1] / prior.iloc[-4] - 1) * 100
    dl = prior.diff(); g = dl.clip(lower=0).ewm(alpha=1 / 14).mean(); l = (-dl.clip(upper=0)).ewm(alpha=1 / 14).mean()
    rsi = float(100 - 100 / (1 + g.iloc[-1] / l.iloc[-1]))
    k = r.direction
    flags = []
    if r.entry_premium > 1000: flags.append('size > $1,000')
    if sig > 0.6: flags.append('strike > 0.6σ')
    if w['chop']: flags.append('whipsaw')
    if (k == 'call' and ct3 < 0) or (k == 'put' and ct3 > 0): flags.append('counter-trend')
    if (k == 'call' and rsi > 70) or (k == 'put' and rsi < 32): flags.append('RSI')
    txt = f"{r.thesis} {r.notes}".lower()
    if re.search(r"before .{0,30}earnings|hours before|earnings that i failed|failed to check", txt): flags.append('earnings ignored')
    # today's exit on the daily path (multi-day trades only)
    alt = None
    if r.strategy != 'daytrade':
        p0 = r.entry_premium / 100; fut = d[[day < i <= exp for i in d.index]]; peak = None; alt = None
        for i, row in fut.iterrows():
            bd = int(np.busday_count(i, exp)); Tm = (bd + 0.5) / 252
            wv = bs(row.L if k == 'call' else row.H, r.strike, Tm, rv, k) * 100 / r.entry_premium * 100 * p0 / p0 - 100
            bv = bs(row.H if k == 'call' else row.L, r.strike, Tm, rv, k) * 100 / r.entry_premium * 100 - 100
            cv = bs(row.C, r.strike, max(bd, 1e-3) / 252, rv, k) * 100 / r.entry_premium * 100 - 100
            # rescale model path to the booked entry premium (model p0 at entry)
            m0 = bs(S, r.strike, T, rv, k) * 100
            sc = r.entry_premium / m0 if m0 > 0 else 1
            wv, bv, cv = [((100 + x) * sc - 100) for x in (wv, bv, cv)]
            if wv <= -50: alt = -50.0; break
            if peak is not None and (100 + wv) <= (100 + peak) * 0.7: alt = (100 + peak) * 0.7 - 100; break
            if bv >= 50: peak = bv if peak is None else max(peak, bv)
            if bd <= (21 if r.strategy == 'swing' else 2): alt = cv; break
        if alt is None: alt = r.pnl_pct
    rows.append(dict(book=r.book, strat=r.strategy, day=day, sym=r.symbol, kind=k, sig=sig, ct3=ct3, rsi=rsi, prem=r.entry_premium,
                     pnl=r.pnl_pct, usd=r.usd, alt=alt, alt_usd=None if alt is None else alt / 100 * r.entry_premium, why=', '.join(flags)))
A = pd.DataFrame(rows)
pd.set_option('display.width', 250)
L = A[A.usd < 0].sort_values('usd')
print(L[['book', 'strat', 'day', 'sym', 'kind', 'sig', 'ct3', 'rsi', 'prem', 'pnl', 'usd', 'alt', 'why']].round(2).to_string(index=False))
print('\n=== would today\'s ENTRY rules have blocked it? (losers vs winners)')
A['blocked'] = A['why'] != ''
for k, g in A.groupby('blocked'):
    print(f"  {'blocked' if k else 'passes '}: n={len(g):3d} losers {(g.usd < 0).sum():3d} (${g[g.usd < 0].usd.sum():+,.0f}) winners {(g.usd > 0).sum():3d} (${g[g.usd > 0].usd.sum():+,.0f}) net ${g.usd.sum():+,.0f}")
for f in ('size > $1,000', 'strike > 0.6σ', 'whipsaw', 'counter-trend', 'RSI', 'earnings ignored'):
    g = A[A['why'].str.contains(f, regex=False)]
    print(f"  {f:18s} flags n={len(g):3d}: losers ${g[g.usd < 0].usd.sum():+,.0f}, winners ${g[g.usd > 0].usd.sum():+,.0f}, net ${g.usd.sum():+,.0f}")
M = A[A.strat != 'daytrade']
print(f"\n=== today's EXIT rules on the multi-day trades (n={len(M)}): booked ${M.usd.sum():+,.0f} -> re-run ${M.alt_usd.sum():+,.0f}")
P = A[(A.usd < 0) & ~A.blocked]
S = A[A['why'].str.contains('size', regex=False)]
print(f"=== the oversized trades re-run at today's \$1,000 cap (scaled to $1,000 premium): booked ${S.usd.sum():+,.0f} -> ${(S.pnl / 100 * 1000).sum():+,.0f}")
print(f"=== losers that pass every entry rule today: n={len(P)}, ${P.usd.sum():+,.0f} (after today's exits ${P.alt_usd.fillna(P.usd).sum():+,.0f})")
A.to_pickle('/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/loss_audit.pkl')
