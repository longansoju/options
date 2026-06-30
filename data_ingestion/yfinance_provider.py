from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from .base import (
    Chain, Event, Fundamentals, IVSeries, OptionContract,
    SmartMoneyTrade,
)
import config

logger = logging.getLogger(__name__)


def _parse_occ_date(occ_symbol: str) -> date:
    """Extract expiry date from OCC symbol like AAPL250117C00150000."""
    # last part: YYMMDD starting at position len(underlying)
    # find the date+type portion: 6 digits then C/P then 8 digits
    import re
    m = re.search(r"(\d{6})[CP](\d{8})$", occ_symbol)
    if not m:
        raise ValueError(f"Cannot parse OCC symbol: {occ_symbol}")
    yy, mm, dd = m.group(1)[:2], m.group(1)[2:4], m.group(1)[4:6]
    return date(2000 + int(yy), int(mm), int(dd))


def _yf_fetch(call, symbol: str, retries: int | None = None, delay: float | None = None, backoff: float | None = None):
    """Wrap a yfinance call with pre-call delay and exponential-backoff retry on empty/error."""
    retries = retries if retries is not None else config.YF_MAX_RETRIES
    delay   = delay   if delay   is not None else config.YF_INTER_CALL_DELAY
    backoff = backoff if backoff is not None else config.YF_RETRY_BACKOFF
    for attempt in range(retries):
        time.sleep(delay)
        try:
            result = call()
            if result is not None and (not hasattr(result, "empty") or not result.empty):
                return result
        except Exception as exc:
            logger.warning("%s: yfinance call failed (attempt %d/%d): %s", symbol, attempt + 1, retries, exc)
        if attempt < retries - 1:
            wait = delay * (backoff ** attempt)
            logger.warning(
                "%s: empty/error response (attempt %d/%d), retrying in %.1fs…",
                symbol, attempt + 1, retries, wait,
            )
            time.sleep(wait)
    logger.error("%s: all %d yfinance attempts exhausted", symbol, retries)
    return None


