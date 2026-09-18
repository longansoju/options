"""Validated entry gates and exit-rule evaluation.

Scope note: an earlier version of this module tried to replace P(ITM) with a
"probability the premium spikes enough to harvest" metric, on the theory that
P(ITM) asks the wrong question for a trader who always sells before expiry.
It was backtested against the 26 labelled trades in data/recommendations.csv
and REJECTED — AUC 0.525 against P(ITM)'s 0.767. It systematically overscored
cheap far-OTM contracts on volatile names (VST C190 scored 0.418 and lost
100%), because a low entry premium makes +50% cheap to touch and high vol
makes it touchable in either direction. Do not rebuild it without new evidence.

What survived validation is here: the whipsaw gate, and the exit rules.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def bs(spot: float, strike: float, t_years: float, vol: float, kind: str,
       r: float = 0.04) -> float:
    t = max(float(t_years), 1e-6)
    vs = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / vs
    d2 = d1 - vs
    disc = strike * math.exp(-r * t)
    if kind == "call":
        return spot * _norm_cdf(d1) - disc * _norm_cdf(d2)
    return disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def prob_itm(spot: float, strike: float, t_years: float, vol: float, kind: str,
             r: float = 0.04) -> float:
    """Kept as the primary discrimination metric: AUC 0.767 on the book."""
    t = max(float(t_years), 1e-6)
    vs = vol * math.sqrt(t)
    d2 = (math.log(spot / strike) + (r - vol * vol / 2) * t) / vs
    return _norm_cdf(d2) if kind == "call" else _norm_cdf(-d2)


def whipsaw_stats(close: pd.Series, lookback: int = 30) -> dict:
    """Validated gate: of 26 book trades it flags 6, and ALL SIX lost
    (avg -64.0%). Survivors won 30% at -7.2% avg. It also lifts P(ITM)'s
    discrimination among survivors from AUC 0.767 to 0.833.
    """
    ret = close.pct_change().dropna() * 100
    win = ret.tail(lookback)
    up, down = int((win > 5).sum()), int((win < -5).sum())
    c = close.values
    rallies = sum(
        1 for i in range(max(0, len(c) - 40), len(c) - 5)
        if c[i:i + 5].max() / c[i] - 1 > 0.08
    )
    return {
        "up5": up,
        "down5": down,
        "avg_abs": float(win.abs().mean()),
        "rally_windows": rallies,
        # the balance test only means anything once there ARE big moves to
        # balance: 0up/0dn is a calm name, not a whipsawing one
        "chop": (up + down) >= 4 and abs(up - down) <= 1,
    }


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def counter_trend(close: pd.Series, kind: str, lookback: int = 3) -> dict:
    """Is the name currently moving AGAINST the trade we are about to put on?

    Validated gate: on the 33-trade book, 3d>0% flags 11 entries and ALL
    ELEVEN LOST (avg −70.4%). No winner is flagged at any tested threshold.
    Structure and RSI gates are both blind to this — a name can be in a clean
    downtrend, not oversold, not choppy, and still be three days into a bounce
    that runs further. AVGO on 2026-09-18 was exactly that.
    """
    if len(close) < lookback + 1:
        return {"ret": 0.0, "fade": False}
    ret = (float(close.iloc[-1]) / float(close.iloc[-1 - lookback]) - 1) * 100
    fade = (kind == "put" and ret > 0) or (kind == "call" and ret < 0)
    return {"ret": ret, "fade": fade}


def gate(close: pd.Series, kind: str, earnings_clear: bool) -> dict:
    """Hard gates only — no tunable weights, no entry verb.

    A trigger is confirmed on the live tape, never here.
    """
    w = whipsaw_stats(close)
    ct = counter_trend(close, kind)
    r = float(rsi(close).iloc[-1])
    blocks = []
    if not earnings_clear:
        blocks.append("earnings inside window")
    if w["chop"]:
        blocks.append(f"whipsaw {w['up5']}up/{w['down5']}dn")
    if ct["fade"]:
        blocks.append(f"counter-trend 3d {ct['ret']:+.1f}%")
    if kind == "put" and r < 32:
        blocks.append(f"RSI {r:.0f} oversold")
    if kind == "call" and r > 70:
        blocks.append(f"RSI {r:.0f} overbought")
    return {
        "rsi": r,
        "whipsaw": w,
        "counter_trend": ct,
        "blocks": blocks,
        "verdict": "REJECT" if blocks else "WATCH — pending trigger",
    }


def apply_exit_rule(pnl_path: list[float], target: float = 50.0,
                    stop: float = -50.0, cut_day: int | None = 2) -> float:
    """Exit rules, in priority order, against a daily premium P&L path.

    Backtested on the book's 26 reconstructed paths. Entries unchanged, exits
    alone moved the average from -47.3% to -10.5%. 8 of 26 trades touched
    +50% but only 3 were booked as winners — five round-trips were given back.
    """
    for v in pnl_path:
        if v >= target:
            return target
        if v <= stop:
            return stop
    if cut_day is not None and len(pnl_path) > cut_day and pnl_path[cut_day] < 0:
        return pnl_path[cut_day]
    return pnl_path[-1]
