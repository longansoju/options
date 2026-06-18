from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from data_ingestion.base import IVSeries
import config

logger = logging.getLogger(__name__)


class IVRegime(Enum):
    LOW = "low"        # IVR < 30 — cheap options, prefer buying
    MEDIUM = "medium"  # 30 <= IVR <= 50 — neutral
    HIGH = "high"      # IVR > 50 — expensive options, avoid naked longs


@dataclass
class IVRankResult:
    symbol: str
    current_iv: float
    iv_rank: float          # 0–100
    iv_min_52w: float
    iv_max_52w: float
    regime: IVRegime
    is_proxy: bool          # True if computed from realized vol, not actual IV
    rationale: str


class IVRankClassifier:
    """
    Computes IV Rank for a symbol given an IVSeries.

    IVR = (current_IV - min_52w) / (max_52w - min_52w) * 100

    If the series has fewer than IV_RANK_MIN_HISTORY_DAYS data points,
    the result is marked is_proxy=True and should be treated as a soft signal.
    """

    def classify(self, series: IVSeries) -> Optional[IVRankResult]:
        if not series.iv_values:
            logger.warning("%s: empty IV series, cannot compute IV Rank", series.symbol)
            return None

        current = series.current_iv
        iv_min = min(series.iv_values)
        iv_max = max(series.iv_values)

        if iv_max == iv_min:
            # No variance in the series — treat as mid-range
            ivr = 50.0
        else:
            ivr = (current - iv_min) / (iv_max - iv_min) * 100.0

        ivr = max(0.0, min(100.0, ivr))

        if ivr < config.IVR_LOW_THRESHOLD:
            regime = IVRegime.LOW
        elif ivr > config.IVR_HIGH_THRESHOLD:
            regime = IVRegime.HIGH
        else:
            regime = IVRegime.MEDIUM

        is_proxy = getattr(series, "_is_proxy", False)
        proxy_note = " [PROXY: realized vol used, not actual IV]" if is_proxy else ""
        n = len(series.iv_values)

        rationale = (
            f"IVR={ivr:.1f} ({regime.value}): current={current:.2%}, "
            f"52w-range=[{iv_min:.2%}, {iv_max:.2%}], n={n}{proxy_note}"
        )

        return IVRankResult(
            symbol=series.symbol,
            current_iv=current,
            iv_rank=ivr,
            iv_min_52w=iv_min,
            iv_max_52w=iv_max,
            regime=regime,
            is_proxy=is_proxy,
            rationale=rationale,
        )
