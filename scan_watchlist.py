"""
Daily watchlist scan: IVR + trend for all tickers in config.WATCHLIST and DIVERSIFICATION.
No options chain fetching — uses price history + cached IV only.

Usage:
    python scan_watchlist.py
    python scan_watchlist.py --direction bullish
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import config
from analysis.iv_regime import IVRankClassifier, IVRegime
from analysis.trend import TrendAnalyzer, TrendSignal
from data_ingestion.yfinance_provider import YFinanceProvider
from journal.research_log import ResearchLog

import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")


def regime_label(iv_result, trend_result, direction="bullish"):
    """Return TRADE / OVERRIDE / WATCH / SKIP and reason string."""
    if iv_result is None:
        return "NO DATA", "-"
    ivr = iv_result.iv_rank
    sig = trend_result.signal if trend_result else None

    if ivr > config.IVR_MOMENTUM_OVERRIDE_MAX:
        return "SKIP", f"IVR={ivr:.0f} (>70 ceiling)"

    if direction == "bearish":
        # For puts: LOW IVR = cheap, always trade; MEDIUM/HIGH need confirmed downtrend
        if iv_result.regime == IVRegime.LOW:
            return "TRADE", f"IVR={ivr:.0f} LOW | trend={sig.value if sig else '?'}"
        if iv_result.regime == IVRegime.MEDIUM:
            if sig in (TrendSignal.WEAK, TrendSignal.NEUTRAL):
                return "OVERRIDE", f"IVR={ivr:.0f} MED | trend={sig.value} → 75% size"
            return "WATCH", f"IVR={ivr:.0f} MED | trend={sig.value if sig else '?'} (uptrend)"
        if iv_result.regime == IVRegime.HIGH:
            if sig == TrendSignal.WEAK:
                return "OVERRIDE", f"IVR={ivr:.0f} HIGH | trend=WEAK → 50% size"
            return "SKIP", f"IVR={ivr:.0f} HIGH | need WEAK trend for puts"
        return "WATCH", "-"

    # bullish
    if iv_result.regime == IVRegime.LOW:
        return "TRADE", f"IVR={ivr:.0f} LOW | trend={sig.value if sig else '?'}"
    if iv_result.regime == IVRegime.MEDIUM:
        if sig in (TrendSignal.STRONG, TrendSignal.MODERATE):
            return "OVERRIDE", f"IVR={ivr:.0f} MED | trend={sig.value} → 75% size"
        return "WATCH", f"IVR={ivr:.0f} MED | trend={sig.value if sig else '?'} (weak)"
    if iv_result.regime == IVRegime.HIGH:
        if sig == TrendSignal.STRONG:
            return "OVERRIDE", f"IVR={ivr:.0f} HIGH | trend=STRONG → 50% size"
        return "SKIP", f"IVR={ivr:.0f} HIGH | need STRONG trend"

    return "WATCH", "-"


def entry_score(iv_result, trend_result, direction="bullish") -> tuple[int, str]:
    """
    Timing-adjusted entry score for ranking TRADE/OVERRIDE candidates.

    Bullish adjustments (base = raw trend score):
      +2  near_hl        — at HL dip-buy zone
      +1  RSI < 55       — momentum reset
      -1  RSI 65–74      — extended
      -2  RSI ≥ 75       — overbought
      -1  1M ret > 25%   — chasing surge

    Bearish adjustments (base = 14 - raw trend score, inverts bullish bias):
      +2  near_lh        — price near last swing HIGH (overhead resistance)
      +1  RSI > 65       — momentum extended, mean-reversion setup
      -1  RSI < 40       — oversold, put premium elevated / bounce risk
      -1  1M ret < -25%  — already crashed, chasing the drop

    Both directions:
      -1  IVR MEDIUM     — elevated premium cost
      -2  IVR HIGH       — expensive premium at 50% size
    """
    if trend_result is None:
        return 0, ""

    try:
        base_bullish = int(trend_result.rationale.split("score=")[1].split("/")[0])
    except (IndexError, ValueError):
        base_bullish = 0

    flags = []
    adj = 0

    if direction == "bearish":
        # Invert: weak trend score = good for puts
        base = 14 - base_bullish

        rsi = trend_result.rsi
        if rsi > 65:
            adj += 1
            flags.append("RSI-ext+1")
        elif rsi < 40:
            adj -= 1
            flags.append("RSI-OS-1")

        if trend_result.ret1m < -25:
            adj -= 1
            flags.append("1M-crash-1")

        # near last swing HIGH = overhead resistance = good put entry
        structure = getattr(trend_result, "structure", "")
        if structure in ("weakening", "downtrend"):
            adj += 1
            flags.append("struct-down+1")

    else:
        base = base_bullish

        if getattr(trend_result, "near_hl", False):
            adj += 2
            flags.append("HL-zone+2")

        rsi = trend_result.rsi
        if rsi < 55:
            adj += 1
            flags.append("RSI-reset+1")
        elif rsi >= 75:
            adj -= 2
            flags.append("RSI-OB-2")
        elif rsi >= 65:
            adj -= 1
            flags.append("RSI-ext-1")

        if trend_result.ret1m > 25:
            adj -= 1
            flags.append("1M-chase-1")

    if iv_result is not None:
        if iv_result.regime == IVRegime.MEDIUM:
            adj -= 1
            flags.append("IVR-MED-1")
        elif iv_result.regime == IVRegime.HIGH:
            adj -= 2
            flags.append("IVR-HIGH-2")

    return base + adj, " ".join(flags)


def scan_all(direction: str = "bullish", log: bool = True):
    provider = YFinanceProvider()
    classifier = IVRankClassifier()
    analyzer = TrendAnalyzer()
    rlog = ResearchLog() if log else None

    tickers = list(dict.fromkeys(
        config.WATCHLIST
        + [t for ts in config.DIVERSIFICATION.values() for t in ts]
    ))

    print(f"\nDaily Watchlist Scan — {__import__('datetime').date.today()}  |  direction={direction}")
    print("=" * 110)
    fmt = "{:<6} {:>8}  {:>5}  {:>8}  {:>7}  {:>6}  {:>6}  {:>6}  {:>5}  {}"
    print(fmt.format("Symbol", "Price", "IVR", "Regime", "Trend", "Score", "1M%", "3M%", "RSI", "Verdict"))
    print("-" * 110)

    results = []
    for sym in tickers:
        try:
            price_df = provider.price_history(sym, 300)
            iv_series = provider.iv_history(sym, config.IV_RANK_LOOKBACK_DAYS)
        except Exception as e:
            results.append((sym, None, None, f"ERROR: {e}"))
            continue

        iv_result = classifier.classify(iv_series) if iv_series.iv_values else None
        trend_result = analyzer.analyze(sym, price_df) if not price_df.empty else None

        results.append((sym, iv_result, trend_result, None))

    # Primary sort: TRADE → OVERRIDE → WATCH → SKIP → NO DATA
    # Secondary sort within TRADE/OVERRIDE: timing-adjusted entry score (desc)
    verdict_order = {"TRADE": 0, "OVERRIDE": 1, "WATCH": 2, "SKIP": 3, "NO DATA": 4}

    def sort_key(r):
        sym, iv, tr, err = r
        v, _ = regime_label(iv, tr, direction)
        es, _ = entry_score(iv, tr, direction) if v in ("TRADE", "OVERRIDE") else (0, "")
        return (verdict_order.get(v, 5), -es)

    results.sort(key=sort_key)

    trade_recs = []
    override_recs = []

    for sym, iv_result, trend_result, err in results:
        if err:
            print(fmt.format(sym, "-", "-", "-", "-", "-", "-", "-", "-", err))
            continue

        price    = f"${trend_result.price:.2f}" if trend_result else "N/A"
        ivr      = f"{iv_result.iv_rank:.0f}" if iv_result else "N/A"
        proxy    = "~" if (iv_result and iv_result.is_proxy) else ""
        regime   = (iv_result.regime.value.upper() + proxy) if iv_result else "N/A"
        trend    = trend_result.signal.value if trend_result else "N/A"
        ret1m    = f"{trend_result.ret1m:+.1f}" if trend_result else "-"
        ret3m    = f"{trend_result.ret3m:+.1f}" if trend_result else "-"
        rsi      = f"{trend_result.rsi:.0f}" if trend_result else "-"

        if trend_result:
            score_str = trend_result.rationale.split("score=")[1].split("/")[0] if "score=" in trend_result.rationale else "?"
        else:
            score_str = "-"

        verdict, detail = regime_label(iv_result, trend_result, direction)
        print(fmt.format(sym, price, ivr + proxy, regime, trend, score_str, ret1m, ret3m, rsi, verdict + " | " + detail))

        if rlog is not None:
            es, es_flags = entry_score(iv_result, trend_result, direction)
            try:
                rlog.log_scan_row(
                    "swing", sym, direction=direction,
                    price=trend_result.price if trend_result else None,
                    ivr=iv_result.iv_rank if iv_result else None,
                    ivr_regime=iv_result.regime.value if iv_result else None,
                    ivr_is_proxy=iv_result.is_proxy if iv_result else None,
                    trend_signal=trend_result.signal.value if trend_result else None,
                    trend_score=int(score_str) if score_str.isdigit() else None,
                    rsi=trend_result.rsi if trend_result else None,
                    ret1m=trend_result.ret1m if trend_result else None,
                    ret3m=trend_result.ret3m if trend_result else None,
                    entry_score=es, verdict=verdict, flags=es_flags,
                )
            except Exception as e:
                logging.warning("scan_history log failed for %s: %s", sym, e)

        if verdict == "TRADE":
            trade_recs.append((sym, iv_result, trend_result))
        elif verdict == "OVERRIDE":
            override_recs.append((sym, iv_result, trend_result))

    print("=" * 110)
    print(f"\nSUMMARY: {len(trade_recs)} TRADE  |  {len(override_recs)} OVERRIDE  |  direction={direction}")

    if trade_recs or override_recs:
        print("\nACTIONABLE — ranked by timing-adjusted entry score:")
        print(f"  {'Sym':<6} {'Price':>8}  {'IVR':<4}  {'Trend':<8}  {'Entry':>5}  {'1M':>7}  {'3M':>7}  {'RSI':>4}  Timing flags")
        print(f"  {'-'*6} {'-'*8}  {'-'*4}  {'-'*8}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*4}  {'-'*30}")
        all_recs = trade_recs + override_recs
        all_recs.sort(key=lambda r: -entry_score(r[1], r[2], direction)[0])
        for sym, iv, tr in all_recs:
            ivr_v  = f"{iv.iv_rank:.0f}" if iv else "?"
            sig_v  = tr.signal.value if tr else "?"
            r1     = f"{tr.ret1m:+.1f}%" if tr else ""
            r3     = f"{tr.ret3m:+.1f}%" if tr else ""
            px     = f"${tr.price:.2f}" if tr else ""
            rsi_v  = f"{tr.rsi:.0f}" if tr else ""
            es, flags = entry_score(iv, tr, direction)
            hl_tag = " ← HL zone" if (direction == "bullish" and getattr(tr, "near_hl", False)) else ""
            print(f"  {sym:<6} {px:>8}  IVR={ivr_v:<3}  {sig_v:<8}  {es:>5}  {r1:>7}  {r3:>7}  {rsi_v:>4}  {flags}{hl_tag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", default="bullish", choices=["bullish", "bearish"])
    parser.add_argument("--no-log", action="store_true", help="skip writing snapshots to scan_history")
    args = parser.parse_args()
    scan_all(args.direction, log=not args.no_log)
