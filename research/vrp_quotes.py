"""User 11-24: "pause the day trades ... find out better ways to improve our strategy".
Every strategy here BUYS options, so the single number that decides whether it can win is the price paid: implied vol at
the ask versus the volatility the stock then actually delivered. data/quote_log.csv holds every real Yahoo quote the engines
fetched since 11-10 (3,373). PRE-SPECIFIED questions:
  Q1  Over the life of the quote's window, was IV at the ask above or below the realized vol that followed?
      (forward RV from 5m closes, quote time -> min(expiry, +5 sessions), overnight gaps included, same trading-time clock
      as the engines' T).  ratio = IV_ask / RV_forward ; < 1 = the option was cheap, > 1 = dear.
  Q2  Does the gate we use (IV_ask / RV30 at the quote) predict that ratio? (rank correlation + buckets)
  Q3  Which names / expiry buckets were cheap or dear?
Caveat fixed in advance: one month, a crash-and-rebound tape (forward RV was high), 1 quote ~ 1 decision, quotes on the same
name and day are not independent - read buckets by distinct name-days, not raw counts.
  python research/vrp_quotes.py"""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd
from analysis import event_radar as er

q = pd.read_csv('/home/user/options/data/quote_log.csv')
m = q.occ.str.extract(r'^([A-Z]+)(\d{6})([CP])(\d{8})$')
q['root'], q['cp'], q['K'] = m[0], m[2], m[3].astype(float) / 1000
q['exp'] = pd.to_datetime(m[1], format='%y%m%d').dt.date
q['t'] = pd.to_datetime(q.logged_utc).dt.tz_convert('America/New_York')
q = q[(q.iv_ask > 0) & (q.rv30 > 0)].drop_duplicates(['occ', 'logged_utc'])
bars = {}
for s in q.root.unique():
    try:
        b = er.fetch_chart(s, '5m', '60d'); bars[s] = b[(b.index.time >= dt.time(9, 30)) & (b.index.time < dt.time(16, 0))].C.dropna()
    except Exception as e:
        print('skip', s, e)
rows = []
for r in q.itertuples():
    b = bars.get(r.root)
    if b is None: continue
    days = sorted(set(b.index.date)); d0 = r.t.date()
    fut = [d for d in days if d >= d0]
    end_day = min([d for d in fut if d <= r.exp][:6][-1:] or [d0])
    w = b[(b.index >= r.t) & (b.index.date <= end_day)]
    if len(w) < 30: continue                                            # need >= ~2.5 hours of forward bars
    lr = np.log(w / w.shift()).dropna()
    T = len(lr) * 5 / 390 / 252
    rvf = math.sqrt((lr ** 2).sum() / T)
    dte = (r.exp - d0).days
    rows.append(dict(root=r.root, day=d0, cp=r.cp, dte=dte, iv_ask=r.iv_ask, iv_bid=r.iv_bid, rv30=r.rv30, rvf=rvf,
                     spread=r.spread_pct_mid, gate=r.iv_ask / r.rv30, ratio=r.iv_ask / rvf, sess=len(set(w.index.date))))
D = pd.DataFrame(rows)
D['nd'] = D.root + D.day.astype(str)
def line(lab, x):
    print(f"  {lab:34s} quotes {len(x):5d}  name-days {x.nd.nunique():4d}  median IV_ask/RV_fwd {x.ratio.median():.2f}  "
          f"cheap (<1) {(x.ratio < 1).mean():4.0%}  | median IV_ask/RV30 {x.gate.median():.2f}")
print(f"quotes scored {len(D)} of {len(q)} | {D.day.min()} .. {D.day.max()} | forward window median {D.sess.median():.0f} sessions\n")
print('Q1  all quotes'); line('all', D)
for lab, mk in (('same day (0 DTE)', D.dte == 0), ('1-6 days', (D.dte >= 1) & (D.dte <= 6)), ('7-13 days', (D.dte >= 7) & (D.dte <= 13)),
                ('14+ days', D.dte >= 14)):
    line(lab, D[mk])
for lab, mk in (('calls', D.cp == 'C'), ('puts', D.cp == 'P')): line(lab, D[mk])
print('\nQ2  does our gate (IV_ask / RV30 at the quote) predict cheapness?')
print(f"  rank correlation gate vs IV_ask/RV_fwd: {D[['gate', 'ratio']].corr('spearman').iloc[0, 1]:+.2f}")
for lab, mk in (('gate <= 0.90', D.gate <= .9), ('0.90-1.10', (D.gate > .9) & (D.gate <= 1.1)), ('1.10-1.30', (D.gate > 1.1) & (D.gate <= 1.3)),
                ('> 1.30', D.gate > 1.3)):
    line(lab, D[mk])
print('\nQ3  by name (median IV_ask / RV_fwd; < 1 = options were cheap vs what the stock then did)')
g = D.groupby('root').agg(q=('ratio', 'size'), nd=('nd', 'nunique'), ratio=('ratio', 'median'), gate=('gate', 'median'), rvf=('rvf', 'median'), rv30=('rv30', 'median'))
print(g.sort_values('ratio').round(2).to_string())
print('\nby quote day (all names) - the regime check')
print(D.groupby('day').agg(q=('ratio', 'size'), ratio=('ratio', 'median'), gate=('gate', 'median')).round(2).to_string())
