"""Event & volatility radar — predicts WHEN a big move is likely, not which way.

Built 2026-09-27 after two misses the user flagged: MRVL's +5.8% overnight gap
after the 2026-09-16 FOMC decision, and MU's +53% opening call spike on
2026-09-25. Two models, both validated walk-forward (every test period is
scored by a model fitted only on earlier data):

  overnight  scored at the close: P(next open gaps up by > 1 gap-sd) and
             P(gaps down by > 1 gap-sd).
             10y x 21 names, OOS 2019-2026: AUC 0.597 (up) / 0.578 (down).
  open       scored pre-open (~09:25 ET) from pre-market: P(a 0.3-sigma weekly
             call / put bought at the open touches +50% in the first hour).
             2y hourly x 21 names, OOS 2024-07..2026-09: AUC 0.585 (call) /
             0.612 (put). Top decile touches 36% / 42% vs a 25% base rate.

What it CANNOT do, stated so nobody rebuilds it expecting otherwise: predict
DIRECTION. The open model's "which side wins" AUC is 0.514; the overnight
expected-gap rank-IC is +0.022 and flips sign by year. Big-move days are
forecastable; which way they break is not. A lean is reported only with that
caveat. Use the radar to decide where to stand ready with a resting +50% limit
and when not to open fresh short-dated premium into the open.

Pricing caveat: touch labels are Black-Scholes at RV30. On exactly the nights
the overnight model flags, realized gaps run ~1.28x what RV30 implies — the
real market prices part of that in, so model option P&L on flagged nights is
optimistic. Probabilities of the UNDERLYING move are not affected.

FOMC: over 2024-26 the night after a decision averaged +1.22% for these names
(73% up, n=22) vs +0.22% on normal nights (p~0.002 vs random nights). Over
2017-23 there was no effect (n=40). Regime-dependent — flagged, not a rule.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import time

import numpy as np
import pandas as pd
import requests

import config

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "models", "event_radar.json")

# Published FOMC decision dates. 2026 Oct/Dec are from the Fed's announced
# schedule — re-verify if the Fed changes it.
FOMC_DATES = frozenset(pd.to_datetime("""
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-03-03 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16 2026-10-28 2026-12-09
""".split()).date)

OVERNIGHT_FEATURES = ["z_r1", "z_gap", "z_id", "clv", "z_rng", "z_r3", "z_r5", "z_r10", "ma20",
                      "ma50", "volx", "smh_r1", "smh_clv", "rel_r1", "qqq_r1", "fomc", "fri"]
# z_open_vs_pm is deliberately absent: it needs the opening print, and this
# model has to be scoreable BEFORE the open.
OPEN_FEATURES = ["z_gap", "z_pm1h", "z_pmearly", "z_relgap", "clv", "z_r1", "z_r3", "z_r5",
                 "hi20", "lo20", "volx", "ma50", "fomc_prev", "mon", "rv"]


# --------------------------------------------------------------------------- data

def fetch_chart(symbol: str, interval: str, rng: str, prepost: bool = False) -> pd.DataFrame:
    """Yahoo chart API, ET-indexed OHLCV. Same retry policy as the provider."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval={interval}&range={rng}&includePrePost={'true' if prepost else 'false'}")
    for attempt in range(config.YF_MAX_RETRIES + 1):
        time.sleep(config.YF_INTER_CALL_DELAY if attempt == 0 else
                   config.YF_INTER_CALL_DELAY * config.YF_RETRY_BACKOFF ** attempt)
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame({"O": q["open"], "H": q["high"], "L": q["low"], "C": q["close"],
                               "V": q["volume"]},
                              index=pd.to_datetime(res["timestamp"], unit="s", utc=True)
                              .tz_convert("America/New_York"))
            return df.dropna(subset=["C"])
        except Exception:
            if attempt == config.YF_MAX_RETRIES:
                raise
    raise RuntimeError(symbol)


