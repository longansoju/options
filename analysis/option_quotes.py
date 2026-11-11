"""Real option quotes for PAPER FILLS (user 11-04: "buy at the ASK, sell at the BID").

Source: Yahoo's option chain via yfinance (needs fc.yahoo.com for the cookie/crumb). Quotes are ~15 min
DELAYED and Yahoo's own `impliedVolatility` column is unreliable (0.00001 on liquid puts, 11-04), so IV is
solved here from the quote itself.

How a fill is priced (`fill`):
  1. fetch the contract's bid/ask from the chain (cached per symbol+expiry for CACHE_S seconds);
  2. solve IV at the ask and at the bid against the spot AT THE QUOTE TIME (the 1m print ~DELAY_MIN ago,
     because the quote is that old - solving a stale quote against a live spot mis-reads the vol);
  3. re-price at the live spot: buy = BS(spot_now, IV_ask), sell = BS(spot_now, IV_bid).
  The raw delayed ask/bid is logged alongside. If there is no usable two-sided quote (bid <= 0, ask <= 0,
  crossed, chain error), returns None and the caller falls back to its Black-Scholes model price and
  flags the row `price_source=model (no quote)`.
Backtests stay model-priced; this module is for the live/paper engines only."""
import math, time, datetime as dt, warnings
import pandas as pd

warnings.filterwarnings('ignore')
DELAY_MIN = 15          # Yahoo option quotes ~15 min behind
CACHE_S = 60            # a chain younger than this is reused without a new request
STALE_S = 600           # 11-05: if a fresh fetch fails (Yahoo 429), a chain up to 10 min old beats the model fallback
_cache: dict = {}       # (root, expiry) -> (fetched_at, chain or None)
_good: dict = {}        # (root, expiry) -> (fetched_at, chain) last SUCCESSFUL fetch


