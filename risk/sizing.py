from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from data_ingestion.base import OptionContract
import config

logger = logging.getLogger(__name__)


class GuardrailViolation(Exception):
    """Raised when a trade would violate a hard constraint (C1–C6)."""


@dataclass
class SizeResult:
    contracts: int
    max_loss_per_contract: float   # premium * 100
    total_max_loss: float          # max_loss_per_contract * contracts
    risk_pct_of_equity: float
    commission: float


class PositionSizer:
    """
    Enforces C2, C3, C5, C6 before any order is placed.

    C2/C3 — only long premium (buy side) allowed.
    C5    — max loss = premium paid (fully known before entry).
    C6    — no single position > MAX_RISK_PER_TRADE_PCT of equity.
    """

    def check_strategy(self, strategy: str) -> None:
        """C2/C3: raise if strategy is not in the allowed long-only set."""
        if strategy not in config.ALLOWED_ACTIONS:
            raise GuardrailViolation(
                f"Strategy '{strategy}' violates C2/C3. "
                f"Only {sorted(config.ALLOWED_ACTIONS)} are permitted. "
                "No short premium, no credit spreads, no margin strategies."
            )

    def compute_size(
        self,
        contract: OptionContract,
        account_equity: float,
        open_position_risk: float = 0.0,
        risk_multiplier: float = 1.0,
    ) -> SizeResult:
        """
        Compute how many contracts can be bought without violating C5/C6.

        open_position_risk — total USD at risk in existing open positions
                              (used to check portfolio heat).
        """
        if contract.ask <= 0:
            raise GuardrailViolation(
                f"Contract {contract.symbol} has ask price <= 0; cannot size."
            )

        # C5: max loss per contract = ask price * 100 (one contract = 100 shares)
        max_loss_per_contract = contract.ask * 100.0

        # C6: max risk per trade (reduced by risk_multiplier for elevated-IVR momentum entries)
        max_risk_dollars = account_equity * config.MAX_RISK_PER_TRADE_PCT / 100.0 * risk_multiplier
        contracts = int(max_risk_dollars / max_loss_per_contract)
        if contracts < 1:
            raise GuardrailViolation(
                f"C6 violation: even 1 contract costs {max_loss_per_contract:.2f} USD, "
                f"exceeding the {config.MAX_RISK_PER_TRADE_PCT}% cap of "
                f"{max_risk_dollars:.2f} USD on {account_equity:.2f} equity."
            )

        # Portfolio heat check
        new_risk = open_position_risk + (max_loss_per_contract * contracts)
        heat_pct = new_risk / account_equity * 100.0
        if heat_pct > config.MAX_PORTFOLIO_HEAT_PCT:
            # Try reducing to 1 contract
            one_contract_heat = (open_position_risk + max_loss_per_contract) / account_equity * 100.0
            if one_contract_heat > config.MAX_PORTFOLIO_HEAT_PCT:
                raise GuardrailViolation(
                    f"Portfolio heat would reach {one_contract_heat:.1f}% "
                    f"(cap: {config.MAX_PORTFOLIO_HEAT_PCT}%). "
                    "No room for another position."
                )
            contracts = 1
            logger.info(
                "Reduced to 1 contract to stay under portfolio heat cap "
                "(%.1f%% → %.1f%%)", heat_pct, one_contract_heat
            )

        total_max_loss = max_loss_per_contract * contracts
        commission = config.COMMISSION_PER_CONTRACT * contracts
        risk_pct = total_max_loss / account_equity * 100.0

        return SizeResult(
            contracts=contracts,
            max_loss_per_contract=max_loss_per_contract,
            total_max_loss=total_max_loss,
            risk_pct_of_equity=risk_pct,
            commission=commission,
        )