def daily_frame(symbol: str, rng: str = "10y") -> pd.DataFrame:
    """Daily bars, with the last sessions rebuilt from intraday regular-session
    bars — the daily feed has repeatedly lagged by 1-2 sessions."""
    d = fetch_chart(symbol, "1d", rng)
    d.index = d.index.date
    d = d[~d.index.duplicated(keep="last")]
    m = fetch_chart(symbol, "5m", "5d")
    m = m[(m.index.time >= dt.time(9, 30)) & (m.index.time < dt.time(16, 0))]
    for day, g in m.groupby(m.index.date):
        d.loc[day] = [float(g.O.iloc[0]), float(g.H.max()), float(g.L.min()),
                      float(g.C.iloc[-1]), float(g.V.sum())]
    return d.sort_index()


# ------------------------------------------------------------------- math utils

def _norm_cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x, float) / math.sqrt(2)))


def _bs(S, K, T, v, call: bool):
    S, K, T, v = (np.asarray(a, float) for a in (S, K, T, v))
    d1 = (np.log(S / K) + (v * v / 2) * T) / (v * np.sqrt(T))
    d2 = d1 - v * np.sqrt(T)
    if call:
        return S * _norm_cdf(d1) - K * _norm_cdf(d2)
    return K * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _logit_fit(X: np.ndarray, y: np.ndarray, l2: float) -> np.ndarray:
    """IRLS logistic regression, L2 on everything but the intercept."""
    X = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(X.shape[1])
    pen = np.eye(X.shape[1]) * l2
    pen[0, 0] = 0
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ w))
        step = np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X + pen, X.T @ (y - p) - pen @ w)
        w += step
        if np.abs(step).max() < 1e-7:
            break
    return w


def _logit_pred(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(np.column_stack([np.ones(len(X)), X]) @ w)))


def _auc(y, s) -> float:
    y = np.asarray(y, bool)
    r = pd.Series(np.asarray(s, float)).rank().values
    n1, n0 = y.sum(), (~y).sum()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")


# ------------------------------------------------------------- feature builders

