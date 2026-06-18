from __future__ import annotations

import logging
from typing import List, Optional

from data_ingestion.base import Chain, OptionContract
import config

logger = logging.getLogger(__name__)


class ContractSelector:
    """
    Selects the best OTM long call or put from a Chain.

    Strategy: momentum/accumulation — buy OTM, let the trend carry price
    into the money. Selection order:
      1. DTE in [MIN_DTE_AT_ENTRY, MAX_DTE_AT_ENTRY]
      2. OTM only (strike > spot for calls, strike < spot for puts)
      3. Liquidity: volume, open interest, spread
      4. Within budget (max_budget param from account equity × risk cap)
      5. Prefer strike closest to TARGET_OTM_PCT from spot;
         walk further OTM if nothing fits budget at target,
         walk closer to ATM if nothing fits further out.
    """

    def _passes_liquidity(self, c: OptionContract) -> bool:
        if c.volume < config.MIN_VOLUME:
            return False

        stale_quotes = c.bid <= 0 or c.ask <= 0
        if stale_quotes:
            if c.last <= 0:
                return False
        else:
            if c.spread_pct > config.MAX_BID_ASK_SPREAD_PCT:
                return False

        # OI check: skip when yfinance returns 0 but volume proves trading activity
        if c.open_interest > 0 and c.open_interest < config.MIN_OPEN_INTEREST:
            return False

        return True

    def _cost(self, c: OptionContract) -> float:
        """Cost of 1 contract in USD (effective_ask × 100)."""
        return c.effective_ask * 100.0

    def _select(
        self,
        candidates: List[OptionContract],
        spot: float,
        option_type: str,
        max_budget: Optional[float],
        symbol: str,
    ) -> Optional[OptionContract]:
        """
        From a pre-filtered list of liquid, DTE-valid contracts:
        - Keep OTM only
        - Apply budget filter
        - Score by distance from TARGET_OTM_PCT; prefer closer to target
        """
        target_pct = config.TARGET_OTM_PCT_CALL if option_type == "call" else config.TARGET_OTM_PCT_PUT

        # OTM filter
        if option_type == "call":
            otm = [c for c in candidates if c.strike > spot]
        else:
            otm = [c for c in candidates if c.strike < spot]

        if not otm:
            logger.warning("%s: no OTM %ss found in DTE window", symbol, option_type)
            return None

        # Budget filter
        if max_budget is not None:
            affordable = [c for c in otm if self._cost(c) <= max_budget]
            if not affordable:
                # Log the cheapest available for diagnostics
                cheapest = min(otm, key=self._cost)
                logger.warning(
                    "%s: cheapest OTM %s costs $%.0f but budget is $%.0f — no fit",
                    symbol, option_type, self._cost(cheapest), max_budget,
                )
                return None
            otm = affordable

        # Score: distance from target OTM %, prefer exact target, then closer-to-ATM
        target_strike = spot * (1 + target_pct) if option_type == "call" else spot * (1 - target_pct)

        best = min(otm, key=lambda c: (
            abs(c.strike - target_strike),  # closest to target OTM%
            -c.volume,                       # higher volume as tiebreak
        ))
        return best

    def select_call(
        self, chain: Chain, max_budget: Optional[float] = None
    ) -> Optional[OptionContract]:
        candidates = [
            c for c in chain.calls()
            if config.MIN_DTE_AT_ENTRY <= c.dte <= config.MAX_DTE_AT_ENTRY
            and self._passes_liquidity(c)
        ]
        result = self._select(candidates, chain.spot_price, "call", max_budget, chain.underlying)
        if result is None:
            logger.warning(
                "%s: no affordable OTM call in %d–%d DTE window (budget=$%.0f)",
                chain.underlying, config.MIN_DTE_AT_ENTRY, config.MAX_DTE_AT_ENTRY,
                max_budget or 0,
            )
        return result

    def select_put(
        self, chain: Chain, max_budget: Optional[float] = None
    ) -> Optional[OptionContract]:
        candidates = [
            c for c in chain.puts()
            if config.MIN_DTE_AT_ENTRY <= c.dte <= config.MAX_DTE_AT_ENTRY
            and self._passes_liquidity(c)
        ]
        result = self._select(candidates, chain.spot_price, "put", max_budget, chain.underlying)
        if result is None:
            logger.warning(
                "%s: no affordable OTM put in %d–%d DTE window (budget=$%.0f)",
                chain.underlying, config.MIN_DTE_AT_ENTRY, config.MAX_DTE_AT_ENTRY,
                max_budget or 0,
            )
        return result

    def select(
        self, chain: Chain, direction: str, max_budget: Optional[float] = None
    ) -> Optional[OptionContract]:
        if direction == "bullish":
            return self.select_call(chain, max_budget)
        elif direction == "bearish":
            return self.select_put(chain, max_budget)
        else:
            raise ValueError(f"Unknown direction '{direction}'; expected 'bullish' or 'bearish'")
