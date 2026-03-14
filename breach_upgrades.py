"""
POEStick — Breachstone Upgrade Analyzer (Multi-Tier).
Calculates profit from upgrading Breachstones at every tier transition.
Tiers: Base → Charged → Enriched → Pure → Flawless
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price

# Full tier ladder for breachstones
BREACH_TIERS = ["", "Charged ", "Enriched ", "Pure ", "Flawless "]
BREACH_TIER_LABELS = ["Base", "Charged", "Enriched", "Pure", "Flawless"]
BREACH_LORDS = ["Xoph", "Tul", "Esh", "Uul-Netol", "Chayula"]


@dataclass
class BreachUpgrade:
    stone_type: str
    from_tier: str
    to_tier: str
    from_price: float
    blessing_price: float
    to_price: float
    total_cost: float
    profit: float
    margin_pct: float


def _stone_name(lord: str, tier_prefix: str) -> str:
    """Build the breachstone item name for a given lord and tier prefix."""
    return f"{tier_prefix}{lord}'s Breachstone"


def analyze_breach_upgrades(league: str, db_conn: sqlite3.Connection, console: Optional[Console] = None) -> list[BreachUpgrade]:
    """
    Fetch Fragments (Breachstones) and Currency (Blessings) to find upgrade margins
    at every tier transition: Base→Charged, Charged→Enriched, etc.
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Fragment"
    frag_data = fetch_json(url, "Fragment", console)
    frags = frag_data.get("lines", [])

    url_curr = f"https://poe.ninja/api/data/currencyoverview?league={league}&type=Currency"
    curr_data = fetch_json(url_curr, "Currency", console)
    currs = curr_data.get("lines", [])

    prices: dict[str, float] = {}
    for f in frags:
        prices[f.get("name")] = f.get("chaosValue", 0.0)
    for c in currs:
        prices[c.get("currencyTypeName")] = c.get("chaosEquivalent", 0.0)

    upgrades: list[BreachUpgrade] = []

    for lord in BREACH_LORDS:
        blessing_name = f"Blessing of {lord}"
        raw_blessing = prices.get(blessing_name, 0.0)
        if raw_blessing <= 0:
            continue
        safe_blessing = get_safe_price(db_conn, blessing_name, raw_blessing)

        # Walk every adjacent tier pair
        for i in range(len(BREACH_TIERS) - 1):
            from_name = _stone_name(lord, BREACH_TIERS[i])
            to_name = _stone_name(lord, BREACH_TIERS[i + 1])
            from_label = BREACH_TIER_LABELS[i]
            to_label = BREACH_TIER_LABELS[i + 1]

            raw_from = prices.get(from_name, 0.0)
            raw_to = prices.get(to_name, 0.0)

            if raw_from <= 0 or raw_to <= 0:
                continue

            safe_from = get_safe_price(db_conn, from_name, raw_from)
            safe_to = get_safe_price(db_conn, to_name, raw_to)

            cost = safe_from + safe_blessing
            profit = safe_to - cost
            margin = (profit / cost * 100) if cost > 0 else 0

            upgrades.append(BreachUpgrade(
                stone_type=lord,
                from_tier=from_label,
                to_tier=to_label,
                from_price=safe_from,
                blessing_price=safe_blessing,
                to_price=safe_to,
                total_cost=cost,
                profit=profit,
                margin_pct=margin,
            ))

    # Sort by profit descending
    upgrades.sort(key=lambda x: x.profit, reverse=True)
    return upgrades


def print_breach_table(upgrades: list[BreachUpgrade], console: Console):
    if not upgrades:
        console.print("[yellow]Could not find complete Breachstone price data.[/yellow]")
        return

    table = Table(
        title="👹 Breachstone Multi-Tier Upgrader (3.28 Mirage)",
        show_header=True,
        header_style="bold purple",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("Lord", style="bold")
    table.add_column("Path")
    table.add_column("From (c)", justify="right")
    table.add_column("Blessing (c)", justify="right")
    table.add_column("Total Cost", justify="right")
    table.add_column("To (c)", justify="right")
    table.add_column("Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")

    for upg in upgrades:
        margin_color = "green" if upg.margin_pct > 15 else ("yellow" if upg.margin_pct > 0 else "red")
        profit_str = f"+{upg.profit:,.1f}c" if upg.profit >= 0 else f"{upg.profit:,.1f}c"

        table.add_row(
            upg.stone_type,
            f"{upg.from_tier} → {upg.to_tier}",
            f"{upg.from_price:,.1f}",
            f"{upg.blessing_price:,.1f}",
            f"{upg.total_cost:,.1f}",
            f"{upg.to_price:,.1f}",
            profit_str,
            f"[{margin_color}]{upg.margin_pct:.1f}%[/{margin_color}]",
        )

    console.print(table)
    console.print("[dim]Upgrade path: Stone + Blessing → next tier. All 4 tier transitions shown per breach lord.[/dim]")
