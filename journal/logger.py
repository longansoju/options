from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from data_ingestion.base import Recommendation, Signal
from execution.alpaca_paper import Fill
import config

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    action                  TEXT NOT NULL,
    structure               TEXT NOT NULL,
    contract_symbol         TEXT,
    strike                  REAL,
    expiry                  TEXT,
    dte_at_entry            INTEGER,
    contracts               INTEGER,
    fill_price              REAL,
    max_loss_per_contract   REAL,
    total_max_loss          REAL,
    risk_pct_equity         REAL,
    commission              REAL,
    ivr                     REAL,
    ivr_regime              TEXT,
    ivr_is_proxy            INTEGER,
    thesis                  TEXT,
    refused_reason          TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id),
    name        TEXT NOT NULL,
    value       REAL,
    direction   TEXT,
    strength    TEXT,
    rationale   TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL REFERENCES decisions(id),
    timestamp       TEXT NOT NULL,
    contract_symbol TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    fill_price      REAL NOT NULL,
    commission      REAL NOT NULL,
    total_cost      REAL NOT NULL,
    order_id        TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id         INTEGER NOT NULL REFERENCES fills(id),
    symbol          TEXT NOT NULL,
    contract_symbol TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    entry_price     REAL NOT NULL,
    entry_cost      REAL NOT NULL,
    max_loss        REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    exit_price      REAL,
    exit_cost       REAL,
    realized_pnl    REAL,
    closed_at       TEXT
);
"""


class JournalLogger:
    """
    SQLite-backed journal. Logs every recommendation, signal, fill, and position.
    All decisions — including refused ones — are stored so the human can audit them.
    """

    def __init__(self, db_path: str = config.JOURNAL_DB_PATH) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        con = sqlite3.connect(db_path)
        con.executescript(_SCHEMA)
        con.commit()
        con.close()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        return con

    def log_recommendation(
        self,
        rec: Recommendation,
        ivr: Optional[float] = None,
        ivr_regime: Optional[str] = None,
        ivr_is_proxy: bool = False,
        fill: Optional[Fill] = None,
        risk_pct_equity: Optional[float] = None,
    ) -> int:
        """
        Persist a Recommendation and optional Fill. Returns the decision_id.
        """
        con = self._con()
        c = rec.contract
        now = datetime.utcnow().isoformat()

        cur = con.execute(
            """INSERT INTO decisions
               (timestamp, symbol, action, structure,
                contract_symbol, strike, expiry, dte_at_entry,
                contracts, fill_price,
                max_loss_per_contract, total_max_loss,
                risk_pct_equity, commission,
                ivr, ivr_regime, ivr_is_proxy,
                thesis, refused_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now,
                rec.symbol,
                rec.action,
                rec.structure,
                c.symbol if c else None,
                c.strike if c else None,
                c.expiration.isoformat() if c else None,
                c.dte if c else None,
                rec.size,
                fill.fill_price if fill else None,
                rec.max_loss / rec.size if rec.size else None,
                rec.max_loss,
                risk_pct_equity,
                fill.commission if fill else None,
                ivr,
                ivr_regime,
                int(ivr_is_proxy),
                rec.thesis,
                rec.refused_reason,
            ),
        )
        decision_id = cur.lastrowid

        for sig in rec.signals:
            con.execute(
                """INSERT INTO signals (decision_id, name, value, direction, strength, rationale)
                   VALUES (?,?,?,?,?,?)""",
                (decision_id, sig.name, sig.value, sig.direction, sig.strength, sig.rationale),
            )

        if fill:
            con.execute(
                """INSERT INTO fills
                   (decision_id, timestamp, contract_symbol, quantity,
                    fill_price, commission, total_cost, order_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    decision_id,
                    fill.timestamp.isoformat(),
                    fill.contract_symbol,
                    fill.quantity,
                    fill.fill_price,
                    fill.commission,
                    fill.total_cost,
                    fill.order_id,
                ),
            )
            fill_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute(
                """INSERT INTO positions
                   (fill_id, symbol, contract_symbol, quantity,
                    entry_price, entry_cost, max_loss, status)
                   VALUES (?,?,?,?,?,?,?,'open')""",
                (
                    fill_id,
                    rec.symbol,
                    fill.contract_symbol,
                    fill.quantity,
                    fill.fill_price,
                    fill.total_cost,
                    rec.max_loss,
                ),
            )

        con.commit()
        con.close()

        self._print_summary(rec, ivr, ivr_regime, fill)
        return decision_id

    def _print_summary(
        self,
        rec: Recommendation,
        ivr: Optional[float],
        ivr_regime: Optional[str],
        fill: Optional[Fill],
    ) -> None:
        sep = "─" * 60
        print(f"\n{sep}")
        print(f"DECISION  {rec.symbol}  |  {rec.action.upper()}  |  {rec.structure}")
        if rec.contract:
            c = rec.contract
            print(f"CONTRACT  {c.symbol}  strike={c.strike}  expiry={c.expiration}  DTE={c.dte}")
            print(f"PRICING   bid={c.bid:.2f}  ask={c.ask:.2f}  mid={c.mid:.2f}  spread={c.spread_pct:.1f}%")
        if ivr is not None:
            print(f"IV RANK   {ivr:.1f}  ({ivr_regime})")
        print(f"MAX LOSS  ${rec.max_loss:.2f}  ({rec.size} contract(s))")
        print(f"THESIS    {rec.thesis}")
        for sig in rec.signals:
            print(f"  SIGNAL  [{sig.strength.upper()}] {sig.name}: {sig.rationale}")
        if rec.refused_reason:
            print(f"REFUSED   {rec.refused_reason}")
        if fill:
            print(f"FILL      {fill.quantity}x @ {fill.fill_price:.2f}  total=${fill.total_cost:.2f}  order={fill.order_id}")
        print(sep)
