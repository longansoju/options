from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TrendSignal(Enum):
    STRONG   = "strong"    # clear uptrend, healthy momentum — override allowed
    MODERATE = "moderate"  # above key MAs, momentum positive but not accelerating
    NEUTRAL  = "neutral"   # mixed signals — no override
    WEAK     = "weak"      # downtrend or broken — no override


@dataclass
class TrendResult:
    symbol: str
    signal: TrendSignal
    price: float
    ma50: float
    rsi: float
    ret1m: float       # %
    ret3m: float       # %
    ret6m: float       # %
    vol_ratio: float   # recent 10d vol vs 50d avg
    rationale: str
    risk_multiplier: float   # 1.0 = full size, <1.0 = reduced for elevated IVR
    structure: str           # uptrend | potential_uptrend | weakening | downtrend | unknown
    last_swing_low: Optional[float]  # price of last confirmed HL — entry zone reference
    near_hl: bool            # True if price is within 5% above last swing low


class TrendAnalyzer:
    """
    Computes price-based trend signals from a price history DataFrame.

    Scoring (max 14):
      MA50 position : 3 pts  — price above 50-day MA
      RSI-14        : 3 pts  — in 50–75 range (bullish, not overbought)
                      1 pt   — ≥75 (overbought caution)
      1M return     : 2 pts  — > +10%
      3M return     : 2 pts  — > +20%
      6M return     : 1 pt   — > +30%
      Volume ratio  : 1 pt   — recent 10d avg > 50d avg by >10%
      HH/HL struct  : 2 pts  — both Higher High + Higher Low confirmed
                      1 pt   — only one of HH or HL (potential/weakening)
                      0 pts  — Lower High + Lower Low (downtrend structure)
                     -1 pt   — price has broken below the last swing low

    Thresholds  → signal:
      ≥ 9  → STRONG    (IVR gate still applies in main.py)
      ≥ 6  → MODERATE
      ≥ 3  → NEUTRAL
      < 3  → WEAK

    Momentum override rules (applied in main.py alongside IVR):
      IVR LOW    (<30) : always allowed, risk × 1.00
      IVR MEDIUM (30–50): allowed if STRONG or MODERATE, risk × 0.75
      IVR HIGH   (50–70): allowed if STRONG only,        risk × 0.50
      IVR CEILING (>70) : refused regardless of trend
    """

    MIN_BARS     = 63   # need at least 3 months of data
    SWING_WINDOW = 5    # bars on each side required to qualify as a local extreme
    NEAR_HL_PCT  = 0.05 # within 5 % above last swing low → "HL entry zone"

    # ── Swing-point detection ────────────────────────────────────────────────

    def _find_swings(
        self, close: pd.Series
    ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """
        Identify swing highs and lows using a fixed-width local-extreme filter.

        A bar at index i is a swing high when:
          - it is the maximum of the [i-w, i+w] window, AND
          - it is strictly higher than its immediate neighbours (avoids flat tops).

        The same logic inverted applies for swing lows.

        Returns two lists of (bar_index, price) tuples, oldest → newest.
        """
        prices = close.values
        n = len(prices)
        w = self.SWING_WINDOW
        swing_highs: list[tuple[int, float]] = []
        swing_lows:  list[tuple[int, float]] = []

        for i in range(w, n - w):
            segment = prices[i - w : i + w + 1]
            p = prices[i]
            if (p >= float(np.max(segment))
                    and p > prices[i - 1] and p > prices[i + 1]):
                swing_highs.append((i, float(p)))
            if (p <= float(np.min(segment))
                    and p < prices[i - 1] and p < prices[i + 1]):
                swing_lows.append((i, float(p)))

        return swing_highs, swing_lows

    def _market_structure(
        self, close: pd.Series
    ) -> tuple[int, str, Optional[float], bool, str]:
        """
        Classify price structure from the two most recent swing points.

        Returns
        -------
        score_pts  : int   — 0–2 contribution to the trend score
        structure  : str   — human label
        last_sl    : float | None — price of last swing low (HL reference)
        near_hl    : bool  — price is in the HL entry zone (0–5 % above last SL)
        detail     : str   — one-line description for the rationale string
        """
        swing_highs, swing_lows = self._find_swings(close)
        price = float(close.iloc[-1])

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return 0, "unknown", None, False, "insufficient swing data"

        sh_prev, sh_last = swing_highs[-2][1], swing_highs[-1][1]
        sl_prev, sl_last = swing_lows[-2][1],  swing_lows[-1][1]

        hh = sh_last > sh_prev   # Higher High
        hl = sl_last > sl_prev   # Higher Low

        # HL entry zone: price is above (not below) the last swing low
        # and hasn't moved more than NEAR_HL_PCT away from it
        near_hl = (
            sl_last > 0
            and price >= sl_last
            and (price / sl_last - 1) <= self.NEAR_HL_PCT
        )

        # Trend-break warning: price closed below the last swing low
        below_hl = price < sl_last

        if hh and hl:
            pts = 2
            structure = "uptrend"
            detail = (
                f"HH ${sh_last:.0f}>${sh_prev:.0f} "
                f"+ HL ${sl_last:.0f}>${sl_prev:.0f}"
            )
            if near_hl:
                detail += " ← at HL entry zone"
        elif hl and not hh:
            pts = 1
            structure = "potential_uptrend"
            detail = (
                f"HL ${sl_last:.0f}>${sl_prev:.0f} "
                f"| LH ${sh_last:.0f}<${sh_prev:.0f}"
            )
        elif hh and not hl:
            pts = 1
            structure = "weakening"
            detail = (
                f"HH ${sh_last:.0f}>${sh_prev:.0f} "
                f"| LL ${sl_last:.0f}<${sl_prev:.0f}"
            )
        else:
            pts = 0
            structure = "downtrend"
            detail = (
                f"LH ${sh_last:.0f}<${sh_prev:.0f} "
                f"+ LL ${sl_last:.0f}<${sl_prev:.0f}"
            )

        if below_hl:
            pts = max(0, pts - 1)
            detail += f" ⚠️ price ${price:.0f} below last HL ${sl_last:.0f}"

        return pts, structure, float(sl_last), near_hl, detail

    # ── Main entry point ─────────────────────────────────────────────────────

    def analyze(self, symbol: str, df: pd.DataFrame) -> Optional[TrendResult]:
        close = df["Close"].squeeze().dropna()
        vol   = df["Volume"].squeeze().dropna()

        if len(close) < self.MIN_BARS:
            logger.warning(
                "%s: only %d bars, need %d for trend analysis",
                symbol, len(close), self.MIN_BARS,
            )
            return None

        price = float(close.iloc[-1])
        ma50  = float(close.rolling(50).mean().iloc[-1])

        ret1m = (price / float(close.iloc[-21])  - 1) * 100 if len(close) >= 21  else 0.0
        ret3m = (price / float(close.iloc[-63])  - 1) * 100 if len(close) >= 63  else 0.0
        ret6m = (price / float(close.iloc[-126]) - 1) * 100 if len(close) >= 126 else 0.0

        # RSI-14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

        # Volume trend: avg last 10d vs avg last 50d
        vol_ratio = (
            float(vol.iloc[-10:].mean() / vol.iloc[-50:].mean())
            if len(vol) >= 50 else 1.0
        )

        above_50 = price > ma50

        # ── Base score (max 12) ──────────────────────────────────────────────
        score = 0
        if above_50:        score += 3
        if 50 < rsi < 75:   score += 3
        elif rsi >= 75:     score += 1   # overbought — caution
        if ret1m  > 10:     score += 2
        if ret3m  > 20:     score += 2
        if ret6m  > 30:     score += 1
        if vol_ratio > 1.1: score += 1

        # ── HH / HL structure bonus (max +2) ────────────────────────────────
        struct_pts, structure, last_swing_low, near_hl, struct_detail = (
            self._market_structure(close)
        )
        score += struct_pts

        # ── Signal (score max 14) ────────────────────────────────────────────
        if score >= 9:
            signal = TrendSignal.STRONG
            risk_multiplier = 1.0
        elif score >= 6:
            signal = TrendSignal.MODERATE
            risk_multiplier = 0.75
        elif score >= 3:
            signal = TrendSignal.NEUTRAL
            risk_multiplier = 0.50
        else:
            signal = TrendSignal.WEAK
            risk_multiplier = 0.0

        rationale = (
            f"trend={signal.value} score={score}/14 | "
            f"price={price:.2f} vs MA50={ma50:.2f} ({'above' if above_50 else 'below'}) | "
            f"RSI={rsi:.0f} | 1M={ret1m:+.1f}% 3M={ret3m:+.1f}% 6M={ret6m:+.1f}% | "
            f"vol_ratio={vol_ratio:.2f}x | "
            f"structure={structure} [{struct_detail}]"
        )

        return TrendResult(
            symbol=symbol,
            signal=signal,
            price=price,
            ma50=ma50,
            rsi=rsi,
            ret1m=ret1m,
            ret3m=ret3m,
            ret6m=ret6m,
            vol_ratio=vol_ratio,
            rationale=rationale,
            risk_multiplier=risk_multiplier,
            structure=structure,
            last_swing_low=last_swing_low,
            near_hl=near_hl,
        )
