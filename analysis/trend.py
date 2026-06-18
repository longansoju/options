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
    ret1m: float   # %
    ret3m: float   # %
    ret6m: float   # %
    vol_ratio: float  # recent 10d vol vs 50d avg
    rationale: str
    risk_multiplier: float  # 1.0 = full size, <1.0 = reduced for elevated IVR


class TrendAnalyzer:
    """
    Computes price-based trend signals from a price history DataFrame.

    Momentum override rules (applied in main.py alongside IVR):
      IVR LOW   (<30)  : always allowed, risk × 1.00  (unchanged)
      IVR MEDIUM(30-50): allowed if trend STRONG/MODERATE, risk × 0.75
      IVR HIGH  (50-70): allowed if trend STRONG only,     risk × 0.50
      IVR EXTREME(>70) : refused regardless of trend
    """

    MIN_BARS = 63  # need at least 3 months of data

    def analyze(self, symbol: str, df: pd.DataFrame) -> Optional[TrendResult]:
        close = df["Close"].squeeze().dropna()
        vol   = df["Volume"].squeeze().dropna()

        if len(close) < self.MIN_BARS:
            logger.warning("%s: only %d bars, need %d for trend analysis", symbol, len(close), self.MIN_BARS)
            return None

        price  = float(close.iloc[-1])
        ma50   = float(close.rolling(50).mean().iloc[-1])
        ret1m  = (price / float(close.iloc[-21])  - 1) * 100 if len(close) >= 21  else 0.0
        ret3m  = (price / float(close.iloc[-63])  - 1) * 100 if len(close) >= 63  else 0.0
        ret6m  = (price / float(close.iloc[-126]) - 1) * 100 if len(close) >= 126 else 0.0

        # RSI-14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

        # Volume trend: avg last 10d vs avg last 50d
        vol_ratio = float(vol.iloc[-10:].mean() / vol.iloc[-50:].mean()) if len(vol) >= 50 else 1.0

        above_50 = price > ma50

        # --- Score → signal ---
        score = 0
        if above_50:          score += 3
        if 50 < rsi < 75:     score += 3   # bullish, not overbought
        if rsi >= 75:         score += 1   # overbought — caution
        if ret1m  > 10:       score += 2
        if ret3m  > 20:       score += 2
        if ret6m  > 30:       score += 1
        if vol_ratio > 1.1:   score += 1

        if score >= 9:
            signal = TrendSignal.STRONG
            risk_multiplier = 1.0   # full size (IVR gate still applies)
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
            f"trend={signal.value} score={score}/12 | "
            f"price={price:.2f} vs MA50={ma50:.2f} ({'above' if above_50 else 'below'}) | "
            f"RSI={rsi:.0f} | 1M={ret1m:+.1f}% 3M={ret3m:+.1f}% 6M={ret6m:+.1f}% | "
            f"vol_ratio={vol_ratio:.2f}x"
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
        )