def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, v, kind):
    T = max(T, 1e-7); v = max(v, 1e-4)
    d1 = (math.log(S / K) + v * v / 2 * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return S * N(d1) - K * N(d2) if kind == 'call' else K * N(-d2) - S * N(-d1)


def implied_vol(price, S, K, T, kind, lo=0.01, hi=6.0):
    """Bisection IV; None if the price is below intrinsic or above the hi-vol bound."""
    intrinsic = max(S - K, 0) if kind == 'call' else max(K - S, 0)
    if price <= intrinsic + 1e-6 or price >= bs(S, K, T, hi, kind): return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs(S, K, T, mid, kind) > price: hi = mid
        else: lo = mid
    return (lo + hi) / 2


def parse_occ(occ):
    root = occ[:-15]; d = dt.datetime.strptime(occ[-15:-9], '%y%m%d').date()
    return root, d, ('call' if occ[-9] == 'C' else 'put'), int(occ[-8:]) / 1000


def fetch_chain(root, exp, tries=3, wait=2.0):
    """Fetch one expiry's chain into the cache; returns the chain or None. Failures are remembered for CACHE_S
    so a burst of lookups does not hammer a rate-limited Yahoo."""
    import yfinance as yf
    key = (root, exp)
    for attempt in range(tries):
        try:
            ch = yf.Ticker(root).option_chain(exp.isoformat())
            _cache[key] = _good[key] = (time.time(), ch); return ch
        except Exception:
            if attempt < tries - 1: time.sleep(wait * (attempt + 1))
    _cache[key] = (time.time(), None)
    return None


def prefetch(root, exp, min_age=240):
    """Warm the cache for a likely signal (day-trade engine, 11-05). One request at most; skipped if a good chain
    is younger than min_age seconds or a failure was cached in the last CACHE_S. Returns True if a chain is cached."""
    key = (root, exp); g = _good.get(key); c = _cache.get(key)
    if g and time.time() - g[0] < min_age: return True
    if c and c[1] is None and time.time() - c[0] < CACHE_S: return bool(g and time.time() - g[0] < STALE_S)
    return fetch_chain(root, exp, tries=1) is not None


def chain_age(root, exp):
    """Seconds since the chain used for this expiry was fetched (None if none usable)."""
    g = _good.get((root, exp))
    return time.time() - g[0] if g and time.time() - g[0] < STALE_S else None


def snap(root, exp, K, side=None):
    """Nearest LISTED strike for this expiry (11-05: the engines' price-step grid invented strikes - NVDA 194,
    NBIS 131/133, SMCI 27.5 do not exist; NBIS261120P00133000 was booked 11-04 and could never have filled).
    side='up' -> nearest listed strike >= K (OTM call), 'down' -> <= K (OTM put). Returns K unchanged if no chain."""
    key = (root, exp); g = _good.get(key)
    if not g or time.time() - g[0] > STALE_S:
        if not fetch_chain(root, exp, tries=2): return K
        g = _good[key]
    st = sorted(set(g[1].calls.strike) | set(g[1].puts.strike))
    if not st: return K
    if side == 'up':
        up = [x for x in st if x >= K - 1e-9]; return float(up[0]) if up else float(st[-1])
    if side == 'down':
        dn = [x for x in st if x <= K + 1e-9]; return float(dn[-1]) if dn else float(st[0])
    return float(min(st, key=lambda x: abs(x - K)))


def chain_row(occ, patient=False):
    """(bid, ask, last, volume, open interest, age_s) for one OCC contract from Yahoo, or None.
    Uses a fresh chain (< CACHE_S), else fetches; if the fetch fails, falls back to the last good chain < STALE_S old.
    patient=True (15:50 engines): retry for up to ~60 s before giving up."""
    root, exp, kind, K = parse_occ(occ)
    key = (root, exp)
    hit = _cache.get(key)
    if not hit or time.time() - hit[0] > CACHE_S:
        fetch_chain(root, exp, tries=6 if patient else 3, wait=4.0 if patient else 2.0)
    g = _good.get(key)
    if not g or time.time() - g[0] > STALE_S: return None
    hit = g
    df = hit[1].calls if kind == 'call' else hit[1].puts
    r = df[df.contractSymbol == occ]
    if not len(r): return None
    r = r.iloc[0]
    f = lambda c: float(r[c]) if pd.notna(r.get(c)) else 0.0
    return dict(bid=f('bid'), ask=f('ask'), last=f('lastPrice'), vol=f('volume'), oi=f('openInterest'), age=time.time() - hit[0])


def years_left(exp, now=None):
    """Time to the 16:00 ET close of the expiry day, in trading years (session minutes / 390 / 252)."""
    import numpy as np
    now = now or pd.Timestamp.now(tz='America/New_York')
    mins = min(max(16 * 60 - (now.hour * 60 + now.minute), 0), 390)
    days = int(np.busday_count(now.date(), exp))
    return max((mins / 390 + days) / 252, 1e-6)


import os as _os
QUOTE_LOG = _os.environ.get('OPT_QUOTE_LOG', '/home/user/options/data/quote_log.csv')   # 11-10: structured log of every real quote used
# (spread-filter test data). 11-11: the intraday engine sets OPT_QUOTE_LOG to a scratchpad file; its rows are appended to the repo log at the 15:50 booking.


def _log_quote(occ, side, q, Sq, S_now, iv_a, iv_b, rv, lag):
    """Append one row per real quote the engines price a fill from. Never raises."""
    try:
        import os, csv
        new = not os.path.exists(QUOTE_LOG)
        mid = (q['ask'] + q['bid']) / 2
        with open(QUOTE_LOG, 'a', newline='') as fh:
            w = csv.writer(fh)
            if new: w.writerow(['logged_utc', 'occ', 'side', 'bid', 'ask', 'spread_pct_mid', 'iv_ask', 'iv_bid', 'rv30',
                                'spot_at_quote', 'spot_now', 'quote_age_min', 'volume', 'open_interest'])
            w.writerow([pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%dT%H:%M:%SZ'), occ, side, q['bid'], q['ask'],
                        round((q['ask'] - q['bid']) / mid, 4) if mid else '', round(iv_a or 0, 4), round(iv_b or 0, 4),
                        round(rv or 0, 4), round(Sq, 4), round(S_now, 4), round(lag, 1), q['vol'], q['oi']])
    except Exception:
        pass


def fill(occ, side, S_now, S_quote=None, rv=None, T=None, now=None, patient=False, spot_at_age=None):
    """Real-quote fill for ONE contract, $ per contract (x100). side = 'buy' (ask) or 'sell' (bid).
    S_now: live spot to re-price at; S_quote: spot when the (delayed) quote was made (default S_now).
    spot_at_age(minutes) -> spot that many minutes ago; used when the chain is a cached one (fetch failed), so the IV is
    solved against the spot when THAT quote was made (age + DELAY_MIN), not the spot 15 min ago.
    Returns dict(prem, raw, bid, ask, iv_ask, iv_bid, iv_rv, src, note) or None (no usable quote)."""
    try:
        q = chain_row(occ, patient=patient)
    except Exception:
        q = None
    if not q or q['bid'] <= 0 or q['ask'] <= 0 or q['ask'] < q['bid']: return None
    root, exp, kind, K = parse_occ(occ)
    T = T if T is not None else years_left(exp, now)
    lag = DELAY_MIN + q['age'] / 60
    Tq = T + lag / 390 / 252
    Sq = S_quote or S_now
    if q['age'] > CACHE_S and spot_at_age is not None:
        try: Sq = spot_at_age(lag) or Sq
        except Exception: pass
    iv_a = implied_vol(q['ask'], Sq, K, Tq, kind); iv_b = implied_vol(q['bid'], Sq, K, Tq, kind)
    raw = q['ask'] if side == 'buy' else q['bid']
    iv = iv_a if side == 'buy' else iv_b
    if iv is None:   # quote at/under intrinsic or unsolvable: take the raw delayed price, shifted by intrinsic change
        intr = lambda s: max(s - K, 0) if kind == 'call' else max(K - s, 0)
        prem = max(raw + intr(S_now) - intr(Sq), intr(S_now) - (q['ask'] - q['bid']), 0.0)   # an ITM sale nets ~intrinsic less the spread
    else:
        prem = bs(S_now, K, T, iv, kind)
    ivr = (iv / rv) if (iv and rv) else None
    note = (f"REAL QUOTE yahoo ~{lag:.0f}m old{' (cached chain - fresh fetch failed)' if q['age'] > CACHE_S else ''}: bid {q['bid']:.2f} / ask {q['ask']:.2f} (spot then {Sq:.2f}) | "
            f"IV ask {iv_a or 0:.2f} / bid {iv_b or 0:.2f}" + (f" = {ivr:.2f}x RV30 {rv:.0%}" if ivr else '') +
            f" | {side} @ {'ask' if side == 'buy' else 'bid'} re-priced to spot {S_now:.2f}: ${prem * 100:.0f}"
            f" | vol {q['vol']:.0f} OI {q['oi']:.0f}")
    _log_quote(occ, side, q, Sq, S_now, iv_a, iv_b, rv, lag)
    return dict(prem=prem * 100, raw=raw * 100, bid=q['bid'], ask=q['ask'], iv_ask=iv_a, iv_bid=iv_b,
                iv=iv, iv_rv=ivr, src='yahoo_chain', note=note, age_min=lag,
                spread=(q['ask'] - q['bid']) / ((q['ask'] + q['bid']) / 2))


def spot_at(symbol, minutes_ago=DELAY_MIN):
    """Regular-session 1m close ~minutes_ago (the spot the delayed quote was made against)."""
    from analysis import event_radar as er
    m = er.fetch_chart(symbol, '1m', '1d').dropna()
    m = m[(m.index.time >= dt.time(9, 30)) & (m.index.time < dt.time(16, 0))]
    if not len(m): return None
    cut = pd.Timestamp.now(tz=m.index.tz) - pd.Timedelta(minutes=minutes_ago)
    sub = m[m.index <= cut]
    return float((sub if len(sub) else m).C.iloc[-1])


if __name__ == '__main__':
    import sys
    for occ in sys.argv[1:]:
        print(occ, chain_row(occ))
