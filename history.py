"""
POEStick — SQLite history tracking.

Logs each scan's results for historical trend data and delta comparison.
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime
from pathlib import Path

from analysis import Opportunity


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize the database and create tables if needed."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            league TEXT NOT NULL,
            total_opportunities INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL REFERENCES scans(id),
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            buy_price REAL NOT NULL,
            sell_price REAL NOT NULL,
            spread REAL NOT NULL,
            margin_pct REAL NOT NULL,
            confidence REAL NOT NULL,
            profit_score REAL NOT NULL,
            total_listings INTEGER NOT NULL,
            pay_listings INTEGER NOT NULL DEFAULT 0,
            recv_listings INTEGER NOT NULL DEFAULT 0,
            trend REAL NOT NULL DEFAULT 0,
            chaos_equivalent REAL NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp);
        CREATE INDEX IF NOT EXISTS idx_opps_scan_id ON opportunities(scan_id);
        CREATE INDEX IF NOT EXISTS idx_opps_name ON opportunities(name);
    """)

    # Migrate: add pay_listings/recv_listings if they don't exist yet
    _migrate_add_columns(conn)

    conn.commit()
    return conn


def _migrate_add_columns(conn: sqlite3.Connection):
    """Add pay_listings and recv_listings columns if missing (backwards compat)."""
    cursor = conn.execute("PRAGMA table_info(opportunities)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    if "pay_listings" not in existing_cols:
        conn.execute("ALTER TABLE opportunities ADD COLUMN pay_listings INTEGER NOT NULL DEFAULT 0")
    if "recv_listings" not in existing_cols:
        conn.execute("ALTER TABLE opportunities ADD COLUMN recv_listings INTEGER NOT NULL DEFAULT 0")


def log_scan(
    conn: sqlite3.Connection,
    league: str,
    opps: list[Opportunity],
    timestamp: datetime | None = None,
) -> int:
    """Log a scan and its opportunities. Returns the scan ID."""
    ts = (timestamp or datetime.now()).isoformat()

    cursor = conn.execute(
        "INSERT INTO scans (timestamp, league, total_opportunities) VALUES (?, ?, ?)",
        (ts, league, len(opps)),
    )
    scan_id = cursor.lastrowid

    conn.executemany(
        """INSERT INTO opportunities
           (scan_id, name, category, buy_price, sell_price, spread,
            margin_pct, confidence, profit_score, total_listings,
            pay_listings, recv_listings, trend, chaos_equivalent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (scan_id, o.name, o.category, o.buy_price, o.sell_price, o.spread,
             o.margin_pct, o.confidence, o.profit_score, o.total_listings,
             o.pay_listings, o.recv_listings, o.trend, o.chaos_equivalent)
            for o in opps
        ],
    )

    conn.commit()
    return scan_id  # type: ignore[return-value]


def get_previous_opps(conn: sqlite3.Connection) -> list[Opportunity]:
    """Fetch opportunities from the most recent scan (for delta comparison)."""
    row = conn.execute(
        "SELECT id FROM scans ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if not row:
        return []

    scan_id = row[0]
    rows = conn.execute(
        """SELECT name, category, buy_price, sell_price, spread, margin_pct,
                  confidence, profit_score, total_listings,
                  pay_listings, recv_listings, trend, chaos_equivalent
           FROM opportunities WHERE scan_id = ?""",
        (scan_id,),
    ).fetchall()

    return [
        Opportunity(
            name=r[0], category=r[1], buy_price=r[2], sell_price=r[3],
            spread=r[4], margin_pct=r[5], confidence=r[6], profit_score=r[7],
            pay_listings=r[9], recv_listings=r[10], total_listings=r[8],
            trend=r[11], chaos_equivalent=r[12],
        )
        for r in rows
    ]


def cleanup_old_scans(conn: sqlite3.Connection, keep_days: int = 7):
    """Remove scans older than keep_days to prevent unbounded growth."""
    conn.execute(
        """DELETE FROM opportunities WHERE scan_id IN (
               SELECT id FROM scans WHERE timestamp < datetime('now', ?)
           )""",
        (f"-{keep_days} days",),
    )
    conn.execute(
        "DELETE FROM scans WHERE timestamp < datetime('now', ?)",
        (f"-{keep_days} days",),
    )
    conn.commit()
