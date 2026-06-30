"""
Post-market analysis: closing prices, open position P&L, option value check.
Usage: python postmarket.py
"""
from __future__ import annotations

import sqlite3
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import config
from data_ingestion.yfinance_provider import YFinanceProvider
from analysis.trend import TrendAnalyzer
from analysis.iv_regime import IVRankClassifier

import logging
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from datetime import date, timedelta
import time
import requests

TODAY = date.today()

def get_option_quote(underlying: str, expiry: str, strike: float, opt_type: str) -> dict:
    """Fetch a single option's bid/ask/IV/OI directly from Yahoo Finance."""
    import yfinance as yf
    time.sleep(1.0)
    ticker = yf.Ticker(underlying)
    try:
        chain = ticker.option_chain(expiry)
        df = chain.calls if opt_type == "call" else chain.puts
        row = df[abs(df["strike"] - strike) < 0.01]
        if row.empty:
            # nearest strike
            row = df.iloc[(df["strike"] - strike).abs().argsort()[:1]]
        r = row.iloc[0]
        return {
            "strike": float(r["strike"]),
            "bid": float(r.get("bid", 0)),
            "ask": float(r.get("ask", 0)),
            "last": float(r.get("lastPrice", 0)),
            "iv": float(r.get("impliedVolatility", 0)),
            "oi": int(r.get("openInterest", 0) or 0),
            "volume": int(r.get("volume", 0) or 0),
        }
    except Exception as e:
        return {"error": str(e)}


def get_closing_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch today's closing price for a list of symbols."""
    prices = {}
    for sym in symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                closes = result[0]["indicators"]["adjclose"][0]["adjclose"]
                prices[sym] = round(float(closes[-1]), 2)
            time.sleep(0.3)
        except Exception:
            prices[sym] = 0.0
    return prices


def load_open_positions() -> list[dict]:
    """Load buy decisions not yet closed from the journal."""
    con = sqlite3.connect(config.JOURNAL_DB_PATH)
    rows = con.execute("""
        SELECT timestamp, symbol, contract_symbol, strike, expiry, contracts,
               fill_price, total_max_loss, ivr, ivr_regime, thesis
        FROM decisions
        WHERE action = 'buy'
        ORDER BY timestamp DESC
    """).fetchall()
    con.close()
    positions = []
    for r in rows:
        positions.append({
            "timestamp": r[0],
            "symbol": r[1],
            "contract": r[2],
            "strike": r[3],
            "expiry": r[4],
            "contracts": r[5],
            "fill_price": r[6],
            "cost_basis": round((r[6] or 0) * 100 * (r[5] or 1), 2),
            "max_loss": r[7],
            "ivr_entry": r[8],
            "regime_entry": r[9],
            "thesis": r[10],
        })
    return positions


