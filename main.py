"""
Phase 1 spine: scan one symbol, compute IV Rank, select contract, size, execute, log.

Usage:
    python main.py --symbol AAPL --direction bullish
    python main.py --symbol TSLA --direction bearish --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import config
from analysis.iv_regime import IVRankClassifier, IVRegime
from analysis.trend import TrendAnalyzer, TrendSignal
from data_ingestion.base import Recommendation, Signal
from data_ingestion.yfinance_provider import YFinanceProvider
from decision_engine.selector import ContractSelector
from execution.alpaca_paper import AlpacaPaperBroker, Fill
from journal.logger import JournalLogger
from risk.sizing import GuardrailViolation, PositionSizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _check_entry_rules(symbol, direction, iv_result, events, trend_result=None):
    """
    Returns (allowed: bool, reason: str, risk_multiplier: float).

    Momentum override: when IVR is MEDIUM or HIGH-but-under-70, a strong
    price trend can unlock entry with reduced position size.
    """
    if iv_result is None:
        return False, "Could not compute IV Rank (no data).", 1.0

    ivr = iv_result.iv_rank

    # Hard ceiling — never buy above this IVR regardless of trend
    if ivr > config.IVR_MOMENTUM_OVERRIDE_MAX:
        return False, (
            f"IVR={ivr:.1f} exceeds hard ceiling of {config.IVR_MOMENTUM_OVERRIDE_MAX}. "
            "Premium too expensive even with strong trend."
        ), 1.0

    risk_mult = 1.0

    if iv_result.regime == IVRegime.HIGH:
        # IVR 50–70: only STRONG trend unlocks entry
        if trend_result is None or trend_result.signal != TrendSignal.STRONG:
            trend_desc = trend_result.signal.value if trend_result else "unknown"
            return False, (
                f"IVR={ivr:.1f} is HIGH. Momentum override requires STRONG trend "
                f"(got {trend_desc}). Stand aside."
            ), 1.0
        risk_mult = config.MOMENTUM_RISK_MULT_HIGH
        logger.info(
            "%s: MOMENTUM OVERRIDE (HIGH IVR) — trend=%s, sizing at %.0f%% normal risk",
            symbol, trend_result.signal.value, risk_mult * 100,
        )

    elif iv_result.regime == IVRegime.MEDIUM:
        # IVR 30–50: STRONG or MODERATE trend unlocks entry
        if trend_result is None or trend_result.signal == TrendSignal.WEAK:
            trend_desc = trend_result.signal.value if trend_result else "unknown"
            return False, (
                f"IVR={ivr:.1f} is MEDIUM and trend is {trend_desc}. Stand aside."
            ), 1.0
        if trend_result.signal == TrendSignal.NEUTRAL:
            return False, (
                f"IVR={ivr:.1f} is MEDIUM and trend is NEUTRAL. "
                "Need STRONG or MODERATE trend for momentum override."
            ), 1.0
        risk_mult = config.MOMENTUM_RISK_MULT_MEDIUM
        logger.info(
            "%s: MOMENTUM OVERRIDE (MEDIUM IVR) — trend=%s, sizing at %.0f%% normal risk",
            symbol, trend_result.signal.value, risk_mult * 100,
        )

    upcoming = [e for e in events if e.date >= date.today()]
    if not upcoming:
        logger.warning(
            "%s: no upcoming catalyst in earnings calendar — proceeding on trend thesis only.", symbol
        )

    if direction not in ("bullish", "bearish"):
        return False, f"Direction '{direction}' not supported in Phase 1.", 1.0

    return True, "Entry rules passed.", risk_mult


def _refuse(journal, symbol, structure, signals, reason, iv_result=None):
    rec = Recommendation(
        action="refuse",
        symbol=symbol,
        contract=None,
        structure=structure,
        max_loss=0.0,
        size=0,
        thesis=f"REFUSED: {reason}",
        signals=signals,
        guardrails_checked=True,
        refused_reason=reason,
    )
    journal.log_recommendation(
        rec,
        ivr=iv_result.iv_rank if iv_result else None,
        ivr_regime=iv_result.regime.value if iv_result else None,
        ivr_is_proxy=iv_result.is_proxy if iv_result else False,
    )
    logger.warning("REFUSED %s: %s", symbol, reason)


def scan(symbol: str, direction: str, dry_run: bool = False) -> None:
    provider = YFinanceProvider()
    classifier = IVRankClassifier()
    trend_analyzer = TrendAnalyzer()
    selector = ContractSelector()
    sizer = PositionSizer()
    journal = JournalLogger()

    logger.info("Scanning %s | direction=%s | dry_run=%s", symbol, direction, dry_run)

    # --- Data ingestion ---
    logger.info("Fetching options chain for %s …", symbol)
    chain = provider.options_chain(symbol)
    logger.info(
        "Fetched %d contracts across %d expirations",
        len(chain.contracts),
        len({c.expiration for c in chain.contracts}),
    )

    logger.info("Fetching IV history for %s …", symbol)
    iv_series = provider.iv_history(symbol, config.IV_RANK_LOOKBACK_DAYS)

    logger.info("Fetching earnings calendar for %s …", symbol)
    events = provider.earnings_calendar(symbol)
    for e in events:
        logger.info("  Catalyst: %s on %s (confirmed=%s)", e.event_type, e.date, e.confirmed)

    # --- IV Rank ---
    iv_result = classifier.classify(iv_series)
    if iv_result:
        logger.info("IV Rank: %s", iv_result.rationale)

    # --- Trend analysis (always run; used for momentum override) ---
    logger.info("Running trend analysis for %s …", symbol)
    price_df = provider.price_history(symbol, 300)
    trend_result = trend_analyzer.analyze(symbol, price_df)
    if trend_result:
        logger.info("Trend: %s", trend_result.rationale)

    # --- Strategy guardrail (C2/C3) ---
    structure = "long_call" if direction == "bullish" else "long_put"
    try:
        sizer.check_strategy(structure)
    except GuardrailViolation as exc:
        _refuse(journal, symbol, structure, [], str(exc))
        return

    # --- Entry rules (with momentum override) ---
    allowed, reason, risk_mult = _check_entry_rules(symbol, direction, iv_result, events, trend_result)
    if not allowed:
        signals = []
        if iv_result:
            signals.append(Signal(
                name="iv_rank", value=iv_result.iv_rank, direction="neutral",
                strength="strong", rationale=reason,
            ))
        _refuse(journal, symbol, structure, signals, reason, iv_result=iv_result)
        return

    # --- Contract selection ---
    contract = selector.select(chain, direction)
    if contract is None:
        reason = (
            f"No liquid contract found for {symbol} {direction} in "
            f"{config.MIN_DTE_AT_ENTRY}–{config.MAX_DTE_AT_ENTRY} DTE window."
        )
        _refuse(journal, symbol, structure, [], reason, iv_result=iv_result)
        return

    logger.info(
        "Selected: %s  strike=%.2f  DTE=%d  IV=%.1f%%  bid/ask=%.2f/%.2f  OI=%d  vol=%d  spread=%.1f%%",
        contract.symbol, contract.strike, contract.dte,
        contract.implied_volatility * 100,
        contract.bid, contract.ask, contract.open_interest, contract.volume,
        contract.spread_pct,
    )

    # --- Account info & position sizing ---
    broker: AlpacaPaperBroker | None = None
    if dry_run:
        account_equity = 10_000.0
        open_risk = 0.0
    else:
        broker = AlpacaPaperBroker()
        account_equity = broker.get_account_equity()
        open_risk = broker.get_open_position_risk()

    try:
        size = sizer.compute_size(contract, account_equity, open_risk, risk_multiplier=risk_mult)
    except GuardrailViolation as exc:
        _refuse(journal, symbol, structure, [], str(exc), iv_result=iv_result)
        return

    logger.info(
        "Size: %d contract(s)  max_loss=$%.2f (%.2f%% equity)  commission=$%.2f",
        size.contracts, size.total_max_loss, size.risk_pct_of_equity, size.commission,
    )

    # --- Build signals ---
    signals: list[Signal] = []
    if trend_result:
        signals.append(Signal(
            name="trend",
            value=trend_result.ret3m,
            direction=direction,
            strength=trend_result.signal.value,
            rationale=trend_result.rationale,
        ))
    if iv_result:
        signals.append(Signal(
            name="iv_rank",
            value=iv_result.iv_rank,
            direction=direction,
            strength="strong" if iv_result.iv_rank < 20 else "moderate",
            rationale=iv_result.rationale,
        ))

    upcoming = [e for e in events if e.date >= date.today()]
    if upcoming:
        next_cat = upcoming[0]
        days_away = (next_cat.date - date.today()).days
        signals.append(Signal(
            name="catalyst",
            value=float(days_away),
            direction=direction,
            strength="strong" if days_away <= 30 else "moderate",
            rationale=f"{next_cat.event_type} in {days_away} days on {next_cat.date}",
        ))

    ivr_str = f"IVR={iv_result.iv_rank:.1f}" if iv_result else "IVR=N/A"
    cat_str = (
        f" | {upcoming[0].event_type} in {(upcoming[0].date - date.today()).days}d"
        if upcoming else ""
    )
    thesis = (
        f"{direction.upper()} on {symbol}: {ivr_str} (LOW — cheap premium){cat_str}. "
        f"Buying {structure.replace('_', ' ')} {contract.symbol} "
        f"(strike={contract.strike}, DTE={contract.dte}, "
        f"IV={contract.implied_volatility:.1%}). "
        f"Max loss = ${size.total_max_loss:.2f}."
    )

    rec = Recommendation(
        action="buy",
        symbol=symbol,
        contract=contract,
        structure=structure,
        max_loss=size.total_max_loss,
        size=size.contracts,
        thesis=thesis,
        signals=signals,
        guardrails_checked=True,
    )

    # --- Execution ---
    fill: Fill | None = None
    if not dry_run and broker is not None:
        try:
            fill = broker.buy(contract, size)
            logger.info("Fill confirmed: order_id=%s", fill.order_id)
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            rec.action = "refuse"
            rec.refused_reason = f"Order failed: {exc}"

    # --- Journal ---
    decision_id = journal.log_recommendation(
        rec,
        ivr=iv_result.iv_rank if iv_result else None,
        ivr_regime=iv_result.regime.value if iv_result else None,
        ivr_is_proxy=iv_result.is_proxy if iv_result else False,
        fill=fill,
        risk_pct_equity=size.risk_pct_of_equity,
    )
    logger.info("Logged decision_id=%d to %s", decision_id, config.JOURNAL_DB_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="Options paper-trading agent — Phase 1 spine")
    parser.add_argument("--symbol", required=True, help="Underlying ticker, e.g. AAPL")
    parser.add_argument(
        "--direction", required=True, choices=["bullish", "bearish"],
        help="Directional thesis",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Alpaca order; uses $10k mock equity for sizing",
    )
    args = parser.parse_args()
    scan(args.symbol.upper(), args.direction, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
