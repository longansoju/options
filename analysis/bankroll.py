"""November bankroll (user 2026-11-01: "be stricter with the budget. we will only use $1000 to trade
for the month. make sure to make the most out of it").

Interpretation: a $1,000 CASH account for the month. Every funded paper trade (book=paper, created
on/after START) is paid from it; proceeds come back when it closes, so wins compound and losses
shrink the next trade. A new entry needs its premium <= available cash AND <= its strategy's cap,
and caps are a fraction of current EQUITY (so they shrink after losses and grow after wins):
  day trade   <= 50% of equity (a -20% stop = 10% of equity at most), max 2 open at once
  1-day pair  <= 10% of equity per pair, max 2 pairs a night (premium can go to zero)
  trend-hold  <= 50% of equity, max 1 open (a -50% stop = 25% of equity at most)
  strangles   not funded - logged as book=watch so the forward test keeps its data
Book fills stay model prices (no spread); `summary()` also reports an after-cost estimate.
"""

from __future__ import annotations

import pandas as pd

START, CAPITAL = "2026-11-02", 1000.0
CAP = {"daytrade": 0.50, "lottery": 0.10, "trendhold": 0.50}
MAX_OPEN = {"daytrade": 2, "trendhold": 1}
COST = {"daytrade": 0.04, "lottery": 0.10, "trendhold": 0.04, "strangle": 0.04}   # round-trip spread estimate
BOOK = "/home/user/options/data/recommendations.csv"


def _funded(book: pd.DataFrame) -> pd.DataFrame:
    return book[(book.book == "paper") & (book.created_date >= START)]


def state(book: pd.DataFrame | None = None, unbooked: float = 0.0) -> dict:
    """Equity / cash from the durable book. `unbooked` = premium of engine positions not yet
    written to the CSV (so a just-fired entry is not double-spent)."""
    book = pd.read_csv(BOOK) if book is None else book
    f = _funded(book)
    closed, open_ = f[f.status == "closed"], f[f.status == "open"]
    realized = float((closed.exit_premium - closed.entry_premium).sum())
    equity = CAPITAL + realized
    cash = equity - float(open_.entry_premium.sum()) - unbooked
    n_open = open_.strategy.value_counts().to_dict()
    return dict(equity=equity, cash=cash, realized=realized, open_premium=float(open_.entry_premium.sum()),
                n_open=n_open, closed=len(closed))


def budget(strategy: str, book: pd.DataFrame | None = None, unbooked: float = 0.0, open_now: int | None = None) -> float:
    """Largest premium a new `strategy` entry may cost right now (0 = no entry)."""
    s = state(book, unbooked)
    n = s["n_open"].get(strategy, 0) if open_now is None else open_now
    if strategy not in CAP or n >= MAX_OPEN.get(strategy, 10 ** 6):
        return 0.0
    return max(0.0, min(CAP[strategy] * s["equity"], s["cash"]))


def summary(book: pd.DataFrame | None = None) -> str:
    book = pd.read_csv(BOOK) if book is None else book
    s = state(book)
    c = _funded(book)
    c = c[c.status == "closed"]
    cost = float((c.entry_premium * c.strategy.map(COST).fillna(0.04)).sum())
    return (f"November $1,000 book: equity ${s['equity']:,.0f} ({s['realized']:+,.0f} on {s['closed']} closed), "
            f"after ~spread ${s['equity'] - cost:,.0f} | cash ${s['cash']:,.0f}, open premium ${s['open_premium']:,.0f}")


if __name__ == "__main__":
    print(summary())
    for k in CAP:
        print(f"  {k:10s} next entry may cost up to ${budget(k):,.0f}")
