"""
Momentum / weekly-lotto scan (day-trader concept).

A DIFFERENT animal from scan_watchlist.py. That scanner is for 35-45 DTE swing
entries gated by an IVR ceiling. THIS one is the opposite philosophy:

    • Short-dated   — defaults to the nearest Friday weekly (the STX-C1000 example).
    • Buy strength  — follows momentum (breakout calls / breakdown puts), not dips.
    • IVR ignored   — high realized vol is a FEATURE here, not a disqualifier; it's
                      what lets a cheap OTM weekly multiply on a fast move.

What it surfaces: which names have the volatility + momentum to make a fast move
inside a few days, the expected move over that window, and a realistic strike
ladder (ATM / 1-sigma / 2-sigma) with ballpark premium + risk-neutral prob ITM.

HARD CONSTRAINTS / honesty:
    • Daily bars only — NO intraday feed. This tells you WHERE to watch; you still
      time the actual entry on the live tape.
    • No live options chain — premium is Black-Scholes priced with realized vol as
      an IV proxy. Treat the dollar figures as ballpark, not quotes.
    • This is the highest-risk style in the system. Most far-OTM weeklies expire
      worthless. The edge is exit speed + strike realism + tiny size, not holding.

Usage:
    python scan_momentum.py                 # nearest Friday, auto-direction per name
    python scan_momentum.py --dte 4         # force a specific days-to-expiry
    python scan_momentum.py --direction call
    python scan_momentum.py --top 12
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd

import config
from analysis.trend import TrendAnalyzer
from data_ingestion.yfinance_provider import YFinanceProvider
from journal.research_log import ResearchLog

import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")

RISK_FREE = 0.045


# ── Black-Scholes (self-contained; repo has no pricer) ──────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, vol: float,
             opt: str, r: float = RISK_FREE) -> float:
    """Black-Scholes price. t_years and vol must be > 0."""
    if t_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        return max(0.0, (spot - strike) if opt == "call" else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    if opt == "call":
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
    return strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_prob_itm(spot: float, strike: float, t_years: float, vol: float,
                opt: str, r: float = RISK_FREE) -> float:
    """Risk-neutral P(finish ITM) = N(d2) for calls, N(-d2) for puts."""
    if t_years <= 0 or vol <= 0:
        return 0.0
    d2 = (math.log(spot / strike) + (r - 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    return _norm_cdf(d2) if opt == "call" else _norm_cdf(-d2)


# ── strike rounding to plausible listed ticks ───────────────────────────────

def _round_strike(x: float) -> float:
    if x < 25:    step = 0.5
    elif x < 100: step = 1.0
    elif x < 250: step = 2.5
    elif x < 500: step = 5.0
    else:         step = 10.0
    return round(x / step) * step


# ── per-symbol momentum metrics ─────────────────────────────────────────────

@dataclass
class MomentumRow:
    symbol: str
    spot: float
    rv: float            # annualized realized vol (20d)
    vol_rank: float      # RV percentile vs own 252d range (0-100) — the "IVR" analogue
    atr_pct: float       # ATR14 / price (daily range capacity)
    ret5: float          # 5-day % return
    vol_ratio: float     # 10d avg volume / 50d avg volume
    rsi: float
    dist_high: float     # % below 20d high (0 = at the high)
    dist_low: float      # % above 20d low
    structure: str
    direction: str       # call | put
    ignition: float      # momentum-following score (0-10)
    why: str


def _realized_vol(close: pd.Series, window: int = 20) -> float:
    logret = np.log(close / close.shift(1)).dropna()
    if len(logret) < window:
        return float("nan")
    return float(logret.iloc[-window:].std() * math.sqrt(252))


def _vol_rank(close: pd.Series) -> float:
    """Current 20d RV vs its own min/max over ~252d — same formula as the IVR proxy."""
    logret = np.log(close / close.shift(1))
    rv = logret.rolling(20).std() * math.sqrt(252)
    rv = rv.dropna().iloc[-252:]
    if len(rv) < 30:
        return float("nan")
    cur, lo, hi = float(rv.iloc[-1]), float(rv.min()), float(rv.max())
    if hi <= lo:
        return 50.0
    return (cur - lo) / (hi - lo) * 100.0


def _atr_pct(df: pd.DataFrame, window: int = 14) -> float:
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window).mean().iloc[-1]
    price = float(c.iloc[-1])
    return float(atr / price * 100) if price else float("nan")


def _analyze_symbol(sym: str, provider: YFinanceProvider,
                    analyzer: TrendAnalyzer, force_dir: Optional[str]) -> Optional[MomentumRow]:
    df = provider.price_history(sym, 300)
    if df.empty or len(df) < 63:
        return None
    close = df["Close"].squeeze().dropna()
    spot = float(close.iloc[-1])

    rv       = _realized_vol(close)
    vol_rank = _vol_rank(close)
    atr_pct  = _atr_pct(df)
    ret5     = (spot / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0.0

    hi20 = float(close.iloc[-20:].max())
    lo20 = float(close.iloc[-20:].min())
    dist_high = (hi20 / spot - 1) * 100   # how far above us the 20d high sits
    dist_low  = (spot / lo20 - 1) * 100   # how far above the 20d low we are

    tr = analyzer.analyze(sym, df)
    rsi       = tr.rsi if tr else 50.0
    vol_ratio = tr.vol_ratio if tr else 1.0
    structure = tr.structure if tr else "unknown"

    # ── direction: follow the immediate momentum ────────────────────────────
    if force_dir:
        direction = force_dir
    elif ret5 >= 0:
        direction = "call"
    else:
        direction = "put"

    # ── ignition score (0-10): momentum-following, vol is GOOD here ──────────
    why = []
    score = 0.0

    # 1. Volatility capacity — the inversion vs the swing scanner.
    if atr_pct >= 4:   score += 2; why.append(f"ATR{atr_pct:.1f}%+2")
    elif atr_pct >= 2.5: score += 1; why.append(f"ATR{atr_pct:.1f}%+1")

    # 2. Volume surge — someone is active.
    if vol_ratio >= 1.3: score += 2; why.append(f"vol{vol_ratio:.1f}x+2")
    elif vol_ratio >= 1.1: score += 1; why.append(f"vol{vol_ratio:.1f}x+1")

    # 3. Short-term momentum in the trade direction.
    aligned = ret5 if direction == "call" else -ret5
    if aligned >= 5:   score += 2; why.append(f"5d{ret5:+.0f}%+2")
    elif aligned >= 2: score += 1; why.append(f"5d{ret5:+.0f}%+1")
    elif aligned < 0:  score -= 1; why.append(f"5d{ret5:+.0f}%-1")  # fighting the tape

    # 4. Breakout / breakdown proximity.
    if direction == "call" and dist_high <= 1.5:
        score += 2; why.append(f"@20dHi+2")
    elif direction == "call" and dist_high <= 4:
        score += 1; why.append(f"nrHi+1")
    if direction == "put" and dist_low <= 1.5:
        score += 2; why.append(f"@20dLo+2")
    elif direction == "put" and dist_low <= 4:
        score += 1; why.append(f"nrLo+1")

    # 5. RSI in a momentum zone (not yet exhausted in the trade direction).
    if direction == "call" and 55 <= rsi <= 72:
        score += 1; why.append("RSImom+1")
    elif direction == "call" and rsi > 78:
        score -= 1; why.append("RSIexh-1")
    if direction == "put" and 28 <= rsi <= 45:
        score += 1; why.append("RSImom+1")
    elif direction == "put" and rsi < 22:
        score -= 1; why.append("RSIexh-1")

    return MomentumRow(
        symbol=sym, spot=spot, rv=rv, vol_rank=vol_rank, atr_pct=atr_pct,
        ret5=ret5, vol_ratio=vol_ratio, rsi=rsi,
        dist_high=dist_high, dist_low=dist_low, structure=structure,
        direction=direction, ignition=round(score, 1), why=" ".join(why),
    )


# ── expiry helper ────────────────────────────────────────────────────────────

def _nearest_friday_dte(today: date) -> tuple[date, int]:
    # weekday(): Mon=0 .. Fri=4. Roll to next Friday if today is Fri/weekend.
    days = (4 - today.weekday()) % 7
    if days == 0:
        days = 7
    exp = today + timedelta(days=days)
    return exp, days


# ── strike ladder for one name ───────────────────────────────────────────────

def _strike_ladder(row: MomentumRow, dte: int) -> list[tuple[str, float, float, float, float]]:
    """Return [(label, strike, otm%, premium_per_contract, prob_itm), ...]."""
    spot, vol, d = row.spot, row.rv, row.direction
    t = dte / 365.0
    sigma_move = spot * vol * math.sqrt(dte / 252.0)   # 1-sigma move over the window
    sign = 1 if d == "call" else -1

    ladder = []
    for label, n_sigma in [("ATM", 0.0), ("1σ", 1.0), ("2σ-lotto", 2.0)]:
        raw = spot + sign * n_sigma * sigma_move
        strike = _round_strike(raw)
        if strike <= 0:
            continue
        otm = (strike / spot - 1) * 100 if d == "call" else (1 - strike / spot) * 100
        prem = bs_price(spot, strike, t, vol, d) * 100   # per contract (×100 shares)
        prob = bs_prob_itm(spot, strike, t, vol, d) * 100
        ladder.append((label, strike, otm, prem, prob))
    return ladder


def scan(direction: Optional[str], dte_override: Optional[int], top: int, log: bool = True):
    provider = YFinanceProvider()
    analyzer = TrendAnalyzer()
    rlog = ResearchLog() if log else None
    today = date.today()

    if dte_override:
        exp_str, dte = f"+{dte_override}d", dte_override
    else:
        exp_date, dte = _nearest_friday_dte(today)
        exp_str = exp_date.isoformat()

    tickers = list(dict.fromkeys(
        config.WATCHLIST + [t for ts in config.DIVERSIFICATION.values() for t in ts]
    ))

    print(f"\nMomentum / Weekly-Lotto Scan — {today}  |  expiry={exp_str} ({dte} DTE)"
          f"  |  direction={direction or 'auto'}")
    print("  daily bars only · IVR ignored by design · BS premium via realized-vol proxy")
    print("=" * 104)

    rows: list[MomentumRow] = []
    for sym in tickers:
        try:
            r = _analyze_symbol(sym, provider, analyzer, direction)
            if r and not math.isnan(r.rv):
                rows.append(r)
        except Exception as e:
            logging.warning("%s: %s", sym, e)

    rows.sort(key=lambda r: -r.ignition)

    if rlog is not None:
        for r in rows:
            try:
                rlog.log_scan_row(
                    "momentum", r.symbol, direction=r.direction,
                    price=r.spot, rv=r.rv, vol_rank=r.vol_rank, atr_pct=r.atr_pct,
                    ret5=r.ret5, vol_ratio=r.vol_ratio, rsi=r.rsi,
                    ignition=r.ignition, verdict=r.direction, flags=r.why,
                )
            except Exception as e:
                logging.warning("scan_history log failed for %s: %s", r.symbol, e)

    # ── ranked table ────────────────────────────────────────────────────────
    fmt = "{:<6} {:>8} {:>4} {:>6} {:>5} {:>6} {:>5} {:>5} {:>4}  {:>4}  {}"
    print(fmt.format("Sym", "Spot", "Dir", "RV%", "VolRk", "ATR%", "5d%", "Vol×", "RSI", "Ign", "Why"))
    print("-" * 104)
    for r in rows:
        print(fmt.format(
            r.symbol, f"${r.spot:.2f}", r.direction.upper()[:4],
            f"{r.rv*100:.0f}", f"{r.vol_rank:.0f}", f"{r.atr_pct:.1f}",
            f"{r.ret5:+.0f}", f"{r.vol_ratio:.1f}", f"{r.rsi:.0f}",
            f"{r.ignition:.0f}", r.why,
        ))

    # ── strike ladders for the top N ─────────────────────────────────────────
    print("\n" + "=" * 104)
    print(f"STRIKE LADDERS — top {top} by ignition  (premium = per contract, ballpark)")
    print(f"expected 1σ move over {dte} days shown per name\n")
    for r in rows[:top]:
        sigma_move = r.spot * r.rv * math.sqrt(dte / 252.0)
        em_pct = sigma_move / r.spot * 100
        print(f"  {r.symbol}  {r.direction.upper()}  spot ${r.spot:.2f}  "
              f"| RV {r.rv*100:.0f}%  ATR {r.atr_pct:.1f}%  ign {r.ignition:.0f}  "
              f"| 1σ move ±${sigma_move:.0f} (±{em_pct:.1f}%)")
        for label, strike, otm, prem, prob in _strike_ladder(r, dte):
            print(f"      {label:<9} {r.direction[0].upper()}{strike:<8.1f} "
                  f"{otm:>4.1f}% OTM   ~${prem:>7.0f}/contract   P(ITM)~{prob:>4.1f}%")
        print()

    print("=" * 104)
    print("READ: ignition ranks momentum capacity, NOT a buy signal. ATM = most delta /\n"
          "      best odds; 2σ-lotto = cheapest / lowest odds (the STX-C1000 end). Exit fast,\n"
          "      size tiny — these decay hard. Daily data: confirm the move on the live tape.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--direction", choices=["call", "put"], default=None,
                   help="force direction; default auto-detects per name from 5d momentum")
    p.add_argument("--dte", type=int, default=None,
                   help="days to expiry; default = nearest Friday weekly")
    p.add_argument("--top", type=int, default=8, help="how many strike ladders to print")
    p.add_argument("--no-log", action="store_true", help="skip writing snapshots to scan_history")
    args = p.parse_args()
    scan(args.direction, args.dte, args.top, log=not args.no_log)
