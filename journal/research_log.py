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
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import config

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
    exit_date         TEXT,
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
        # migration for DBs created before the `book` column existed
        cols = [r[1] for r in con.execute("PRAGMA table_info(recommendations)").fetchall()]
        if "book" not in cols:
            con.execute("ALTER TABLE recommendations ADD COLUMN book TEXT NOT NULL DEFAULT 'watch'")
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
        now = datetime.now()
        scan_ts = scan_ts or now.isoformat(timespec="seconds")
        scan_date = scan_date or now.date().isoformat()
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
                           status="open", book="watch") -> str:
        created_date = created_date or date.today().isoformat()
        code = occ_code(symbol, expiry, direction, strike)
        con = self._con()
        con.execute(
            """INSERT OR REPLACE INTO recommendations
               (created_date, symbol, strategy, direction, strike, expiry, occ_code,
                entry_ref_price, entry_premium, thesis, status, book)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (created_date, symbol.upper(), strategy, direction.lower(), strike,
             expiry, code, entry_ref_price, entry_premium, thesis, status, book),
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
        exit_date = exit_date or date.today().isoformat()
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
               SET status=?, exit_date=?, exit_ref_price=?, exit_premium=?, pnl_pct=?,
                   notes=COALESCE(?, notes)
               WHERE occ_code=? AND status='open'""",
            (status, exit_date, exit_ref_price, exit_premium, pnl, notes, occ),
        )
        con.commit()
        con.close()
        return True

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
