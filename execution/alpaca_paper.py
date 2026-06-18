from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import config
from data_ingestion.base import OptionContract
from risk.sizing import GuardrailViolation, SizeResult

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    contract_symbol: str
    quantity: int
    fill_price: float      # per-contract price (realistic: ask price)
    commission: float
    total_cost: float      # fill_price * 100 * quantity + commission
    timestamp: datetime
    order_id: Optional[str] = None


class AlpacaPaperBroker:
    """
    Wraps the Alpaca paper trading API for long option buys only (C4: paper, C2/C3: buy side).

    Fill model (Section 10 realism):
      - Paper fills at ask price (crossing the spread), not mid. This is the
        most important paper-vs-live realism adjustment.
      - Commission: $0.65 per contract (configurable in config.py).
    """

    def __init__(self) -> None:
        if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in the environment. "
                "See .env.example for instructions."
            )
        if not config.ALPACA_PAPER:
            raise GuardrailViolation(
                "C4 violation: ALPACA_PAPER must be True. Real-money routing is forbidden."
            )
        from alpaca.trading.client import TradingClient
        self._client = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=True,
        )

    def get_account_equity(self) -> float:
        account = self._client.get_account()
        return float(account.equity)

    def get_open_position_risk(self) -> float:
        """Sum of max-loss across all open long option positions."""
        try:
            positions = self._client.get_all_positions()
        except Exception:
            return 0.0
        total = 0.0
        for pos in positions:
            # cost_basis on Alpaca is total cost paid for the position
            cost = float(pos.cost_basis or 0)
            total += cost
        return total

    def buy(self, contract: OptionContract, size: SizeResult) -> Fill:
        """
        Place a limit BUY order at the effective ask price (crosses the spread).
        Falls back to last-trade price when bid/ask quotes are stale (yfinance gap).
        Only long (BUY) orders are allowed (C2/C3).
        """
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        fill_price = contract.effective_ask          # handles stale 0/0 quotes
        limit_price = round(fill_price * 1.02, 2)   # 2% buffer for fill certainty on stale quotes

        order_request = LimitOrderRequest(
            symbol=contract.symbol,
            qty=size.contracts,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        )

        logger.info(
            "Submitting paper BUY: %s x%d @ %.2f (limit %.2f)",
            contract.symbol, size.contracts, fill_price, limit_price,
        )

        order = self._client.submit_order(order_data=order_request)
        commission = config.COMMISSION_PER_CONTRACT * size.contracts
        total_cost = fill_price * 100 * size.contracts + commission

        return Fill(
            contract_symbol=contract.symbol,
            quantity=size.contracts,
            fill_price=fill_price,
            commission=commission,
            total_cost=total_cost,
            timestamp=datetime.utcnow(),
            order_id=str(order.id),
        )
