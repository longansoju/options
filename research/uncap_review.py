"""User 11-28: "uncap the paper book. perform a backtest to see whether we missed out on profit making opportunities".
Question: in November (11-02 -> 11-27), which signals did the $1,000-book CAPS keep out, and would they have made money?
Rules fixed before running; only the premium cap is varied, every other rule kept.
  A  DAY TRADES - every opening-range signal rebuilt on 5m bars (month_review.py logic: break held 2 x 5m closes, VWAP side,
     relvol >= 1.0x, 10:00-15:00, first per name/side/day), gates applied as live (whipsaw, 3d counter-trend at 1%, RSI).
     Vehicle 2-week 0.2-sigma, BS at RV30 (mid path), exits +20/-20/120m/15:45, charged an 8% real spread (median logged).
     Cap at the time = 50% (to 11-12) / 25% (from 11-13) of book equity that day. Buckets: fit the cap | over the cap but
     <= $1,000 | over $1,000.  Whole 08-12 -> 11-27 window also shown (both halves) so November is not read alone.
  B  1-DAY TICKETS - the lottery engine's trigger (volume > 1.5x AND range > 2 x 20d sd, at the close), only names with a
     listed next-session expiry, ~1 daily-sigma call + put, sold at the next open (overnight-variance pricing, put skew,
     10% friction - lottery_event.py). IV at 1.0x and 1.5x RV30 (real 1-day asks logged 1.35-2.1x). Cap = min($300, 10% eq).
  Model prices, no real quotes: answers "what did the caps keep us out of", not "what would we have made".
  python research/uncap_review.py <scratchpad>/mr/"""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
D = sys.argv[1]
SPREAD = 0.08
book = pd.read_csv('/home/user/options/data/recommendations.csv')
f = book[(book.book == 'paper') & (book.created_date >= '2026-11-02') & (book.status == 'closed')]
def equity(day): return 1000 + float((f[f.exit_date < str(day)].exit_premium - f[f.exit_date < str(day)].entry_premium).sum())

