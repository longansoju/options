"""
Market-data provider selection.

Default is yfinance (free, works anywhere). Set MARKET_DATA_PROVIDER=moomoo on the
machine running Moomoo OpenD to use real option chains/quotes instead of the
Black-Scholes-on-realized-vol estimates.

    export MARKET_DATA_PROVIDER=moomoo
    export MOOMOO_OPEND_HOST=127.0.0.1   # default
    export MOOMOO_OPEND_PORT=11111       # default
    export MOOMOO_MARKET=US              # default underlying market prefix
"""
from __future__ import annotations

import os


def get_provider():
    name = os.getenv("MARKET_DATA_PROVIDER", "yfinance").lower()
    if name == "moomoo":
        from .moomoo_provider import MoomooProvider
        return MoomooProvider(
            host=os.getenv("MOOMOO_OPEND_HOST", "127.0.0.1"),
            port=int(os.getenv("MOOMOO_OPEND_PORT", "11111")),
            market=os.getenv("MOOMOO_MARKET", "US"),
        )
    from .yfinance_provider import YFinanceProvider
    return YFinanceProvider()
