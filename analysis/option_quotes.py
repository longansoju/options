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
CACHE_S = 60
_cache: dict = {}


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


def chain_row(occ):
    """(bid, ask, last, volume, open interest) for one OCC contract from Yahoo, or None."""
    import yfinance as yf
    root, exp, kind, K = parse_occ(occ)
    key = (root, exp)
    hit = _cache.get(key)
    if not hit or time.time() - hit[0] > CACHE_S:
        for attempt in range(3):
            try:
                ch = yf.Ticker(root).option_chain(exp.isoformat()); break
            except Exception as e:
                err = e; time.sleep(2 * (attempt + 1))
        else:
            _cache[key] = (time.time(), None)   # remember the failure: no 5x retry storm while Yahoo rate-limits (429)
            return None
        _cache[key] = hit = (time.time(), ch)
    if hit[1] is None: return None
    df = hit[1].calls if kind == 'call' else hit[1].puts
    r = df[df.contractSymbol == occ]
    if not len(r): return None
    r = r.iloc[0]
    f = lambda c: float(r[c]) if pd.notna(r.get(c)) else 0.0
    return dict(bid=f('bid'), ask=f('ask'), last=f('lastPrice'), vol=f('volume'), oi=f('openInterest'))


def years_left(exp, now=None):
    """Time to the 16:00 ET close of the expiry day, in trading years (session minutes / 390 / 252)."""
    import numpy as np
    now = now or pd.Timestamp.now(tz='America/New_York')
    mins = min(max(16 * 60 - (now.hour * 60 + now.minute), 0), 390)
    days = int(np.busday_count(now.date(), exp))
    return max((mins / 390 + days) / 252, 1e-6)


def fill(occ, side, S_now, S_quote=None, rv=None, T=None, now=None):
    """Real-quote fill for ONE contract, $ per contract (x100). side = 'buy' (ask) or 'sell' (bid).
    S_now: live spot to re-price at; S_quote: spot when the (delayed) quote was made (default S_now).
    Returns dict(prem, raw, bid, ask, iv_ask, iv_bid, iv_rv, src, note) or None (no usable quote)."""
    try:
        q = chain_row(occ)
    except Exception:
        q = None
    if not q or q['bid'] <= 0 or q['ask'] <= 0 or q['ask'] < q['bid']: return None
    root, exp, kind, K = parse_occ(occ)
    T = T if T is not None else years_left(exp, now)
    Tq = T + DELAY_MIN / 390 / 252
    Sq = S_quote or S_now
    iv_a = implied_vol(q['ask'], Sq, K, Tq, kind); iv_b = implied_vol(q['bid'], Sq, K, Tq, kind)
    raw = q['ask'] if side == 'buy' else q['bid']
    iv = iv_a if side == 'buy' else iv_b
    if iv is None:   # quote at/under intrinsic or unsolvable: take the raw delayed price, shifted by intrinsic change
        intr = lambda s: max(s - K, 0) if kind == 'call' else max(K - s, 0)
        prem = max(raw + intr(S_now) - intr(Sq), intr(S_now) - (q['ask'] - q['bid']), 0.0)   # an ITM sale nets ~intrinsic less the spread
    else:
        prem = bs(S_now, K, T, iv, kind)
    ivr = (iv / rv) if (iv and rv) else None
    note = (f"REAL QUOTE yahoo ~{DELAY_MIN}m delayed: bid {q['bid']:.2f} / ask {q['ask']:.2f} (spot then {Sq:.2f}) | "
            f"IV ask {iv_a or 0:.2f} / bid {iv_b or 0:.2f}" + (f" = {ivr:.2f}x RV30 {rv:.0%}" if ivr else '') +
            f" | {side} @ {'ask' if side == 'buy' else 'bid'} re-priced to spot {S_now:.2f}: ${prem * 100:.0f}"
            f" | vol {q['vol']:.0f} OI {q['oi']:.0f}")
    return dict(prem=prem * 100, raw=raw * 100, bid=q['bid'], ask=q['ask'], iv_ask=iv_a, iv_bid=iv_b,
                iv=iv, iv_rv=ivr, src='yahoo_chain', note=note)


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
