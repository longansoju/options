"""
Position / recommendation review — reads from the DB, no re-scan.

Backs the standing rule (CLAUDE.md → Session routine): before new analysis,
re-check every open recommendation and report how it has moved. Movement is read
from the latest scan_history snapshot, so run a scanner first to refresh prices.

Usage:
    python review_positions.py                 # review all OPEN recs
    python review_positions.py list            # everything incl. closed
    python review_positions.py add  --symbol MAR --strategy swing --dir call \\
        --strike 420 --expiry 2026-08-07 --ref 375.20 [--prem 5.20] [--thesis "..."]
    python review_positions.py close --occ MAR260807C00420000 --prem 6.10 \\
        [--ref 392.0] [--status closed|expired|skipped] [--notes "..."]
"""
from __future__ import annotations

import argparse
import math
from datetime import date

from journal.research_log import ResearchLog
from scan_momentum import bs_price


def _est_premium(rl: ResearchLog, symbol: str, strike: float, direction: str, dte: int):
    """Estimate current per-contract premium from the latest snapshot carrying RV."""
    snap = rl.latest_snapshot(symbol, require_rv=True)
    if snap is None or snap["price"] is None or snap["rv"] is None or dte <= 0:
        return None
    return bs_price(snap["price"], strike, dte / 365.0, snap["rv"], direction) * 100


def review(rl: ResearchLog, status: str = "open") -> None:
    recs = rl.recommendations(status=status) if status else rl.recommendations(status=None)
    if not recs:
        print(f"No {status or 'recorded'} recommendations.")
        return

    today = date.today()
    print(f"\nPosition review — {today}  |  status={status or 'ALL'}")
    print("=" * 116)
    hdr = "{:<22} {:<5} {:>4} {:>5} {:>10} {:>7} {:>6} {:>5} {:>5}  {}"
    print(hdr.format("OCC", "Strat", "DTE", "Strk", "Ref→Now", "Move%", "IVR/Ig", "Trnd", "RSI", "Moneyness / status"))
    print("-" * 116)

    for r in recs:
        sym, d = r["symbol"], r["direction"]
        snap = rl.latest_snapshot(sym)
        now_px = snap["price"] if snap else None
        dte = (date.fromisoformat(r["expiry"]) - today).days

        ref = r["entry_ref_price"]
        move = f"{(now_px/ref - 1)*100:+.1f}" if (ref and now_px) else "-"
        refnow = f"{ref or 0:.0f}→{now_px:.0f}" if now_px else f"{ref or 0:.0f}→?"

        ivr_ig = "-"
        trend = rsi = "-"
        if snap:
            if snap["ignition"] is not None:
                ivr_ig = f"ig{snap['ignition']:.0f}"
            elif snap["ivr"] is not None:
                ivr_ig = f"{snap['ivr']:.0f}"
            trend = (snap["trend_signal"] or "-")[:4]
            rsi = f"{snap['rsi']:.0f}" if snap["rsi"] is not None else "-"

        # moneyness
        if now_px is None:
            money = "no snapshot — run a scan"
        else:
            itm = (now_px > r["strike"]) if d == "call" else (now_px < r["strike"])
            gap = (r["strike"]/now_px - 1)*100 if d == "call" else (1 - r["strike"]/now_px)*100
            money = ("ITM" if itm else f"{gap:+.1f}% to strike")

        # premium estimate (entry → est now)
        est = _est_premium(rl, sym, r["strike"], d, dte)
        if r["entry_premium"] and est is not None:
            money += f" | prem {r['entry_premium']:.0f}→~{est:.0f} ({(est/r['entry_premium']-1)*100:+.0f}%)"
        elif est is not None:
            money += f" | ~${est:.0f} est"

        flag = "⚠️ " if dte <= 7 else ("· " if dte <= 21 else "  ")
        print(hdr.format(r["occ_code"], r["strategy"][:5], f"{flag}{dte}", f"{r['strike']:.0f}",
                         refnow, move, ivr_ig, trend, rsi, money))
        if r["thesis"]:
            print(f"    thesis: {r['thesis']}")

    print("=" * 116)
    print("DTE flags: ⚠️ ≤7 (theta danger)  · ≤21 (swing exit zone).  "
          "Premium est uses realized-vol proxy — ballpark, not a quote.")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("review")
    sub.add_parser("list")

    a = sub.add_parser("add")
    a.add_argument("--symbol", required=True)
    a.add_argument("--strategy", required=True, choices=["swing", "momentum"])
    a.add_argument("--dir", required=True, choices=["call", "put"])
    a.add_argument("--strike", required=True, type=float)
    a.add_argument("--expiry", required=True, help="YYYY-MM-DD")
    a.add_argument("--ref", type=float, default=None, help="underlying price at entry")
    a.add_argument("--prem", type=float, default=None, help="per-contract premium")
    a.add_argument("--thesis", default=None)
    a.add_argument("--held", action="store_true", help="mark as actually held (not just a rec)")

    c = sub.add_parser("close")
    c.add_argument("--occ", required=True)
    c.add_argument("--prem", type=float, default=None, help="exit per-contract premium")
    c.add_argument("--ref", type=float, default=None, help="underlying price at exit")
    c.add_argument("--status", default="closed", choices=["closed", "expired", "skipped"])
    c.add_argument("--notes", default=None)

    args = p.parse_args()
    rl = ResearchLog()

    if args.cmd == "add":
        thesis = args.thesis
        if args.held:
            thesis = (thesis + " " if thesis else "") + "[HELD]"
        code = rl.add_recommendation(
            args.symbol, args.strategy, args.dir, args.strike, args.expiry,
            entry_ref_price=args.ref, entry_premium=args.prem, thesis=thesis)
        print(f"added {code}")
    elif args.cmd == "close":
        ok = rl.close_recommendation(
            args.occ, exit_premium=args.prem, exit_ref_price=args.ref,
            status=args.status, notes=args.notes)
        print(f"closed {args.occ}" if ok else f"no open rec with OCC {args.occ}")
    elif args.cmd == "list":
        review(rl, status=None)
    else:
        review(rl, status="open")


if __name__ == "__main__":
    main()
