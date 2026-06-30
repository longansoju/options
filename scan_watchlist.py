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
from analysis.iv_regime import IVRankClassifier
from analysis.trend import TrendAnalyzer, TrendSignal
from data_ingestion.yfinance_provider import YFinanceProvider

import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")


def regime_label(iv_result, trend_result):
    """Return TRADE / OVERRIDE / WATCH / SKIP and color hint."""
    if iv_result is None:
        return "NO DATA", "-"
    ivr = iv_result.iv_rank
    sig = trend_result.signal if trend_result else None

    if ivr > config.IVR_MOMENTUM_OVERRIDE_MAX:
        return "SKIP", f"IVR={ivr:.0f} (>70 ceiling)"

    from analysis.iv_regime import IVRegime
    if iv_result.regime == IVRegime.LOW:
        trend_str = sig.value if sig else "?"
        return "TRADE", f"IVR={ivr:.0f} LOW | trend={trend_str}"

    if iv_result.regime == IVRegime.MEDIUM:
        if sig in (TrendSignal.STRONG, TrendSignal.MODERATE):
            return "OVERRIDE", f"IVR={ivr:.0f} MED | trend={sig.value} → 75% size"
        return "WATCH", f"IVR={ivr:.0f} MED | trend={sig.value if sig else '?'} (weak)"

    if iv_result.regime == IVRegime.HIGH:
        if sig == TrendSignal.STRONG:
            return "OVERRIDE", f"IVR={ivr:.0f} HIGH | trend=STRONG → 50% size"
        return "SKIP", f"IVR={ivr:.0f} HIGH | need STRONG trend"

    return "WATCH", "-"


def scan_all(direction: str = "bullish"):
    provider = YFinanceProvider()
    classifier = IVRankClassifier()
    analyzer = TrendAnalyzer()

    # Build flat ticker list (watchlist + diversification), deduplicated
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

    # Sort: TRADE first, then OVERRIDE, WATCH, SKIP, NO DATA
    order = {"TRADE": 0, "OVERRIDE": 1, "WATCH": 2, "SKIP": 3, "NO DATA": 4}
    results.sort(key=lambda r: order.get(regime_label(r[1], r[2])[0], 5))

    trade_recs = []
    override_recs = []

    for sym, iv_result, trend_result, err in results:
        if err:
            print(fmt.format(sym, "-", "-", "-", "-", "-", "-", "-", "-", err))
            continue

        price = f"${trend_result.price:.2f}" if trend_result else "N/A"
        ivr   = f"{iv_result.iv_rank:.0f}" if iv_result else "N/A"
        proxy = "~" if (iv_result and iv_result.is_proxy) else ""
        regime = (iv_result.regime.value.upper() + proxy) if iv_result else "N/A"
        trend  = trend_result.signal.value if trend_result else "N/A"
        score  = str(getattr(trend_result, '_score', '?')) if trend_result else "-"
        ret1m  = f"{trend_result.ret1m:+.1f}" if trend_result else "-"
        ret3m  = f"{trend_result.ret3m:+.1f}" if trend_result else "-"
        rsi    = f"{trend_result.rsi:.0f}" if trend_result else "-"

        # Recompute score from trend rationale
        if trend_result:
            score_str = trend_result.rationale.split("score=")[1].split("/")[0] if "score=" in trend_result.rationale else "?"
        else:
            score_str = "-"

        verdict, detail = regime_label(iv_result, trend_result)

        print(fmt.format(sym, price, ivr + proxy, regime, trend, score_str, ret1m, ret3m, rsi, verdict + " | " + detail))

        if verdict == "TRADE":
            trade_recs.append((sym, iv_result, trend_result))
        elif verdict == "OVERRIDE":
            override_recs.append((sym, iv_result, trend_result))

    print("=" * 110)
    print(f"\nSUMMARY: {len(trade_recs)} TRADE  |  {len(override_recs)} OVERRIDE  |  direction={direction}")

    if trade_recs or override_recs:
        print("\nACTIONABLE (IVR < 70, trend supports entry):")
        for sym, iv, tr in (trade_recs + override_recs):
            ivr_v = f"{iv.iv_rank:.0f}" if iv else "?"
            sig_v = tr.signal.value if tr else "?"
            r1 = f"{tr.ret1m:+.1f}%" if tr else ""
            r3 = f"{tr.ret3m:+.1f}%" if tr else ""
            px = f"${tr.price:.2f}" if tr else ""
            print(f"  {sym:<6} {px:>8}  IVR={ivr_v:<3}  trend={sig_v:<8}  1M={r1:<8} 3M={r3}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", default="bullish", choices=["bullish", "bearish"])
    args = parser.parse_args()
    scan_all(args.direction)
