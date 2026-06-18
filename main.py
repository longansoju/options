"""
Phase 1 spine: scan one symbol, compute IV Rank, select contract, size, execute, log.

Usage:
    python main.py --symbol AAPL --direction bullish
    python main.py --symbol TSLA --direction bearish
    python main.py --symbol SPY  --direction bullish --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import config
from analysis.iv_regime import IVRankClassifier, IVRegime
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


def _check_entry_rules(
    symbol: str,
    direction: str,
    iv_result,
    events,
) -> tuple[bool, str]:
    """
    Returns (allowed: bool, reason: str).
    Entry is blocked if any hard entry rule fails.
    """
    # Rule 1: IVR must be LOW
    if iv_result is None:
        return False, "Could not compute IV Rank (no data)."

    if iv_result.regime == IVRegime.HIGH:
        return False, (
            f"IVR={iv_result.iv_rank:.1f} is HIGH (>{config.IVR_HIGH_THRESHOLD}). "
            "Options are expensive. Refusing naked long to avoid buying into inflated premium."
        )

    if iv_result.regime == IVRegime.MEDIUM:
        return False, (
            f"IVR={iv_result.iv_rank:.1f} is MEDIUM. Entry requires LOW IVR "
            f"(< {config.IVR_LOW_THRESHOLD}). Stand aside."
        )

    # Rule 2: Warn if no catalyst found (not a hard block — directional trades allowed)
    upcoming = [e for e in events if e.date >= date.today()]
    if not upcoming:
        logger.warning("%s: no upcoming catalyst found in earnings calendar. "
                       "Proceeding on directional thesis only.", symbol)

    # Rule 3: direction must be bullish or bearish (not neutral for Phase 1)
    if direction not in ("bullish", "bearish"):
        return False, f"Direction '{direction}' not supported in Phase 1 (use bullish/bearish)."

    return True, "Entry rules passed."


def scan(symbol: str, direction: str, dry_run: bool = False) -> None:
    provider = YFinanceProvider()
    classifier = IVRankClassifier()
    selector = ContractSelector()
    sizer = PositionSizer()
    journal = JournalLogger()

    logger.info("Scanning %s | direction=%s | dry_run=%s", symbol, direction, dry_run)

    # --- Data ingestion ---
    logger.info("Fetching options chain for %s …", symbol)
    chain = provider.options_chain(symbol)
    logger.info("Fetched %d contracts across %d expirations", len(chain.contracts),
                len({c.expiration for c in chain.contracts}))

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

    # --- Entry rules ---
    structure = "long_call" if direction == "bullish" else "long_put"
    try:
        sizer.check_strategy(structure)
    except GuardrailViolation as exc:
        _refuse(journal, symbol, structure, [], str(exc))
        return

    allowed, reason = _check_entry_rules(symbol, direction, iv_result, events)
    if not allowed:
        _refuse(journal, symbol, structure,
                [Signal("iv_rank", iv_result.iv_rank if iv_result else 0, "neutral",
                        "strong", reason)],
                reason,
                iv_result=iv_result)
        return

    # --- Contract selection ---
    contract = selector.select(chain, direction)
    if contract is None:
        reason = (f"No liquid contract found for {symbol} {direction} in "
                  f"{config.MIN_DTE_AT_ENTRY}–{config.MAX_DTE_AT_ENTRY} DTE window.")
        _refuse(journal, symbol, structure, [], reason, iv_result=iv_result)
        return

    logger.info(
        "Selected contract: %s  strike=%.2f  DTE=%d  IV=%.2%%  bid/ask=%.2f/%.2f  "
        "OI=%d  vol=%d  spread=%.1f%%",
        contract.symbol, contract.strike, contract.dte,
        contract.implied_volatility,
        contract.bid, contract.ask, contract.open_interest, contract.volume,
        contract.spread_pct,
    )

    # --- Position sizing ---
    if dry_run:
        account_equity = 10_000.0
        open_risk = 0.0
    else:
        broker = AlpacaPaperBroker()
        account_equity = broker.get_account_equity()
        open_risk = broker.get_open_position_risk()

    try:
        size = sizer.compute_size(contract, account_equity, open_risk)
    except GuardrailViolation as exc:
        _refuse(journal, symbol, structure, [], str(exc), iv_result=iv_result)
        return

    logger.info(
        "Size: %d contract(s), max_loss=$%.2f (%.2f%% of equity), commission=$%.2f",
        size.contracts, size.total_max_loss, size.risk_pct_of_equity, size.commission,
    )

    # --- Build signals & recommendation ---
    signals: list[Signal] = []
    if iv_result:
        signals.append(Signal(
            name="iv_rank",
            value=iv_result.iv_rank,
            direction="bullish" if direction == "bullish" else "bearish",
            strength="strong" if iv_result.iv_rank < 20 else "moderate",
            rationale=iv_result.rationale,
        ))

    upcoming_catalysts = [e for e in events if e.date >= date.today()]
    if upcoming_catalysts:
        next_cat = upcoming_catalysts[0]
        days_to_cat = (next_cat.date - date.today()).days
        signals.append(Signal(
            name="catalyst",
            value=float(days_to_cat),
            direction=direction,
            strength="strong" if days_to_cat <= 30 else "moderate",
            rationale=f"{next_cat.event_type} in {days_to_cat} days on {next_cat.date}",
        ))

    ivr_str = f"IVR={iv_result.iv_rank:.1f}" if iv_result else "IVR=N/A"
    next_cat_str = (f" | {upcoming_catalysts[0].event_type} in "
                    f"{(upcoming_catalysts[0].date - date.today()).days}d"
                    if upcoming_catalysts else "")
    thesis = (
        f"{direction.upper()} on {symbol}: {ivr_str} (LOW — cheap premium){next_cat_str}. "
        f"Buying {structure.replace('_', ' ')} {contract.symbol} "
        f"(strike={contract.strike}, DTE={contract.dte}, IV={contract.implied_volatility:.1%}). "
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
    if not dry_run:
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
    logger.info("Logged decision_id=%d", decision_id)


def _refuse(
    journal: JournalLogger,
    symbol: str,
    structure: str,
    signals: list,
    reason: str,
    iv_result=None,
) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Options paper-trading agent — Phase 1 spine")
    parser.add_argument("--symbol", required=True, help="Underlying ticker, e.g. AAPL")
    parser.add_argument(
        "--direction", required=True, choices=["bullish", "bearish"],
        help="Directional thesis"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Alpaca order submission; uses $10k mock equity"
    )
    args = parser.parse_args()
    scan(args.symbol.upper(), args.direction, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