def overnight_features(d: pd.DataFrame, smh: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    """One row per session; every feature is known at that session's close.
    Targets (gap_next, big_up, big_dn) are NaN on the last row."""
    c, o, h, l, v = d.C, d.O, d.H, d.L, d.V
    r = c.pct_change()
    sd = r.rolling(20).std()
    gap = o / c.shift(1) - 1
    f = pd.DataFrame(index=d.index)
    f["C"], f["sd"] = c, sd
    f["gsd"] = gap.rolling(60).std()
    f["rv"] = r.rolling(30).std() * math.sqrt(252)
    f["z_r1"] = r / sd
    f["z_gap"] = gap / sd
    f["z_id"] = (c / o - 1) / sd
    f["clv"] = ((c - l) / (h - l)).where(h > l, 0.5)
    f["z_rng"] = ((h - l) / c) / sd
    for n in (3, 5, 10):
        f[f"z_r{n}"] = (c / c.shift(n) - 1) / (sd * math.sqrt(n))
    f["ma20"] = (c / c.rolling(20).mean() - 1) / sd
    f["ma50"] = (c / c.rolling(50).mean() - 1) / sd
    with np.errstate(divide="ignore"):
        f["volx"] = np.log(v / v.rolling(20).mean()).replace([np.inf, -np.inf], np.nan)
    sm, qq = smh.reindex(d.index), qqq.reindex(d.index)
    f["smh_r1"] = sm.C.pct_change() / sm.C.pct_change().rolling(20).std()
    f["smh_clv"] = ((sm.C - sm.L) / (sm.H - sm.L)).where(sm.H > sm.L, 0.5)
    f["rel_r1"] = f.z_r1 - f.smh_r1
    f["qqq_r1"] = qq.C.pct_change() / qq.C.pct_change().rolling(20).std()
    f["fomc"] = [x in FOMC_DATES for x in d.index]
    f["fri"] = [x.weekday() == 4 for x in d.index]
    f["gap_next"] = gap.shift(-1)
    f["big_up"] = f.gap_next > f.gsd
    f["big_dn"] = f.gap_next < -f.gsd
    return f


def _premarket_table(h: pd.DataFrame) -> pd.DataFrame:
    """Per-day pre-market snapshot + first regular hour. Pre-market uses bar
    CLOSES only — pre-market highs/lows carry junk prints."""
    rows = {}
    for day, g in h.groupby(h.index.date):
        t = g.index.time
        pm = g[t < dt.time(9, 30)]
        reg = g[(t >= dt.time(9, 30)) & (t < dt.time(16, 0))]
        first = reg[reg.index.time == dt.time(9, 30)]

        def pm_at(hh):
            x = pm[pm.index.time == dt.time(hh, 0)]
            return float(x.C.iloc[0]) if len(x) else np.nan

        rows[day] = dict(pm_last=float(pm.C.iloc[-1]) if len(pm) else np.nan,
                         pm_08=pm_at(8), pm_04=pm_at(4),
                         O=float(first.O.iloc[0]) if len(first) else np.nan,
                         H1=float(first.H.iloc[0]) if len(first) else np.nan,
                         L1=float(first.L.iloc[0]) if len(first) else np.nan,
                         Creg=float(reg.C.iloc[-1]) if len(reg) >= 6 else np.nan)
    p = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    p["prevC"] = p.Creg.shift(1).ffill()
    return p


def open_features(h: pd.DataFrame, d: pd.DataFrame, smh_h: pd.DataFrame) -> pd.DataFrame:
    """One row per day; features known before 09:30 ET. Targets need the first
    regular hour, so they are NaN for a day scored pre-open."""
    p = _premarket_table(h)
    c, hi, lo, v = d.C, d.H, d.L, d.V
    r = c.pct_change()
    sd = r.rolling(20).std()
    daily = pd.DataFrame({
        "sd": sd, "rv": r.rolling(30).std() * math.sqrt(252),
        "clv": ((c - lo) / (hi - lo)).where(hi > lo, 0.5), "z_r1": r / sd,
        "z_r3": (c / c.shift(3) - 1) / (sd * math.sqrt(3)),
        "z_r5": (c / c.shift(5) - 1) / (sd * math.sqrt(5)),
        "hi20": (hi.rolling(20).max() / c - 1) / sd, "lo20": (1 - lo.rolling(20).min() / c) / sd,
        "volx": np.log(v / v.rolling(20).mean()).replace([np.inf, -np.inf], np.nan),
        "ma50": (c / c.rolling(50).mean() - 1) / sd,
    })
    daily["fomc_prev"] = [float(x in FOMC_DATES) for x in daily.index]
    # every daily feature must come from the session BEFORE the scored day
    left = pd.DataFrame({"day": pd.to_datetime(p.index)}).reset_index(drop=True)
    right = daily.copy()
    right["day"] = pd.to_datetime(right.index)
    prev = pd.merge_asof(left, right.sort_values("day"), on="day", allow_exact_matches=False)
    prev.index = p.index
    p = p.join(prev.drop(columns="day"))
    sp = _premarket_table(smh_h)
    p["z_gap"] = (p.pm_last / p.prevC - 1) / p.sd
    p["z_pm1h"] = (p.pm_last / p.pm_08 - 1) / p.sd
    p["z_pmearly"] = (p.pm_08 / p.pm_04 - 1) / p.sd
    p["z_relgap"] = p.z_gap - (sp.pm_last / sp.prevC - 1).reindex(p.index) / p.sd
    p["mon"] = [x.weekday() == 0 for x in p.index]
    # targets: 0.3-sigma weekly call/put bought at the open, valued at the
    # first-hour extreme (at ~10:00 time-to-expiry)
    ses = np.array([5 if x.weekday() == 4 else 4 - x.weekday() for x in p.index])
    T0, T1 = (1 + ses) / 252, (360 / 390 + ses) / 252
    sdT = p.rv.values * np.sqrt(T0)
    Kc, Kp = p.O.values * np.exp(0.3 * sdT), p.O.values * np.exp(-0.3 * sdT)
    with np.errstate(all="ignore"):
        p["call_peak"] = _bs(p.H1, Kc, T1, p.rv, True) / _bs(p.O, Kc, T0, p.rv, True) - 1
        p["put_peak"] = _bs(p.L1, Kp, T1, p.rv, False) / _bs(p.O, Kp, T0, p.rv, False) - 1
    p["call_touch"] = p.call_peak >= 0.5
    p["put_touch"] = p.put_peak >= 0.5
    p["up_wins"] = (p.H1 / p.O - 1) > (1 - p.L1 / p.O)
    return p


# ----------------------------------------------------------------- fit / score

def _fit_target(df: pd.DataFrame, feats: list[str], target: str, period: pd.Series,
                min_train_periods: int, l2: float) -> dict:
    """Walk-forward OOS evaluation, then a final fit on everything."""
    X = df[feats].astype(float).values
    y = df[target].astype(float).values
    oos = np.full(len(df), np.nan)
    periods = sorted(period.unique())
    for i, per in enumerate(periods):
        if i < min_train_periods:
            continue
        tr, te = (period < per).values, (period == per).values
        mu, s = X[tr].mean(0), X[tr].std(0) + 1e-9
        oos[te] = _logit_pred(_logit_fit((X[tr] - mu) / s, y[tr], l2), (X[te] - mu) / s)
    m = ~np.isnan(oos)
    mu, s = X.mean(0), X.std(0) + 1e-9
    w = _logit_fit((X - mu) / s, y, l2)
    top = oos[m] >= np.quantile(oos[m], 0.9)
    return {"coef": w.tolist(), "mu": mu.tolist(), "sd": s.tolist(),
            "oos_auc": _auc(y[m] > 0.5, oos[m]), "oos_n": int(m.sum()),
            "base_rate": float(y[m].mean()), "top_decile_rate": float(y[m][top].mean()),
            "oos_deciles": np.quantile(oos[m], np.linspace(0.1, 0.9, 9)).tolist()}


def fit(symbols: list[str] | None = None, path: str = MODEL_PATH, verbose: bool = True) -> dict:
    """Fetch history, validate walk-forward, fit, and save coefficients as JSON."""
    symbols = symbols or config.FOCUS_AI_SEMI_IT
    smh_d, qqq_d = daily_frame("SMH"), daily_frame("QQQ")
    smh_h = fetch_chart("SMH", "1h", "730d", prepost=True)
    ov, op = [], []
    for sym in symbols:
        if verbose:
            print(f"  fetching {sym}...", flush=True)
        d = daily_frame(sym)
        f = overnight_features(d, smh_d, qqq_d)
        f["sym"] = sym
        ov.append(f.iloc[:-1])                      # last row has no target yet
        p = open_features(fetch_chart(sym, "1h", "730d", prepost=True), d, smh_h)
        p["sym"] = sym
        op.append(p)
    ov = pd.concat(ov).replace([np.inf, -np.inf], np.nan).dropna(subset=OVERNIGHT_FEATURES + ["gap_next", "gsd"])
    op = pd.concat(op).replace([np.inf, -np.inf], np.nan).dropna(subset=OPEN_FEATURES + ["call_peak", "put_peak"])
    year = pd.Series([x.year for x in ov.index], index=ov.index)
    quarter = pd.Series([f"{x.year}Q{(x.month - 1) // 3 + 1}" for x in op.index], index=op.index)
    model = {
        "fit_date": str(dt.date.today()), "symbols": symbols,
        "overnight": {"features": OVERNIGHT_FEATURES, "n": len(ov),
                      "big_up": _fit_target(ov, OVERNIGHT_FEATURES, "big_up", year, 2, 10.0),
                      "big_dn": _fit_target(ov, OVERNIGHT_FEATURES, "big_dn", year, 2, 10.0)},
        "open": {"features": OPEN_FEATURES, "n": len(op),
                 "call_touch": _fit_target(op, OPEN_FEATURES, "call_touch", quarter, 3, 20.0),
                 "put_touch": _fit_target(op, OPEN_FEATURES, "put_touch", quarter, 3, 20.0),
                 "up_wins": _fit_target(op, OPEN_FEATURES, "up_wins", quarter, 3, 20.0)},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(model, fh, indent=1)
    return model


def load(path: str = MODEL_PATH) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _score(block: dict, feats: list[str], row: pd.Series) -> tuple[float, int]:
    x = (row[feats].astype(float).values - np.array(block["mu"])) / np.array(block["sd"])
    p = float(_logit_pred(np.array(block["coef"]), x[None, :])[0])
    decile = int(np.searchsorted(block["oos_deciles"], p)) + 1        # 1..10
    return p, decile


def score_overnight(symbols: list[str] | None = None, model: dict | None = None) -> pd.DataFrame:
    """Score the most recent session. Run near the close — an intraday run uses
    the day so far (volume understated, close = current price)."""
    model = model or load()
    symbols = symbols or model["symbols"]
    smh_d, qqq_d = daily_frame("SMH", "1y"), daily_frame("QQQ", "1y")
    out = []
    for sym in symbols:
        f = overnight_features(daily_frame(sym, "1y"), smh_d, qqq_d).iloc[-1]
        if f[OVERNIGHT_FEATURES].astype(float).isna().any():
            continue
        pu, du = _score(model["overnight"]["big_up"], OVERNIGHT_FEATURES, f)
        pdn, dd = _score(model["overnight"]["big_dn"], OVERNIGHT_FEATURES, f)
        out.append(dict(sym=sym, session=str(f.name), price=f.C, p_gap_up=pu, dec_up=du,
                        p_gap_dn=pdn, dec_dn=dd, fomc=bool(f.fomc), one_gap_sd_pct=f.gsd * 100))
    return pd.DataFrame(out).sort_values("p_gap_up", ascending=False, ignore_index=True) if out else pd.DataFrame()


def score_open(symbols: list[str] | None = None, model: dict | None = None) -> pd.DataFrame:
    """Score today's open from pre-market. Best run 09:15-09:28 ET (21:15-21:28 SGT)."""
    model = model or load()
    symbols = symbols or model["symbols"]
    smh_h = fetch_chart("SMH", "1h", "5d", prepost=True)
    out = []
    for sym in symbols:
        p = open_features(fetch_chart(sym, "1h", "5d", prepost=True), daily_frame(sym, "1y"), smh_h)
        row = p.iloc[-1]
        if row[OPEN_FEATURES].astype(float).isna().any():
            continue
        pc, dc = _score(model["open"]["call_touch"], OPEN_FEATURES, row)
        pp, dp = _score(model["open"]["put_touch"], OPEN_FEATURES, row)
        pu, _ = _score(model["open"]["up_wins"], OPEN_FEATURES, row)
        out.append(dict(sym=sym, day=str(row.name), pm_last=row.pm_last,
                        gap_pct=(row.pm_last / row.prevC - 1) * 100,
                        p_call50=pc, dec_call=dc, p_put50=pp, dec_put=dp,
                        # call and put touches almost never share a first hour
                        # (2% of days), so P(either) is close to the sum
                        p_spike=min(pc + pp, 1.0), lean_up=pu, fomc_yday=bool(row.fomc_prev)))
    return pd.DataFrame(out).sort_values("p_spike", ascending=False, ignore_index=True) if out else pd.DataFrame()
