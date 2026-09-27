"""
Event & volatility radar — WHEN is a big move likely (not which way).

Two modes, both backed by walk-forward-validated models in analysis/event_radar.py:

    --mode open    pre-market, best 09:15-09:28 ET (21:15-21:28 SGT).
                   P(a 0.3-sigma weekly call / put bought at the open touches +50%
                   within the first hour). Top decile touches 36-42% vs a 25% base.
    --mode close   near the close. P(next open gaps up / down by > 1 gap-sd).
                   Flags FOMC nights (2024-26 regime: +1.22% avg next gap, 73% up).

HONESTY: the models find BIG-MOVE days; they do not find direction (open-model
direction AUC 0.514). The output labels a lean only with that caveat. Everything
here is "watch — volatility radar", never an entry. Use it to (1) know which
names to be ready on with a RESTING +50% limit, and (2) avoid opening fresh
short-dated premium into a flagged open or overnight.

The close radar is timing-constrained for a GMT+8 trader: the US close is
04:00 SGT. It is most useful for positions already held (tighten or pre-place
the harvest limit before sleeping) and for FOMC nights.

Usage:
    python scan_events.py --mode open            # default universe = focus list
    python scan_events.py --mode close
    python scan_events.py --refit                # re-fit models (~3 min of fetching)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import config  # noqa: E402
from analysis import event_radar as er  # noqa: E402


def _summary(model: dict) -> str:
    o, n = model["open"], model["overnight"]
    return (f"model fit {model['fit_date']} | OOS AUC: open call {o['call_touch']['oos_auc']:.3f} "
            f"put {o['put_touch']['oos_auc']:.3f} direction {o['up_wins']['oos_auc']:.3f} | "
            f"overnight up {n['big_up']['oos_auc']:.3f} down {n['big_dn']['oos_auc']:.3f}")


def run_open(model: dict, symbols: list[str], top: int) -> None:
    df = er.score_open(symbols, model)
    if df.empty:
        print("No pre-market data yet.")
        return
    o = model["open"]
    print(f"\nOPEN RADAR — {df.day.iloc[0]}   base rate: call +50% {o['call_touch']['base_rate']*100:.0f}% / "
          f"put +50% {o['put_touch']['base_rate']*100:.0f}% in the first hour")
    print(f"{'sym':6s}{'pm last':>10s}{'gap':>8s}{'P(call+50)':>12s}{'dec':>5s}{'P(put+50)':>11s}{'dec':>5s}"
          f"{'P(either)':>11s}  lean (AUC 0.51 — near coin flip)")
    for r in df.head(top).itertuples():
        lean = "up" if r.lean_up > 0.5 else "down"
        flag = "  FOMC yesterday" if r.fomc_yday else ""
        print(f"{r.sym:6s}{r.pm_last:10.2f}{r.gap_pct:+7.2f}%{r.p_call50*100:11.1f}%{r.dec_call:5d}"
              f"{r.p_put50*100:10.1f}%{r.dec_put:5d}{r.p_spike*100:10.1f}%  {lean} {abs(r.lean_up-0.5)*100:.1f}pt{flag}")
    print("\nLabel: watch — volatility radar. Deciles 9-10 = stand ready with a resting +50% limit;"
          " direction is NOT forecast.")


def run_close(model: dict, symbols: list[str], top: int) -> None:
    df = er.score_overnight(symbols, model)
    if df.empty:
        print("No data.")
        return
    n = model["overnight"]
    print(f"\nOVERNIGHT RADAR — session {df.session.iloc[0]}   base rate: big gap up "
          f"{n['big_up']['base_rate']*100:.0f}% / down {n['big_dn']['base_rate']*100:.0f}%")
    if df.fomc.any():
        print("  FOMC NIGHT — 2024-26 regime: next open averaged +1.22% (73% up, n=22); "
              "2017-23: no effect (n=40). Regime-dependent, not a rule.")
    print(f"{'sym':6s}{'price':>10s}{'1 gap-sd':>10s}{'P(gap up)':>11s}{'dec':>5s}{'P(gap dn)':>11s}{'dec':>5s}")
    for r in df.head(top).itertuples():
        print(f"{r.sym:6s}{r.price:10.2f}{r.one_gap_sd_pct:9.2f}%{r.p_gap_up*100:10.1f}%{r.dec_up:5d}"
              f"{r.p_gap_dn*100:10.1f}%{r.dec_dn:5d}")
    print("\nLabel: watch — volatility radar. Up and down odds rise together on flagged nights;"
          " the model forecasts size, not direction.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["open", "close"], default="open")
    ap.add_argument("--refit", action="store_true", help="re-fit and save the models first")
    ap.add_argument("--top", type=int, default=21)
    ap.add_argument("--symbols", nargs="*", default=None, help="default: config.FOCUS_AI_SEMI_IT")
    a = ap.parse_args()
    syms = a.symbols or config.FOCUS_AI_SEMI_IT
    if a.refit or not os.path.exists(er.MODEL_PATH):
        print("Fitting models (walk-forward validation, then final fit)...")
        er.fit(syms)
    m = er.load()
    print(_summary(m))
    (run_open if a.mode == "open" else run_close)(m, syms, a.top)