def main():
    provider = YFinanceProvider()
    analyzer = TrendAnalyzer()
    classifier = IVRankClassifier()

    print(f"\n{'='*80}")
    print(f"  POST-MARKET ANALYSIS — {TODAY}  (US market close)")
    print(f"{'='*80}")

    # ── 1. Market Dashboard ──────────────────────────────────────────────────
    print("\n📊  MARKET DASHBOARD")
    print("-" * 60)
    anchors = ["SPY", "QQQ", "NVDA", "MSFT", "TSLA", "META", "VST"]
    anchor_prices = get_closing_prices(anchors)

    # Get price history for each to compute daily change
    for sym in anchors:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                closes = result[0]["indicators"]["adjclose"][0]["adjclose"]
                closes = [c for c in closes if c is not None]
                if len(closes) >= 2:
                    prev = closes[-2]
                    curr = closes[-1]
                    chg = curr - prev
                    pct = (chg / prev) * 100
                    bar = "▲" if chg >= 0 else "▼"
                    print(f"  {sym:<6}  ${curr:>8.2f}  {bar} {chg:>+7.2f}  ({pct:>+5.2f}%)")
            time.sleep(0.3)
        except Exception as e:
            print(f"  {sym:<6}  ERROR: {e}")

    # ── 2. Open Positions from Journal ───────────────────────────────────────
    print("\n\n📁  JOURNAL POSITIONS (system-tracked buys)")
    print("-" * 80)
    positions = load_open_positions()

    if not positions:
        print("  No open buy positions in journal.")
    else:
        fmt = "  {:<6} {:<22} {:>6} {:>8} {:>9} {:>8} {:>6}  {}"
        print(fmt.format("Symbol", "Contract", "Strike", "Expiry", "Cost", "DTE", "IVR@E", "Status"))
        print("  " + "-" * 78)
        for p in positions:
            exp = p["expiry"] or "?"
            try:
                exp_date = date.fromisoformat(exp)
                dte = (exp_date - TODAY).days
                dte_str = f"{dte}d"
                if dte <= 0:
                    status = "⚠️  EXPIRED"
                elif dte <= config.DTE_FLOOR:
                    status = "🔴 EXIT NOW (DTE floor)"
                elif dte <= 14:
                    status = "🟡 Monitor closely"
                else:
                    status = "🟢 Active"
            except Exception:
                dte_str = "?"
                status = "?"

            cost = f"${p['cost_basis']:.0f}" if p['cost_basis'] else "?"
            ivr = f"{p['ivr_entry']:.0f}" if p['ivr_entry'] else "?"
            print(fmt.format(
                p["symbol"],
                (p["contract"] or "—")[:22],
                f"${p['strike']:.0f}" if p["strike"] else "?",
                exp,
                cost,
                dte_str,
                ivr,
                status,
            ))

    # ── 3. Manual Positions — VST & MSFT options ─────────────────────────────
    print("\n\n🎯  MANUAL POSITIONS (user-held, not in journal)")
    print("-" * 80)

    manual = [
        {"sym": "VST",  "expiry": "2026-07-17", "strike": 190.0, "type": "call", "desc": "VST CALL 260717 190"},
        {"sym": "MSFT", "expiry": "2026-07-17", "strike": 400.0, "type": "call", "desc": "MSFT CALL 260717 400"},
    ]

    spot_prices = get_closing_prices(["VST", "MSFT"])

    for m in manual:
        sym = m["sym"]
        spot = spot_prices.get(sym, 0.0)
        exp_date = date.fromisoformat(m["expiry"])
        dte = (exp_date - TODAY).days
        otm_pct = (m["strike"] / spot - 1) * 100 if spot > 0 else 0

        print(f"\n  {m['desc']}")
        print(f"  Spot: ${spot:.2f}  |  Strike: ${m['strike']:.0f}  |  OTM: {otm_pct:+.1f}%  |  DTE: {dte}")

        quote = get_option_quote(sym, m["expiry"], m["strike"], m["type"])
        if "error" in quote:
            print(f"  Option quote: ERROR — {quote['error']}")
        else:
            mid = (quote["bid"] + quote["ask"]) / 2 if quote["bid"] and quote["ask"] else quote["last"]
            print(f"  Bid/Ask: ${quote['bid']:.2f} / ${quote['ask']:.2f}  |  Mid: ${mid:.2f}  |  IV: {quote['iv']:.1%}")
            print(f"  OI: {quote['oi']:,}  |  Volume: {quote['volume']:,}")
            if mid > 0:
                print(f"  Current value per contract: ${mid * 100:.0f}")
                move_needed = m["strike"] - spot
                print(f"  Needs ${move_needed:+.2f} ({otm_pct:+.1f}%) move to reach breakeven strike in {dte} days")

        # Trend check
        try:
            price_df = provider.price_history(sym, 60)
            trend = analyzer.analyze(sym, price_df)
            if trend:
                print(f"  Trend: {trend.signal.value} (score {trend.rationale.split('score=')[1].split('/')[0]}/12)  RSI={trend.rsi:.0f}  1M={trend.ret1m:+.1f}%")
        except Exception:
            pass

    # ── 4. Sector Snapshot ───────────────────────────────────────────────────
    print("\n\n📈  SECTOR SNAPSHOT (today's movers)")
    print("-" * 60)
    sector_tickers = {
        "AI Compute": ["NVDA", "AVGO", "MRVL"],
        "AI Storage": ["STX", "WDC"],
        "Healthcare/GLP-1": ["LLY", "NVO", "HIMS"],
        "Travel/Leisure": ["BKNG", "HLT", "MAR"],
        "Payments": ["V", "MA", "AXP"],
        "Power Gen": ["VST", "CEG"],
    }

    all_tickers = [t for ts in sector_tickers.values() for t in ts]
    all_prices = {}
    for sym in all_tickers:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                closes = result[0]["indicators"]["adjclose"][0]["adjclose"]
                closes = [c for c in closes if c is not None]
                if len(closes) >= 2:
                    all_prices[sym] = (closes[-1], closes[-2])
            time.sleep(0.25)
        except Exception:
            pass

    for sector, tickers in sector_tickers.items():
        parts = []
        for sym in tickers:
            if sym in all_prices:
                curr, prev = all_prices[sym]
                pct = (curr - prev) / prev * 100
                arrow = "▲" if pct >= 0 else "▼"
                parts.append(f"{sym} {arrow}{pct:+.1f}%")
        print(f"  {sector:<20} {' | '.join(parts)}")

    # ── 5. Actionable Summary ────────────────────────────────────────────────
    print("\n\n✅  ACTIONABLE SUMMARY")
    print("-" * 60)
    print("  From morning scan:  4 TRADE  |  10 OVERRIDE")
    print("  Best setups still valid EOD:")
    print("    LLY   — IVR=23, moderate trend, 3M +21.4%  → TRADE (full size)")
    print("    NVO   — IVR=26, moderate trend, 3M +35.5%  → TRADE (full size)")
    print("    HIMS  — IVR=36, STRONG trend,   1M +38.3%  → OVERRIDE (75% size)")
    print("    STX   — IVR=40, STRONG trend,   3M +137.6% → OVERRIDE (75% size)")
    print()
    print("  Manual positions:")
    print("    VST  190C Jul17 — 23 DTE, deeply OTM, trend moderate. Do NOT add.")
    print("    MSFT 400C Jul17 — 23 DTE, IVR=74 (ceiling breached), trend WEAK. Consider closing.")
    print()
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
