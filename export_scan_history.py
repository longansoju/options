"""
Export scan_history → data/scan_history.csv (cumulative, deduped).

Run after a scan. In the GitHub Action the working DB is ephemeral (gitignored and
recreated each run), so this CSV is the DURABLE, version-controlled dataset: each
run's rows are merged into the committed history and deduped on the snapshot key.
"""
from __future__ import annotations

import os
import sqlite3

import pandas as pd

import config

CSV = "data/scan_history.csv"
KEY = ["scan_date", "scan_type", "direction", "symbol"]


def main() -> None:
    con = sqlite3.connect(config.JOURNAL_DB_PATH)
    try:
        db = pd.read_sql_query("SELECT * FROM scan_history", con)
    finally:
        con.close()

    if db.empty:
        print("no scan_history rows in DB; nothing to export")
        return

    db = db.drop(columns=["id"], errors="ignore")
    os.makedirs("data", exist_ok=True)

    if os.path.exists(CSV):
        merged = pd.concat([pd.read_csv(CSV), db], ignore_index=True)
    else:
        merged = db

    merged = (merged
              .drop_duplicates(subset=KEY, keep="last")
              .sort_values(KEY)
              .reset_index(drop=True))
    merged.to_csv(CSV, index=False)
    print(f"wrote {len(merged)} rows to {CSV} ({len(db)} from this run)")


if __name__ == "__main__":
    main()
