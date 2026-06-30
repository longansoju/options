"""
Moomoo OpenD data provider — REAL option chains/quotes to replace BS estimates.

⚠️ UNVERIFIED IN THIS REPO YET: written against the moomoo-api SDK (v10.x) but not
yet run end-to-end here, because it requires Moomoo OpenD running and logged in.
Verify locally (OpenD up on 127.0.0.1:11111) before trusting its numbers.

Architecture
------------
Moomoo OpenD is a LOCAL gateway you run on your own machine (your moomoo login;
data encrypted/transmitted locally). This class connects to it via the quote
context only — DATA ONLY, no trade context, no password handling. Per moomoo's
security guidance the trade-unlock password is entered manually in OpenD and is
never given to or auto-filled by an AI agent.

Setup (on the machine where you trade)
-------------------------------------
1. Install + start Moomoo OpenD, log in, leave it listening on 127.0.0.1:11111.
2. pip install moomoo-api
3. Run the scanners there; they'll use real quotes when this provider is selected.

Symbols are mapped to moomoo's `MARKET.CODE` form (default market US → "US.AAPL").
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import List

import numpy as np
import pandas as pd

import config
from .base import (
    Chain, Event, Fundamentals, IVSeries, OptionContract, SmartMoneyTrade,
)

logger = logging.getLogger(__name__)

try:
    from moomoo import (
        OpenQuoteContext, RET_OK, KLType, AuType, OptionType as MmOptionType,
    )
    _HAS_MOOMOO = True
except Exception:  # SDK not installed in this environment
    _HAS_MOOMOO = False


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class MoomooProvider:
    """DataProvider backed by a local Moomoo OpenD gateway (quote context only)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 11111,
                 market: str = "US"):
        if not _HAS_MOOMOO:
            raise RuntimeError(
                "moomoo-api not installed. Run `pip install moomoo-api` on the "
                "machine where OpenD is running.")
        self._host, self._port, self._market = host, port, market
        self._ctx = None

    # ── connection ──────────────────────────────────────────────────────────

    def _quote(self) -> "OpenQuoteContext":
        if self._ctx is None:
            self._ctx = OpenQuoteContext(host=self._host, port=self._port)
        return self._ctx

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None

    def _mk(self, symbol: str) -> str:
        return symbol if "." in symbol else f"{self._market}.{symbol.upper()}"

    # ── option chain (the real-quote win) ───────────────────────────────────

    def options_chain(self, symbol: str) -> Chain:
        ctx = self._quote()
        code = self._mk(symbol)

        # spot
        ret, snap = ctx.get_market_snapshot([code])
        spot = float(snap["last_price"].iloc[0]) if (ret == RET_OK and len(snap)) else 0.0

        # expirations within the entry DTE window
        ret, exp_df = ctx.get_option_expiration_date(code=code)
        if ret != RET_OK or exp_df is None or len(exp_df) == 0:
            logger.warning("moomoo: no expirations for %s (ret=%s)", symbol, ret)
            return Chain(underlying=symbol, as_of=date.today(), spot_price=spot, contracts=[])

        today = date.today()
        expiries: list[str] = []
        for ds in exp_df["strike_time"].tolist():
            try:
                dte = (date.fromisoformat(ds) - today).days
            except Exception:
                continue
            if config.MIN_DTE_AT_ENTRY <= dte <= config.MAX_DTE_AT_ENTRY:
                expiries.append(ds)

        contracts: List[OptionContract] = []
        for exp in expiries:
            ret, chain_df = ctx.get_option_chain(code=code, start=exp, end=exp,
                                                 option_type=MmOptionType.ALL)
            if ret != RET_OK or chain_df is None or len(chain_df) == 0:
                continue

            # map static fields by option code; quotes/greeks come from snapshot
            static = {r["code"]: r for _, r in chain_df.iterrows()}
            opt_codes = list(static.keys())

            quotes: dict = {}
            for batch in _chunks(opt_codes, 200):  # snapshot batch cap
                ret, q = ctx.get_market_snapshot(batch)
                if ret == RET_OK and q is not None:
                    for _, r in q.iterrows():
                        quotes[r["code"]] = r

            for oc in opt_codes:
                s, q = static[oc], quotes.get(oc)
                try:
                    contracts.append(self._to_contract(symbol, oc, s, q))
                except Exception as e:
                    logger.debug("moomoo: skip %s: %s", oc, e)

        return Chain(underlying=symbol, as_of=today, spot_price=spot, contracts=contracts)

    def _to_contract(self, underlying, opt_code, static_row, q) -> OptionContract:
        def g(row, *names, default=0.0):
            if row is None:
                return default
            for n in names:
                if n in row and pd.notna(row[n]):
                    return row[n]
            return default

        otype = str(g(static_row, "option_type", default="")).upper()
        opt_type = "call" if "CALL" in otype else "put"
        strike = float(g(static_row, "strike_price"))
        exp_s = str(g(static_row, "strike_time", default=""))
        expiration = date.fromisoformat(exp_s[:10]) if exp_s else date.today()
        occ = opt_code.split(".", 1)[-1]  # "US.AAPL2608..." → "AAPL2608..."

        return OptionContract(
            symbol=occ, underlying=underlying, expiration=expiration,
            strike=strike, option_type=opt_type,
            bid=float(g(q, "bid_price")), ask=float(g(q, "ask_price")),
            last=float(g(q, "last_price")), volume=int(g(q, "volume", default=0) or 0),
            open_interest=int(g(q, "option_open_interest", default=0) or 0),
            implied_volatility=float(g(q, "option_implied_volatility")) / 100.0,
            delta=float(g(q, "option_delta", default=float("nan"))),
            gamma=float(g(q, "option_gamma", default=float("nan"))),
            theta=float(g(q, "option_theta", default=float("nan"))),
            vega=float(g(q, "option_vega", default=float("nan"))),
        )

    # ── price history ────────────────────────────────────────────────────────

    def price_history(self, symbol: str, lookback_days: int) -> pd.DataFrame:
        ctx = self._quote()
        code = self._mk(symbol)
        start = (date.today() - timedelta(days=lookback_days + 10)).isoformat()
        end = date.today().isoformat()
        ret, df, _page = ctx.request_history_kline(
            code=code, start=start, end=end, ktype=KLType.K_DAY,
            autype=AuType.QFQ, max_count=1000)
        if ret != RET_OK or df is None or len(df) == 0:
            logger.warning("moomoo: no kline for %s (ret=%s)", symbol, ret)
            return pd.DataFrame()
        out = pd.DataFrame({
            "Open": df["open"], "High": df["high"], "Low": df["low"],
            "Close": df["close"], "Volume": df["volume"],
        })
        out.index = pd.to_datetime(df["time_key"])
        out.index.name = "Date"
        return out

    # ── IV history: realized-vol proxy from real price history ────────────────

    def iv_history(self, symbol: str, lookback_days: int) -> IVSeries:
        df = self.price_history(symbol, lookback_days + 60)
        if df.empty or len(df) < 30:
            return IVSeries(symbol=symbol, dates=[], iv_values=[])
        logret = np.log(df["Close"] / df["Close"].shift(1))
        rv = (logret.rolling(21).std() * np.sqrt(252)).dropna()
        cutoff = date.today() - timedelta(days=lookback_days)
        dates, vals = [], []
        for ts, v in rv.items():
            d = ts.date() if hasattr(ts, "date") else ts
            if d >= cutoff:
                dates.append(d); vals.append(float(v))
        series = IVSeries(symbol=symbol, dates=dates, iv_values=vals)
        series._is_proxy = True
        return series

    # ── minimal/no-op for the rest of the protocol ───────────────────────────

    def fundamentals(self, symbol: str) -> Fundamentals:
        return Fundamentals(symbol=symbol, pe_ratio=None, pb_ratio=None,
                            market_cap=None, sector=None, industry=None)

    def earnings_calendar(self, symbol: str) -> List[Event]:
        return []

    def smart_money(self, symbol: str) -> List[SmartMoneyTrade]:
        return []