class YFinanceProvider:
    """DataProvider backed by yfinance (free, no API key required)."""

    def __init__(self, db_path: str = config.JOURNAL_DB_PATH):
        self._db_path = db_path
        self._ensure_iv_cache_table()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_iv_cache_table(self) -> None:
        import os
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        con = sqlite3.connect(self._db_path)
        con.execute(
            """CREATE TABLE IF NOT EXISTS iv_cache (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol   TEXT NOT NULL,
                date     TEXT NOT NULL,
                iv_value REAL NOT NULL,
                source   TEXT NOT NULL,
                UNIQUE(symbol, date)
            )"""
        )
        con.commit()
        con.close()

    def _store_iv(self, symbol: str, iv_date: date, iv_value: float, source: str) -> None:
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT OR REPLACE INTO iv_cache (symbol, date, iv_value, source) VALUES (?,?,?,?)",
            (symbol, iv_date.isoformat(), iv_value, source),
        )
        con.commit()
        con.close()

    def _load_iv_history(self, symbol: str, lookback_days: int) -> tuple[list[date], list[float]]:
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
        con = sqlite3.connect(self._db_path)
        rows = con.execute(
            "SELECT date, iv_value FROM iv_cache WHERE symbol=? AND date>=? ORDER BY date",
            (symbol, cutoff),
        ).fetchall()
        con.close()
        dates = [date.fromisoformat(r[0]) for r in rows]
        vals = [r[1] for r in rows]
        return dates, vals

    def _realized_vol_series(self, symbol: str, lookback_days: int) -> tuple[list[date], list[float]]:
        """Rolling 30-day realized vol as a proxy for IV when no cache exists."""
        df = self.price_history(symbol, lookback_days + 60)
        if df.empty or len(df) < 30:
            return [], []
        df["log_ret"] = np.log(df["Close"] / df["Close"].shift(1))
        window = 21  # ~30 calendar days of trading
        rv = df["log_ret"].rolling(window).std() * np.sqrt(252)
        rv = rv.dropna()
        dates_out = [d.date() if hasattr(d, "date") else d for d in rv.index.tolist()]
        vals_out = rv.tolist()
        # only keep the last lookback_days worth
        cutoff = date.today() - timedelta(days=lookback_days)
        pairs = [(d, v) for d, v in zip(dates_out, vals_out) if d >= cutoff]
        if not pairs:
            return [], []
        dates_out, vals_out = zip(*pairs)
        return list(dates_out), list(vals_out)

    # ------------------------------------------------------------------
    # DataProvider interface
    # ------------------------------------------------------------------

    def fundamentals(self, symbol: str) -> Fundamentals:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        return Fundamentals(
            symbol=symbol,
            pe_ratio=info.get("trailingPE"),
            pb_ratio=info.get("priceToBook"),
            market_cap=info.get("marketCap"),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )

    def options_chain(self, symbol: str) -> Chain:
        ticker = yf.Ticker(symbol)
        hist = _yf_fetch(lambda: ticker.history(period="1d"), symbol)
        spot = float(hist["Close"].iloc[-1]) if hist is not None and not hist.empty else 0.0

        expirations = ticker.options  # tuple of date strings
        contracts: List[OptionContract] = []

        for exp_str in expirations:
            exp_date = date.fromisoformat(exp_str)
            dte = (exp_date - date.today()).days
            if dte < config.MIN_DTE_AT_ENTRY or dte > config.MAX_DTE_AT_ENTRY:
                continue
            chain = _yf_fetch(lambda e=exp_str: ticker.option_chain(e), symbol)
            if chain is None:
                logger.warning("Failed fetching chain for %s %s after retries", symbol, exp_str)
                continue

            for df, opt_type in [(chain.calls, "call"), (chain.puts, "put")]:
                for _, row in df.iterrows():
                    try:
                        contracts.append(
                            OptionContract(
                                symbol=row["contractSymbol"],
                                underlying=symbol,
                                expiration=exp_date,
                                strike=float(row["strike"]),
                                option_type=opt_type,
                                bid=float(row.get("bid", 0)),
                                ask=float(row.get("ask", 0)),
                                last=float(row.get("lastPrice", 0)),
                                volume=int(row.get("volume", 0) or 0),
                                open_interest=int(row.get("openInterest", 0) or 0),
                                implied_volatility=float(row.get("impliedVolatility", 0)),
                                delta=None,  # yfinance doesn't provide Greeks
                                gamma=None,
                                theta=None,
                                vega=None,
                            )
                        )
                    except Exception as exc:
                        logger.debug("Skipping bad row for %s: %s", symbol, exc)

        result = Chain(underlying=symbol, as_of=date.today(), spot_price=spot, contracts=contracts)

        # Cache today's ATM IV
        atm = result.atm_iv("call")
        if atm and atm > 0:
            self._store_iv(symbol, date.today(), atm, "yfinance_atm")

        return result

    def price_history(self, symbol: str, lookback_days: int) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        period_str = f"{lookback_days + 5}d"
        df = _yf_fetch(lambda: ticker.history(period=period_str), symbol)
        return df if df is not None else pd.DataFrame()

    def iv_history(self, symbol: str, lookback_days: int) -> IVSeries:
        dates, vals = self._load_iv_history(symbol, lookback_days)

        if len(dates) >= config.IV_RANK_MIN_HISTORY_DAYS:
            series = IVSeries(symbol=symbol, dates=dates, iv_values=vals)
            series._is_proxy = False
            return series

        # Fall back to realized vol as proxy
        logger.info(
            "%s: only %d days of cached IV (need %d); using realized-vol proxy for IV Rank",
            symbol, len(dates), config.IV_RANK_MIN_HISTORY_DAYS,
        )
        rdates, rvals = self._realized_vol_series(symbol, lookback_days)
        if not rdates:
            return IVSeries(symbol=symbol, dates=[], iv_values=[])
        series = IVSeries(symbol=symbol, dates=list(rdates), iv_values=list(rvals))
        series._is_proxy = True
        return series

    def earnings_calendar(self, symbol: str) -> List[Event]:
        ticker = yf.Ticker(symbol)
        events: List[Event] = []
        try:
            cal = ticker.calendar
            if cal is None:
                return events
            # yfinance calendar varies by version; handle both dict and DataFrame
            if isinstance(cal, dict):
                earnings_date = cal.get("Earnings Date")
                if earnings_date:
                    if hasattr(earnings_date, "__iter__") and not isinstance(earnings_date, str):
                        for ed in earnings_date:
                            d = ed.date() if hasattr(ed, "date") else ed
                            events.append(Event(symbol=symbol, event_type="earnings", date=d, confirmed=False))
                    else:
                        d = earnings_date.date() if hasattr(earnings_date, "date") else earnings_date
                        events.append(Event(symbol=symbol, event_type="earnings", date=d, confirmed=False))
            elif isinstance(cal, pd.DataFrame):
                if "Earnings Date" in cal.columns:
                    for val in cal["Earnings Date"].dropna():
                        d = val.date() if hasattr(val, "date") else val
                        events.append(Event(symbol=symbol, event_type="earnings", date=d, confirmed=False))
        except Exception as exc:
            logger.debug("Earnings calendar failed for %s: %s", symbol, exc)
        return events

    def smart_money(self, symbol: str) -> List[SmartMoneyTrade]:
        # yfinance does not provide congressional/insider data
        # Phase 2 will wire in Quiver Quantitative or similar
        return []
