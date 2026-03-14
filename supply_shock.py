"""
POEStick — Supply Shock Detector.

Monitors listing count changes between consecutive scan snapshots.
A sudden supply DROP (>20%) often precedes a price spike — buy signal.
A sudden supply SURGE (>20%) often precedes a price crash — sell signal.

Covers: Currency, Fragment, Scarab, Fossil, DivinationCard.
Persists listing counts to SQLite so the live dashboard can compare
the current scan against the previous one without extra API calls.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import sqlite3
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from api import fetch_json


# ── Tunables ────────────────────────────────────────────────────────────────

SHOCK_THRESHOLD    = 0.20   # minimum fractional change to qualify (20%)
MIN_PREV_LISTINGS  = 10     # ignore items with fewer prior listings (noise)
MIN_PRICE          = 5.0    # ignore items below this chaos value


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class ShockEntry:
    name: str
    category: str
    price: float
    prev_listings: int
    curr_listings: int
    change: int             # curr - prev  (negative = supply dropped)
    change_pct: float       # fractional change, e.g. -0.35 = -35%
    shock_score: float      # abs(change_pct) × price — financial weight
    direction: str          # "DROP" or "SURGE"


# ── Database ─────────────────────────────────────────────────────────────────

def init_listing_db(db_conn: sqlite3.Connection) -> None:
    """Create the listing_history table if it doesn't exist."""
    db_conn.executescript("""
        CREATE TABLE IF NOT EXISTS listing_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT    NOT NULL,
            item_name     TEXT    NOT NULL,
            category      TEXT    NOT NULL,
            listing_count INTEGER NOT NULL,
            price         REAL    NOT NULL DEFAULT 0.0
        );
        CREATE INDEX IF NOT EXISTS idx_lh_item_ts
            ON listing_history (item_name, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_lh_ts
            ON listing_history (timestamp DESC);
    """)
    db_conn.commit()


