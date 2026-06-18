from __future__ import annotations

import logging
from typing import List, Optional

from data_ingestion.base import Chain, OptionContract
from analysis.iv_regime import IVRegime, IVRankResult
import config

logger = logging.getLogger(__name__)


class ContractSelector:
    """
    Selects the best single long call or long put from a Chain.

    Selection criteria (in order of application):
    1. DTE in [MIN_DTE_AT_ENTRY, MAX_DTE_AT_ENTRY]
    2. Liquidity filter: volume, open interest, bid-ask spread
    3. Strike selection: closest to target delta (if available) or
       OTM bias (call: slightly above spot; put: slightly below spot)
    4. Prefer higher open interest among tied candidates
    """

    def _passes_liquidity(self, c: OptionContract) -> bool:
        if c.volume < config.MIN_VOLUME:
            return False
        if c.open_interest < config.MIN_OPEN_INTEREST:
            return False
        if c.spread_pct > config.MAX_BID_ASK_SPREAD_PCT:
            return False
        if c.bid <= 0 or c.ask <= 0:
            return False
        return True

    def _score_strike(self, contract: OptionContract, spot: float, option_type: str) -> float:
        """Lower score = better candidate."""
        if contract.delta is not None:
            target = config.TARGET_DELTA_CALL if option_type == "call" else config.TARGET_DELTA_PUT
            return abs(contract.delta - target)
        # Fallback: price-based OTM bias
        if option_type == "call":
            # want strike slightly above spot (~5%)
            target_strike = spot * 1.05
        else:
            target_strike = spot * 0.95
        return abs(contract.strike - target_strike)

    def select_call(self, chain: Chain) -> Optional[OptionContract]:
        candidates = [
            c for c in chain.calls()
            if config.MIN_DTE_AT_ENTRY <= c.dte <= config.MAX_DTE_AT_ENTRY
            and self._passes_liquidity(c)
        ]
        if not candidates:
            logger.warning("%s: no liquid calls in %d–%d DTE window", chain.underlying,
                           config.MIN_DTE_AT_ENTRY, config.MAX_DTE_AT_ENTRY)
            return None
        return min(candidates, key=lambda c: (
            self._score_strike(c, chain.spot_price, "call"),
            -c.open_interest,
        ))

    def select_put(self, chain: Chain) -> Optional[OptionContract]:
        candidates = [
            c for c in chain.puts()
            if config.MIN_DTE_AT_ENTRY <= c.dte <= config.MAX_DTE_AT_ENTRY
            and self._passes_liquidity(c)
        ]
        if not candidates:
            logger.warning("%s: no liquid puts in %d–%d DTE window", chain.underlying,
                           config.MIN_DTE_AT_ENTRY, config.MAX_DTE_AT_ENTRY)
            return None
        return min(candidates, key=lambda c: (
            self._score_strike(c, chain.spot_price, "put"),
            -c.open_interest,
        ))

    def select(self, chain: Chain, direction: str) -> Optional[OptionContract]:
        """
        direction: "bullish" → long call; "bearish" → long put.
        Returns None if no liquid contract found.
        """
        if direction == "bullish":
            return self.select_call(chain)
        elif direction == "bearish":
            return self.select_put(chain)
        else:
            raise ValueError(f"Unknown direction '{direction}'; expected 'bullish' or 'bearish'")
