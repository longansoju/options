"""
Research log — the data foundation (Phase 1).

Two additive tables in the existing journal DB (journal/trades.db). Neither
touches the execution-side schema in journal/logger.py (decisions/fills/positions),
which is reserved for real Alpaca paper fills.

    scan_history     — one dated snapshot per (date, scan_type, direction, symbol)
                       written automatically every time a scanner runs. This is the
                       time-series dataset everything downstream learns from.
    recommendations  — every chat-surfaced pick (swing or momentum) with its OCC
                       code, entry reference, thesis, and outcome fields. Lets the
                       "review my positions" routine read from the DB instead of
                       re-scanning from scratch.

Outcome fields on `recommendations` start NULL and are filled when a position is
closed (real exit premium + date) → that's the labeled data for later calibration.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import config

# The user trades from Singapore (GMT+8). Precise timestamps are recorded in SGT
# with an explicit +08:00 offset so they read correctly in local time. Date-key
# fields (scan_date, created_date, exit_date) stay on the UTC calendar date, which
# for US-session scan times equals the US trading date — keeps per-session keys stable.
SGT = timezone(timedelta(hours=8))


def _sgt_now() -> str:
    return datetime.now(SGT).isoformat(timespec="seconds")


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date     TEXT NOT NULL,          -- YYYY-MM-DD
    scan_ts       TEXT NOT NULL,          -- full ISO timestamp of the run
    scan_type     TEXT NOT NULL,          -- swing | momentum
    direction     TEXT,                   -- bullish/bearish (swing) | call/put (momentum)
    symbol        TEXT NOT NULL,
    price         REAL,
    ivr           REAL,
    ivr_regime    TEXT,
    ivr_is_proxy  INTEGER,
    trend_signal  TEXT,
    trend_score   INTEGER,
    rsi           REAL,
    ret1m         REAL,
    ret3m         REAL,
    rv            REAL,                    -- momentum: annualized realized vol
    vol_rank      REAL,                    -- momentum: RV percentile (IVR analogue)
    atr_pct       REAL,
    ret5          REAL,
    vol_ratio     REAL,
    ignition      REAL,                    -- momentum score
    entry_score   INTEGER,                 -- swing timing-adjusted score
    verdict       TEXT,
    flags         TEXT,
    UNIQUE(scan_date, scan_type, direction, symbol)
);
CREATE INDEX IF NOT EXISTS idx_scan_symbol ON scan_history(symbol, scan_date);

CREATE TABLE IF NOT EXISTS recommendations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_date      TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    strategy          TEXT NOT NULL,        -- swing | momentum
    direction         TEXT NOT NULL,        -- call | put
    strike            REAL NOT NULL,
    expiry            TEXT NOT NULL,        -- YYYY-MM-DD
    occ_code          TEXT NOT NULL,
    entry_ref_price   REAL,                 -- underlying price at rec time
    entry_premium     REAL,                 -- per-contract; actual if held, else est
    thesis            TEXT,
    status            TEXT NOT NULL DEFAULT 'open',  -- open|closed|expired|skipped
    book              TEXT NOT NULL DEFAULT 'watch',  -- real | paper | watch
    entry_ts          TEXT,                           -- precise ISO time the entry was booked
    price_source      TEXT NOT NULL DEFAULT 'estimate',  -- estimate | real (backfill target)
    exit_date         TEXT,
    exit_ts           TEXT,                           -- precise ISO time of exit
    exit_ref_price    REAL,
    exit_premium      REAL,
    pnl_pct           REAL,
    notes             TEXT,
    UNIQUE(occ_code, created_date)
);
"""


def occ_code(symbol: str, expiry: str, direction: str, strike: float) -> str:
    """Build an OCC contract code: {ROOT}{YYMMDD}{C|P}{strike*1000 :08d}."""
    d = date.fromisoformat(expiry)
    cp = "C" if direction.lower().startswith("c") else "P"
    return f"{symbol.upper()}{d:%y%m%d}{cp}{int(round(strike * 1000)):08d}"


