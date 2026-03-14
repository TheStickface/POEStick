"""
POEStick — Essence Tier Upgrade Evaluator.
Identifies underpriced essences by comparing tier upgrade ratios (3:1 vendor).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price

# Essence tier ordering (low to high). 3 of tier N vendor into 1 of tier N+1.
ESSENCE_TIERS = ["Whispering", "Muttering", "Weeping", "Wailing", "Screaming", "Shrieking", "Deafening"]

# Base essence types that follow the 3:1 upgrade path
ESSENCE_TYPES = [
    "Greed", "Contempt", "Hatred", "Woe", "Fear", "Anger", "Torment",
    "Sorrow", "Rage", "Suffering", "Wrath", "Doubt", "Loathing",
    "Zeal", "Anguish", "Spite", "Scorn", "Envy", "Misery", "Dread",
]


@dataclass
class EssenceTierEntry:
    essence_type: str
    lower_tier: str
    upper_tier: str
    lower_price: float
    upper_price: float
    upgrade_cost: float  # 3 × lower_price
    profit: float        # upper_price - upgrade_cost
    margin_pct: float
    lower_listings: int
    upper_listings: int


def analyze_essences(
    league: str,
    db_conn: sqlite3.Connection,
    min_listings: int = 5,
    console: Optional[Console] = None,
) -> list[EssenceTierEntry]:
    """
    Fetch Essence prices and find profitable 3:1 upgrade paths.
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Essence"
    data = fetch_json(url, "Essence", console)
    lines = data.get("lines", [])

    # Build price lookup: "Screaming Essence of Greed" -> {price, listings}
    price_map: dict[str, dict] = {}
    for line in lines:
        name = line.get("name")
        price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)
        if name and price > 0:
            safe_price = get_safe_price(db_conn, name, price)
            price_map[name] = {"price": safe_price, "listings": listings}

    results: list[EssenceTierEntry] = []

    for etype in ESSENCE_TYPES:
        for i in range(len(ESSENCE_TIERS) - 1):
            lower_tier = ESSENCE_TIERS[i]
            upper_tier = ESSENCE_TIERS[i + 1]

            lower_name = f"{lower_tier} Essence of {etype}"
            upper_name = f"{upper_tier} Essence of {etype}"

            if lower_name not in price_map or upper_name not in price_map:
                continue

            lower_data = price_map[lower_name]
            upper_data = price_map[upper_name]

            if lower_data["listings"] < min_listings or upper_data["listings"] < min_listings:
                continue

            upgrade_cost = 3.0 * lower_data["price"]
            profit = upper_data["price"] - upgrade_cost
            margin = (profit / upgrade_cost * 100) if upgrade_cost > 0 else 0

            # Only show profitable upgrades
            if profit > 0:
                results.append(EssenceTierEntry(
                    essence_type=etype,
                    lower_tier=lower_tier,
                    upper_tier=upper_tier,
                    lower_price=lower_data["price"],
                    upper_price=upper_data["price"],
                    upgrade_cost=upgrade_cost,
                    profit=profit,
                    margin_pct=margin,
                    lower_listings=lower_data["listings"],
                    upper_listings=upper_data["listings"],
                ))

    results.sort(key=lambda x: x.profit, reverse=True)
    return results


def print_essence_table(entries: list[EssenceTierEntry], console: Console, limit: int = 20):
    if not entries:
        console.print("[yellow]No profitable Essence upgrades found at current prices.[/yellow]")
        return

    table = Table(
        title="💎 Essence Tier Upgrade Evaluator (3:1 Vendor Path)",
        show_header=True,
        header_style="bold magenta",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Type")
    table.add_column("From Tier")
    table.add_column("To Tier")
    table.add_column("3× Lower (c)", justify="right")
    table.add_column("Upper (c)", justify="right")
    table.add_column("Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")
    table.add_column("Lo / Hi Listings", justify="right")

    for rank, e in enumerate(entries[:limit], start=1):
        margin_color = "green" if e.margin_pct > 25 else ("yellow" if e.margin_pct > 0 else "red")

        table.add_row(
            str(rank),
            e.essence_type,
            e.lower_tier,
            e.upper_tier,
            f"{e.upgrade_cost:,.1f}",
            f"{e.upper_price:,.1f}",
            f"+{e.profit:,.1f}c",
            f"[{margin_color}]{e.margin_pct:.1f}%[/{margin_color}]",
            f"{e.lower_listings} / {e.upper_listings}",
        )

    console.print(table)
    console.print("[dim]Upgrade path: 3 lower-tier essences vendor into 1 upper-tier essence.[/dim]")
    console.print("[dim]Corruption Essences (Hysteria, Insanity, Horror, Delirium) are excluded — no vendor path.[/dim]")
