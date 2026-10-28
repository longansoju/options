"""User 10-28: "MU had already been rising 2 days straight" before the 10-27 close (MU 960C).
Is a multi-day up-streak a signal to buy calls at the close? Daily bars, 2y, day-trade universe.
Streak = N consecutive up closes. Outcome: next open gap, next close, 3-day; and a 0.2-sigma
call two Fridays out bought at the streak close, sold at the next close (BS at RV30, 4% friction).
IS = first half of dates, OOS = second half."""
import sys, math, datetime as dt, warnings
warnings.filterwarnings('ignore'); sys.path.insert(0, '/home/user/options')
import numpy as np, pandas as pd, config
from analysis import event_radar as er
config.YF_INTER_CALL_DELAY = 0.15


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def call(S, K, T, v):
    T = max(T, 1e-6); d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); return S * N(d1) - K * N(d1 - v * math.sqrt(T))


rows = []
for s in config.FOCUS_AI_SEMI_IT + config.DAYTRADE_EXPANSION:
    d = er.daily_frame(s, '2y').dropna(); c = d.C; r = c.pct_change()
    up = (r > 0).astype(int); streak = up.groupby((up == 0).cumsum()).cumsum()
    rv = r.rolling(30).std() * math.sqrt(252); ma20 = c.rolling(20).mean()
    for i in range(60, len(d) - 4):
        S, v = c.iloc[i], rv.iloc[i]; day = pd.Timestamp(d.index[i]).date()
        exp = day + dt.timedelta(days=(4 - day.weekday()) % 7 + 14); bd = np.busday_count(day, exp)
        K = S * math.exp(0.2 * v * math.sqrt(bd / 252)); p0 = call(S, K, bd / 252, v)
        p1 = call(c.iloc[i + 1], K, (bd - 1) / 252, v)
        rows.append(dict(sym=s, day=day, streak=int(streak.iloc[i]), r3=c.iloc[i] / c.iloc[i - 3] - 1, below20=S < ma20.iloc[i],
                         gap=d.O.iloc[i + 1] / S - 1, nc=c.iloc[i + 1] / S - 1, n3=c.iloc[i + 3] / S - 1, opt=p1 / p0 - 1 - 0.04))
R = pd.DataFrame(rows); cut = sorted(R.day.unique())[len(R.day.unique()) // 2]


def show(name, t):
    i, o = t[t.day < cut], t[t.day >= cut]
    print(f"{name:42s} n={len(t):5d} gap {t.gap.mean():+.2%} up-open {(t.gap > 0).mean():.0%} | next close {t.nc.mean():+.2%} "
          f"up {(t.nc > 0).mean():.0%} | 3d {t.n3.mean():+.2%} | call 1d {t.opt.mean():+.1%} (IS {i.opt.mean():+.1%} / OOS {o.opt.mean():+.1%})")


show('all days', R)
for k in (2, 3, 4): show(f'up-streak >= {k} days', R[R.streak >= k])
show('streak >= 3, below 20d MA (bounce, like MU)', R[(R.streak >= 3) & R.below20])
show('streak >= 3 AND 3d >= +5%', R[(R.streak >= 3) & (R.r3 >= .05)])
show('MU only, streak >= 3', R[(R.sym == 'MU') & (R.streak >= 3)])