def record_listings(
    db_conn: sqlite3.Connection,
    snapshot: dict[str, tuple[str, int, float]],
    timestamp: Optional[str] = None,
) -> None:
    """
    Persist a listing snapshot to the DB.
    snapshot: { item_name -> (category, listing_count, price) }
    Prunes records older than 24 hours to keep the table lean.
    """
    ts = timestamp or datetime.now().isoformat()
    rows = [
        (ts, name, cat, count, price)
        for name, (cat, count, price) in snapshot.items()
        if count > 0 and price > 0
    ]
    if rows:
        db_conn.executemany(
            "INSERT INTO listing_history (timestamp, item_name, category, listing_count, price) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    db_conn.execute("DELETE FROM listing_history WHERE timestamp < datetime('now', '-24 hours')")
    db_conn.commit()


def detect_shocks(
    db_conn: sqlite3.Connection,
    threshold: float = SHOCK_THRESHOLD,
    min_price: float = MIN_PRICE,
    min_prev_listings: int = MIN_PREV_LISTINGS,
) -> list[ShockEntry]:
    """
    Compare the two most recent distinct listing snapshots.
    Returns ShockEntry list sorted by shock_score descending.
    Returns [] if fewer than 2 snapshots exist yet.
    """
    timestamps = [
        row[0] for row in db_conn.execute(
            "SELECT DISTINCT timestamp FROM listing_history ORDER BY timestamp DESC LIMIT 2"
        ).fetchall()
    ]
    if len(timestamps) < 2:
        return []

    latest_ts, prev_ts = timestamps[0], timestamps[1]

    rows = db_conn.execute("""
        SELECT
            curr.item_name,
            curr.category,
            curr.price,
            prev.listing_count AS prev_count,
            curr.listing_count AS curr_count
        FROM listing_history curr
        JOIN listing_history prev
          ON curr.item_name = prev.item_name
         AND prev.timestamp = ?
        WHERE curr.timestamp = ?
          AND prev.listing_count >= ?
          AND curr.price >= ?
    """, (prev_ts, latest_ts, min_prev_listings, min_price)).fetchall()

    shocks: list[ShockEntry] = []
    for name, category, price, prev_count, curr_count in rows:
        frac = (curr_count - prev_count) / prev_count
        if abs(frac) < threshold:
            continue
        shocks.append(ShockEntry(
            name=name,
            category=category,
            price=price,
            prev_listings=prev_count,
            curr_listings=curr_count,
            change=curr_count - prev_count,
            change_pct=round(frac * 100, 1),
            shock_score=round(abs(frac) * price, 2),
            direction="DROP" if frac < 0 else "SURGE",
        ))

    shocks.sort(key=lambda x: x.shock_score, reverse=True)
    return shocks


# ── Snapshot extraction ──────────────────────────────────────────────────────

def extract_snapshot(data: dict, category: str) -> dict[str, tuple[str, int, float]]:
    """
    Pull listing counts out of a raw poe.ninja API response dict.
    Returns { name -> (category, listing_count, price) }.
    Works for both currencyoverview and itemoverview shapes.
    """
    out: dict[str, tuple[str, int, float]] = {}
    for line in data.get("lines", []):
        name  = line.get("currencyTypeName") or line.get("name")
        price = line.get("chaosEquivalent") or line.get("chaosValue") or 0.0
        # Currency endpoint stores counts inside pay/receive sub-dicts
        pay_c   = (line.get("pay")     or {}).get("listing_count", 0)
        recv_c  = (line.get("receive") or {}).get("listing_count", 0)
        count   = line.get("listingCount") or (pay_c + recv_c)
        if name and count and price:
            out[name] = (category, int(count), float(price))
    return out


def run_supply_shock_scan(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
) -> list[ShockEntry]:
    """
    Full standalone scan: fetches Currency, Fragment, Scarab, Fossil,
    DivinationCard data, records the snapshot, then returns shocks.
    Used by --supply-shock mode.
    """
    snapshot: dict[str, tuple[str, int, float]] = {}

    targets = [
        ("currencyoverview", "Currency"),
        ("currencyoverview", "Fragment"),
        ("itemoverview",     "Scarab"),
        ("itemoverview",     "Fossil"),
        ("itemoverview",     "DivinationCard"),
    ]
    for endpoint, cat in targets:
        url  = f"https://poe.ninja/api/data/{endpoint}?league={league}&type={cat}"
        data = fetch_json(url, cat, console)
        snapshot.update(extract_snapshot(data, cat))

    record_listings(db_conn, snapshot)
    return detect_shocks(db_conn)


# ── Display ──────────────────────────────────────────────────────────────────

def build_shock_live_panel(shocks: list[ShockEntry], top_n: int = 6) -> Optional[Panel]:
    """
    Compact panel for embedding in the live dashboard.
    Shows top DROP signals only (most actionable for traders).
    Returns None when no shocks detected.
    """
    drops = [s for s in shocks if s.direction == "DROP"][:top_n]
    if not drops:
        return None

    table = Table(
        show_header=True,
        header_style="bold red",
        border_style="bright_black",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Item")
    table.add_column("Cat", width=9)
    table.add_column("Price", justify="right", width=7)
    table.add_column("Prev→Curr", justify="center", width=11)
    table.add_column("Δ Listings", justify="right", width=10)
    table.add_column("Δ %", justify="right", width=7)
    table.add_column("Score", justify="right", width=7)

    for s in drops:
        table.add_row(
            f"[bold white]{s.name}[/bold white]",
            f"[dim]{s.category}[/dim]",
            f"{s.price:.1f}c",
            f"{s.prev_listings}→{s.curr_listings}",
            f"[red]{s.change:+d}[/red]",
            f"[bold red]{s.change_pct:+.1f}%[/bold red]",
            f"{s.shock_score:.1f}",
        )

    return Panel(
        table,
        title="[bold red]⚡ SUPPLY SHOCK — DROP ALERTS[/bold red]  "
              "[dim](supply fell sharply → price spike likely)[/dim]",
        border_style="red",
        padding=(0, 0),
    )


def print_shock_table(shocks: list[ShockEntry], console: Console, limit: int = 25):
    """Full standalone display with both DROPs and SURGEs."""
    if not shocks:
        console.print(
            "[yellow]No supply shocks detected yet.[/yellow]\n"
            "[dim]Two consecutive snapshots are required. "
            "Run --supply-shock again after the next refresh.[/dim]"
        )
        return

    table = Table(
        title=f"⚡ Supply Shock Detector  [dim](threshold ≥{SHOCK_THRESHOLD*100:.0f}%,"
              f" min {MIN_PREV_LISTINGS} prior listings, min {MIN_PRICE:.0f}c)[/dim]",
        show_header=True,
        header_style="bold red",
        border_style="bright_black",
        expand=True,
    )
    table.add_column("#",          style="dim", width=3,  justify="right")
    table.add_column("Item")
    table.add_column("Category",   width=13,               justify="center")
    table.add_column("Price (c)",  width=9,                justify="right")
    table.add_column("Signal",     width=16,               justify="center")
    table.add_column("Prev→Curr",  width=12,               justify="center")
    table.add_column("Δ Listings", width=10,               justify="right")
    table.add_column("Δ %",        width=8,                justify="right")
    table.add_column("Score",      width=7,                justify="right")

    # Drops first (most actionable), then surges
    ordered = (
        [s for s in shocks if s.direction == "DROP"] +
        [s for s in shocks if s.direction == "SURGE"]
    )

    for rank, s in enumerate(ordered[:limit], start=1):
        if s.direction == "DROP":
            signal     = "[bold red]▼ SUPPLY DROP[/bold red]"
            pct_style  = "bold red"
        else:
            signal     = "[bold yellow]▲ SUPPLY SURGE[/bold yellow]"
            pct_style  = "bold yellow"

        table.add_row(
            str(rank),
            s.name,
            f"[dim]{s.category}[/dim]",
            f"{s.price:.1f}",
            signal,
            f"{s.prev_listings}→{s.curr_listings}",
            f"[{pct_style}]{s.change:+d}[/{pct_style}]",
            f"[{pct_style}]{s.change_pct:+.1f}%[/{pct_style}]",
            f"{s.shock_score:.1f}",
        )

    console.print(table)
    console.print(
        "[dim]Score = |Δ%| × price  (financial weight of the shock).\n"
        "▼ SUPPLY DROP  → listings fell sharply → price spike likely → buy opportunity.\n"
        "▲ SUPPLY SURGE → listings flooded       → price crash likely → sell / avoid.\n"
        "Covers: Currency, Fragment, Scarab, Fossil, DivinationCard.[/dim]"
    )
