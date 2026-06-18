from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Protocol, runtime_checkable

import pandas as pd


@dataclass
class Fundamentals:
    symbol: str
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    market_cap: Optional[float]
    sector: Optional[str]
    industry: Optional[str]


@dataclass
class OptionContract:
    symbol: str           # OCC symbol e.g. "AAPL250117C00150000"
    underlying: str
    expiration: date
    strike: float
    option_type: str      # "call" or "put"
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None

    @property
    def effective_ask(self) -> float:
        """Ask price for sizing; falls back to last when yfinance returns stale 0 quotes."""
        return self.ask if self.ask > 0 else self.last

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.mid * 100.0

    @property
    def dte(self) -> int:
        return (self.expiration - date.today()).days


@dataclass
class Chain:
    underlying: str
    as_of: date
    spot_price: float
    contracts: List[OptionContract]

    def calls(self) -> List[OptionContract]:
        return [c for c in self.contracts if c.option_type == "call"]

    def puts(self) -> List[OptionContract]:
        return [c for c in self.contracts if c.option_type == "put"]

    def atm_iv(self, option_type: str = "call") -> Optional[float]:
        """Return IV of the contract closest to ATM for the given type."""
        pool = self.calls() if option_type == "call" else self.puts()
        if not pool:
            return None
        closest = min(pool, key=lambda c: abs(c.strike - self.spot_price))
        return closest.implied_volatility


@dataclass
class Event:
    symbol: str
    event_type: str   # "earnings", "fomc", "cpi", etc.
    date: date
    confirmed: bool = False


@dataclass
class IVSeries:
    symbol: str
    dates: List[date]
    iv_values: List[float]

    @property
    def current_iv(self) -> float:
        return self.iv_values[-1] if self.iv_values else 0.0

    @property
    def is_proxy(self) -> bool:
        return getattr(self, "_is_proxy", False)


@dataclass
class SmartMoneyTrade:
    symbol: str
    trader_name: str
    trade_type: str
    amount: float
    trade_date: date
    disclosure_date: date
    source: str


@dataclass
class Signal:
    name: str
    value: float
    direction: str   # "bullish", "bearish", "neutral"
    strength: str    # "strong", "moderate", "weak"
    rationale: str


@dataclass
class Recommendation:
    action: str                        # "buy", "sell", "hold", "refuse"
    symbol: str
    contract: Optional[OptionContract]
    structure: str                     # "long_call", "long_put"
    max_loss: float                    # premium * 100 * contracts (USD)
    size: int                          # number of contracts
    thesis: str
    signals: List[Signal]
    guardrails_checked: bool = False
    refused_reason: Optional[str] = None


@runtime_checkable
class DataProvider(Protocol):
    def fundamentals(self, symbol: str) -> Fundamentals: ...
    def options_chain(self, symbol: str) -> Chain: ...
    def price_history(self, symbol: str, lookback_days: int) -> pd.DataFrame: ...
    def iv_history(self, symbol: str, lookback_days: int) -> IVSeries: ...
    def earnings_calendar(self, symbol: str) -> List[Event]: ...
    def smart_money(self, symbol: str) -> List[SmartMoneyTrade]: ...
