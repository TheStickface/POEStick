"""
POEStick — Foulborn upgrade analyzer.
Fetches Unique items and calculates the optimal Foulborn upgrades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price


@dataclass
class FoulbornCraft:
    base_name: str
    foulborn_name: str
    base_price: float
    foulborn_price: float
    profit: float
    margin_pct: float
    base_listings: int
    foulborn_listings: int


def fetch_unique_data(league: str, category: str, console: Optional[Console] = None) -> list[dict]:
    """Fetch unique item overview data for a given category (UniqueArmour, etc)."""
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type={category}"
    data = fetch_json(url, category, console)
    return data.get("lines", [])


def analyze_foulborn_crafts(league: str, db_conn: sqlite3.Connection, min_listings: int = 3, console: Optional[Console] = None) -> list[FoulbornCraft]:
    """
    Fetch all unique categories, pair base items with Foulborn versions,
    and calculate the crafting profit.
    """
    categories = ["UniqueArmour", "UniqueAccessory", "UniqueWeapon"]
    all_lines = []

    for cat in categories:
        all_lines.extend(fetch_unique_data(league, cat, console))

    # Group into dictionary to cross-reference
    items_by_name: dict[str, dict[str, float | int]] = {}
    for line in all_lines:
        name = line.get("name")
        chaos_value = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)
        
        # Keep the cheapest variant of an item (e.g. some might be 5-link vs 6-link, take base)
        # However, poe.ninja often groups them or has multiple entries.
        # We simplify by just taking the first listing we see or the minimum value for bases.
        if name and listings > 0 and chaos_value > 0:
            if name not in items_by_name or items_by_name[name]["chaosValue"] > chaos_value:
                items_by_name[name] = {"chaosValue": chaos_value, "listingCount": listings}

    crafts: list[FoulbornCraft] = []

    for name, data in items_by_name.items():
        if name and name.startswith("Foulborn "):
            base_name = name.removeprefix("Foulborn ")
            
            # Special exceptions for syntax differences could go here.
            
            if base_name in items_by_name:
                base_data = items_by_name[base_name]
                
                # Use safe pricing for both base and foulborn items
                raw_f_price = float(data["chaosValue"])
                raw_b_price = float(base_data["chaosValue"])

                f_price = get_safe_price(db_conn, name, raw_f_price)
                b_price = get_safe_price(db_conn, base_name, raw_b_price)

                profit = f_price - b_price
                
                base_listings = int(base_data.get("listingCount", 0))
                foulborn_listings = int(data.get("listingCount", 0))

                # Enforce minimum liquidity to avoid fake flips
                if base_listings < min_listings or foulborn_listings < min_listings:
                    continue
                
                if b_price > 0:
                    margin_pct = (profit / b_price) * 100.0
                else:
                    margin_pct = 0.0

                crafts.append(FoulbornCraft(
                    base_name=base_name,
                    foulborn_name=name,
                    base_price=b_price,
                    foulborn_price=f_price,
                    profit=profit,
                    margin_pct=margin_pct,
                    base_listings=base_listings,
                    foulborn_listings=foulborn_listings
                ))

    # Sort by profit descending
    crafts.sort(key=lambda c: c.profit, reverse=True)
    return crafts


def print_foulborn_table(crafts: list[FoulbornCraft], console: Console, limit: int = 15):
    """Render the top Foulborn crafts to the console."""
    if not crafts:
        console.print("[yellow]No Foulborn crafts found. API might be lagging or empty.[/yellow]")
        return

    table = Table(
        title=f"[bold magenta]🔮 Top Foulborn Upgrades (Flesh of Xesht / Wombgifts)[/bold magenta]",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Base Item")
    table.add_column("Base (c)", justify="right")
    table.add_column("Foulborn (c)", justify="right")
    table.add_column("Crafter Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")
    table.add_column("F B Listings", justify="right")
    table.add_column("F F Listings", justify="right")

    for rank, craft in enumerate(crafts[:limit], start=1):
        # Color margin
        margin_color = "white"
        if craft.margin_pct >= 100:
            margin_color = "bold green"
        elif craft.margin_pct >= 50:
            margin_color = "green"
        elif craft.margin_pct > 0:
            margin_color = "yellow"
        elif craft.margin_pct < 0:
            margin_color = "red"

        table.add_row(
            str(rank),
            craft.base_name,
            f"{craft.base_price:,.1f}",
            f"{craft.foulborn_price:,.1f}",
            f"+{craft.profit:,.1f}c" if craft.profit >= 0 else f"{craft.profit:,.1f}c",
            f"[{margin_color}]{craft.margin_pct:.1f}%[/{margin_color}]",
            str(craft.base_listings),
            str(craft.foulborn_listings)
        )

    console.print(table)
    console.print("[dim]Note: Prices above do not include the cost of Flesh of Xesht or Wombgift resources. Profit represents the gross added value.[/dim]")