# ---------- A: day trades (reuse month_review's signal builder on the merged 5m data)
src = open('/home/user/options/research/month_review.py').read().split('R = pd.DataFrame(rows)')[0]
src = src.replace("OUT = '/tmp/claude-0/-home-user-options/d48d96a0-6287-5653-9e57-8256394e61c5/scratchpad/mr/'", f"OUT = {D!r}")
src = src.replace("('data_merged.pkl' if 'merged' in sys.argv else 'data.pkl')", "'data_merged2.pkl'")
src = src.replace("if p0 * 100 > 1000: blocks.append('budget')", "pass")
exec(src)
R = pd.DataFrame(rows)
exec(open('/home/user/options/research/month_review.py').read().split('R = pd.DataFrame(rows)')[1].split("R['cur']")[0])   # ex()
R['pnl'] = [ex(p) - SPREAD for p in R.path]
G = R[R.blocks == ''].copy()
days = sorted(R.day.unique()); cut = days[len(days) // 2]
def show(n, g):
    if not len(g): print(f"  {n:44s} n=   0"); return
    i, o = g[g.day < cut], g[g.day >= cut]
    print(f"  {n:44s} n={len(g):4d} win {(g.pnl > 0).mean():4.0%} avg {g.pnl.mean():+6.1%} | IS {i.pnl.mean() if len(i) else np.nan:+6.1%} ({len(i)}) "
          f"OOS {o.pnl.mean() if len(o) else np.nan:+6.1%} ({len(o)}) | $ {(g.pnl * g.prem).sum():+8,.0f} on ${g.prem.sum():,.0f}")
print(f"A. DAY TRADES  sessions {days[0]} -> {days[-1]} | gate-passing signals {len(G)} of {len(R)} | 8% spread, model mid path\n")
show('whole window, all gate-passing', G)
for lo, hi, lab in ((0, 1000, '<= $1,000'), (1000, 1e9, '> $1,000')): show(f'whole window, premium {lab}', G[(G.prem > lo) & (G.prem <= hi)])
N_ = G[G.day >= dt.date(2026, 11, 2)].copy()
N_['cap'] = [equity(d) * (0.5 if d < dt.date(2026, 11, 13) else 0.25) for d in N_.day]
print('\n  November 11-02 -> 11-27:')
show('all gate-passing (= fully uncapped)', N_)
show('fit the cap at the time', N_[N_.prem <= N_.cap])
show('over the cap, <= $1,000  (MISSED by the cap)', N_[(N_.prem > N_.cap) & (N_.prem <= 1000)])
show('over $1,000  (MISSED by the $1k ceiling)', N_[N_.prem > 1000])
show('after the 11-24 pause', N_[N_.day >= dt.date(2026, 11, 24)])
for k, g in N_.groupby('kind'): show(f'  {k}s', g)
print('  weekly:', ' | '.join(f"wk {str(w)[5:10]} n={len(g)} {g.pnl.mean():+.1%} ${(g.pnl * g.prem).sum():+,.0f}" for w, g in N_.groupby([pd.Timestamp(d).to_period('W') for d in N_.day])))
over = N_[N_.prem > N_.cap].sort_values('pnl')
print('  biggest missed winners:', ', '.join(f"{r.sym} {r.kind} {r.day:%m-%d} ${r.prem:,.0f} {r.pnl:+.0%}" for r in over.tail(6)[::-1].itertuples()))
print('  biggest missed losers :', ', '.join(f"{r.sym} {r.kind} {r.day:%m-%d} ${r.prem:,.0f} {r.pnl:+.0%}" for r in over.head(6).itertuples()))

# ---------- B: 1-day tickets
def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def bs(S, K, T, v, k):
    if T <= 0: return max(S - K, 0) if k == 'call' else max(K - S, 0)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if k == 'call' else K * N(-d2) - S * N(-d1)
DAILY = {'NVDA', 'AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'MU'}
HOL = [dt.date(2026, 11, 26)]
rows = []
for s in config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION:
    d = data[s][1].copy(); d.index = [pd.Timestamp(i).date() for i in d.index]
    c = d.C; r1 = c.pct_change(); cc = np.log(c / c.shift(1)); gp = np.log(d.O / c.shift(1))
    fr = float(np.clip((gp ** 2).tail(250).mean() / (cc ** 2).tail(250).mean(), 0.05, 0.9))
    for i in range(30, len(d) - 1):
        day = d.index[i]
        if day < dt.date(2026, 11, 2): continue
        nx = d.index[i + 1]
        sd20 = float(r1.iloc[i - 20:i].std()); volx = float(d.V.iloc[i] / d.V.iloc[i - 20:i].mean())
        rng = float((d.H.iloc[i] - d.L.iloc[i]) / c.iloc[i] / sd20)
        if not (volx > 1.5 and rng > 2): continue
        if not ((s in DAILY and nx.weekday() in (0, 2, 4)) or nx.weekday() == 4): continue
        S = float(c.iloc[i]); rv = float(cc.iloc[i - 29:i + 1].std() * math.sqrt(252)); sd = rv * math.sqrt(1 / 252); O = float(d.O.iloc[i + 1])
        r = dict(sym=s, day=day, cap=min(300, 0.10 * equity(day)))
        for m in (1.0, 1.5):
            p = x = 0.0
            for k, g_ in (('call', 1), ('put', -1)):
                K = S * math.exp(g_ * sd); iv = rv * m * (1.15 if k == 'put' else 1)
                p += bs(S, K, 1 / 252, iv, k) * 100; x += bs(O, K, (1 - fr) / 252, iv, k) * 100
            r[f'prem{m}'] = p; r[f'pnl{m}'] = x / p - 1 - 0.10
        rows.append(r)
B = pd.DataFrame(rows)
print(f"\nB. 1-DAY TICKETS  November trigger nights with a listed next-session expiry: {len(B)} (both legs, sold at the next open, 10% friction)")
for m in (1.0, 1.5):
    fit = B[f'prem{m}'] <= B.cap
    for lab, g in (('all (uncapped)', B), ('fit the cap', B[fit]), ('over the cap (MISSED)', B[~fit])):
        print(f"  IV {m}x RV  {lab:24s} n={len(g):3d} win {(g[f'pnl{m}'] > 0).mean() if len(g) else 0:4.0%} avg {g[f'pnl{m}'].mean() if len(g) else 0:+6.1%} "
              f"$ {(g[f'pnl{m}'] * g[f'prem{m}']).sum():+8,.0f} on ${g[f'prem{m}'].sum():,.0f}")
B.to_pickle(D + "B.pkl")
print('  by night (one market event = one bet):')
for d_, g in B.groupby('day'):
    print(f"    {d_}  {len(g):2d} names  1.0x {(g['pnl1.0'] * g['prem1.0']).sum():+7,.0f} on ${g['prem1.0'].sum():6,.0f} | 1.5x {(g['pnl1.5'] * g['prem1.5']).sum():+7,.0f} on ${g['prem1.5'].sum():6,.0f} | "
          + ', '.join(f"{r.sym} {r._7:+.0%}" for r in g.itertuples()))
print('  check vs REAL fills the engine booked the same nights (pair, ask in / bid out):')
for sym, day, real in (('AAPL', '2026-11-05', 131 / 157 - 1), ('SMCI', '2026-11-05', 32 / 38 - 1)):
    r = B[(B.sym == sym) & (B.day.astype(str) == day)]
    if len(r): print(f"    {sym} {day}: real {real:+.0%} | model 1.0x {r['pnl1.0'].iloc[0]:+.0%} (pair ${r['prem1.0'].iloc[0]:.0f}) | 1.5x {r['pnl1.5'].iloc[0]:+.0%} (pair ${r['prem1.5'].iloc[0]:.0f})")