class ResearchLog:
    def __init__(self, db_path: str = config.JOURNAL_DB_PATH) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = db_path
        con = sqlite3.connect(db_path)
        con.executescript(_SCHEMA)
        # migrations for columns added after a DB was first created
        cols = [r[1] for r in con.execute("PRAGMA table_info(recommendations)").fetchall()]
        for name, ddl in (
            ("book", "TEXT NOT NULL DEFAULT 'watch'"),
            ("entry_ts", "TEXT"),
            ("price_source", "TEXT NOT NULL DEFAULT 'estimate'"),
            ("exit_ts", "TEXT"),
        ):
            if name not in cols:
                con.execute(f"ALTER TABLE recommendations ADD COLUMN {name} {ddl}")
        con.commit()
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db)
        con.row_factory = sqlite3.Row
        return con

    # ── scan snapshots ──────────────────────────────────────────────────────

    def log_scan_row(self, scan_type: str, symbol: str, *, direction: str | None = None,
                     scan_date: str | None = None, scan_ts: str | None = None,
                     **fields) -> None:
        """Upsert one snapshot row. Unknown kwargs are ignored, missing → NULL."""
        scan_ts = scan_ts or _sgt_now()
        scan_date = scan_date or _utc_today()
        cols = ["price", "ivr", "ivr_regime", "ivr_is_proxy", "trend_signal",
                "trend_score", "rsi", "ret1m", "ret3m", "rv", "vol_rank",
                "atr_pct", "ret5", "vol_ratio", "ignition", "entry_score",
                "verdict", "flags"]
        vals = [fields.get(c) for c in cols]
        if fields.get("ivr_is_proxy") is not None:
            vals[cols.index("ivr_is_proxy")] = int(fields["ivr_is_proxy"])
        con = self._con()
        con.execute(
            f"""INSERT OR REPLACE INTO scan_history
                (scan_date, scan_ts, scan_type, direction, symbol, {', '.join(cols)})
                VALUES ({','.join(['?'] * (5 + len(cols)))})""",
            [scan_date, scan_ts, scan_type, direction, symbol, *vals],
        )
        con.commit()
        con.close()

    def latest_snapshot(self, symbol: str, *, require_rv: bool = False):
        con = self._con()
        where = "symbol=?" + (" AND rv IS NOT NULL" if require_rv else "")
        row = con.execute(
            f"SELECT * FROM scan_history WHERE {where} "
            "ORDER BY scan_date DESC, scan_ts DESC LIMIT 1", (symbol,)
        ).fetchone()
        con.close()
        return row

    def scan_count(self) -> int:
        con = self._con()
        n = con.execute("SELECT COUNT(*) FROM scan_history").fetchone()[0]
        con.close()
        return n

    # ── recommendations ─────────────────────────────────────────────────────

    def add_recommendation(self, symbol: str, strategy: str, direction: str,
                           strike: float, expiry: str, *, entry_ref_price=None,
                           entry_premium=None, thesis=None, created_date=None,
                           status="open", book="watch", price_source="estimate",
                           entry_ts=None) -> str:
        created_date = created_date or _utc_today()
        entry_ts = entry_ts or _sgt_now()
        code = occ_code(symbol, expiry, direction, strike)
        con = self._con()
        con.execute(
            """INSERT OR REPLACE INTO recommendations
               (created_date, symbol, strategy, direction, strike, expiry, occ_code,
                entry_ref_price, entry_premium, thesis, status, book, entry_ts, price_source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (created_date, symbol.upper(), strategy, direction.lower(), strike,
             expiry, code, entry_ref_price, entry_premium, thesis, status, book,
             entry_ts, price_source),
        )
        con.commit()
        con.close()
        return code

    def paper_stats(self) -> dict:
        """Track-record summary over CLOSED paper trades."""
        con = self._con()
        rows = con.execute(
            "SELECT entry_premium, exit_premium, pnl_pct FROM recommendations "
            "WHERE book='paper' AND status='closed' AND exit_premium IS NOT NULL "
            "AND entry_premium IS NOT NULL"
        ).fetchall()
        con.close()
        n = len(rows)
        if not n:
            return {"closed": 0}
        wins = sum(1 for r in rows if (r["pnl_pct"] or 0) > 0)
        cost = sum(r["entry_premium"] for r in rows)
        proceeds = sum(r["exit_premium"] for r in rows)
        return {
            "closed": n, "wins": wins, "win_rate": wins / n * 100,
            "avg_pnl_pct": sum(r["pnl_pct"] for r in rows) / n,
            "cost": cost, "proceeds": proceeds, "net": proceeds - cost,
            "net_pct": (proceeds / cost - 1) * 100 if cost else 0,
        }

    def close_recommendation(self, occ: str, *, exit_premium=None, exit_ref_price=None,
                             status="closed", notes=None, exit_date=None) -> bool:
        exit_date = exit_date or _utc_today()
        exit_ts = _sgt_now()
        con = self._con()
        row = con.execute(
            "SELECT entry_premium FROM recommendations WHERE occ_code=? AND status='open' "
            "ORDER BY id DESC LIMIT 1", (occ,)
        ).fetchone()
        if row is None:
            con.close()
            return False
        pnl = None
        ep = row["entry_premium"]
        if ep and exit_premium is not None:
            pnl = (exit_premium - ep) / ep * 100
        con.execute(
            """UPDATE recommendations
               SET status=?, exit_date=?, exit_ts=?, exit_ref_price=?, exit_premium=?, pnl_pct=?,
                   notes=COALESCE(?, notes)
               WHERE occ_code=? AND status='open'""",
            (status, exit_date, exit_ts, exit_ref_price, exit_premium, pnl, notes, occ),
        )
        con.commit()
        con.close()
        return True

    def export_recommendations(self, path: str = "data/recommendations.csv") -> int:
        """Dump the book to a committed CSV (durable across ephemeral containers)."""
        import csv
        import os
        con = self._con()
        rows = con.execute("SELECT * FROM recommendations ORDER BY created_date, id").fetchall()
        con.close()
        if not rows:
            return 0
        cols = [c for c in rows[0].keys() if c != "id"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r[c] for c in cols})
        return len(rows)

    def import_recommendations(self, path: str = "data/recommendations.csv") -> int:
        """Restore the book from the committed CSV into the DB (idempotent)."""
        import csv
        import os
        if not os.path.exists(path):
            return 0
        con = self._con()
        n = 0
        with open(path) as f:
            for row in csv.DictReader(f):
                cols = list(row.keys())
                vals = [row[c] if row[c] not in ("", None) else None for c in cols]
                con.execute(
                    f"INSERT OR REPLACE INTO recommendations ({','.join(cols)}) "
                    f"VALUES ({','.join(['?'] * len(cols))})", vals)
                n += 1
        con.commit()
        con.close()
        return n

    def recommendations(self, *, status: str | None = "open"):
        con = self._con()
        if status:
            rows = con.execute(
                "SELECT * FROM recommendations WHERE status=? ORDER BY strategy, symbol",
                (status,)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM recommendations ORDER BY status, strategy, symbol").fetchall()
        con.close()
        return rows
