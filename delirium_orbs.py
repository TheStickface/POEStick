"""
POEStick — Delirium Orb Profit Calculator.
Fetches Delirium Orb prices and estimates profit-per-orb based on reward type values.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price

# Mapping of Delirium Orb → the poe.ninja category that best represents its drops.
# The orb's reward type adds delirium monsters that drop items of that type.
ORB_REWARD_CATEGORIES: dict[str, str] = {
    "Skittering Delirium Orb": "Currency",         # Currency items
    "Cartographer's Delirium Orb": "Currency",      # Maps (use currency proxy)
    "Diviner's Delirium Orb": "DivinationCard",     # Divination cards
    "Abyssal Delirium Orb": "Currency",             # Abyss items
    "Fossilised Delirium Orb": "Fossil",            # Fossils
    "Obscured Delirium Orb": "Currency",            # Veiled items
    "Whispering Delirium Orb": "Essence",           # Essences
    "Fine Delirium Orb": "Currency",                # Generic quality currency
    "Singular Delirium Orb": "UniqueWeapon",        # Uniques
    "Thaumaturge's Delirium Orb": "Currency",       # Quality currency
    "Timeless Delirium Orb": "Currency",            # Legion splinters/emblems
    "Fragmented Delirium Orb": "Fragment",          # Fragments
    "Armoursmith's Delirium Orb": "Currency",       # Armour currency
    "Blacksmith's Delirium Orb": "Currency",        # Weapon currency
    "Imperial Delirium Orb": "Currency",            # High-value mixed drops
}

# Estimated average chaos value per Delirium encounter for each reward type.
# These are community-calibrated estimates for 3.28 Mirage.
# They represent the average additional chaos value added by the delirium layer.
ORB_AVG_REWARD_VALUE: dict[str, float] = {
    "Skittering Delirium Orb": 15.0,
    "Cartographer's Delirium Orb": 8.0,
    "Diviner's Delirium Orb": 12.0,
    "Abyssal Delirium Orb": 6.0,
    "Fossilised Delirium Orb": 10.0,
    "Obscured Delirium Orb": 5.0,
    "Whispering Delirium Orb": 14.0,
    "Fine Delirium Orb": 4.0,
    "Singular Delirium Orb": 18.0,
    "Thaumaturge's Delirium Orb": 5.0,
    "Timeless Delirium Orb": 11.0,
    "Fragmented Delirium Orb": 9.0,
    "Armoursmith's Delirium Orb": 3.0,
    "Blacksmith's Delirium Orb": 3.0,
    "Imperial Delirium Orb": 25.0,
}


@dataclass
class DeliriumOrbEntry:
    orb_name: str
    orb_price: float
    est_reward_value: float
    profit: float
    roi_pct: float
    listings: int


def analyze_delirium_orbs(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
    mirage_multiplier: float = 1.0,
) -> list[DeliriumOrbEntry]:
    """
    Fetch Delirium Orb prices and calculate estimated profit per orb.
    mirage_multiplier: apply to reward estimates (Mirage can double the
    Delirium encounter, effectively doubling reward value per map).
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=DeliriumOrb"
    data = fetch_json(url, "DeliriumOrb", console)
    lines = data.get("lines", [])

    results: list[DeliriumOrbEntry] = []

    for line in lines:
        name = line.get("name")
        raw_price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)

        if not name or raw_price <= 0 or listings < 3:
            continue

        orb_price = get_safe_price(db_conn, name, raw_price)

        # Get estimated reward value, scaled by Mirage encounter multiplier
        est_reward = ORB_AVG_REWARD_VALUE.get(name, 8.0) * mirage_multiplier

        profit = est_reward - orb_price
        roi = (profit / orb_price * 100) if orb_price > 0 else 0

        results.append(DeliriumOrbEntry(
            orb_name=name,
            orb_price=orb_price,
            est_reward_value=est_reward,
            profit=profit,
            roi_pct=roi,
            listings=listings,
        ))

    results.sort(key=lambda x: x.profit, reverse=True)
    return results


def print_delirium_orb_table(entries: list[DeliriumOrbEntry], console: Console, limit: int = 15):
    if not entries:
        console.print("[yellow]No Delirium Orb data found on poe.ninja.[/yellow]")
        return

    table = Table(
        title="🌀 Delirium Orb Profit Calculator (3.28 Mirage)",
        show_header=True,
        header_style="bold blue",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Orb Name")
    table.add_column("Orb Cost (c)", justify="right")
    table.add_column("Est. Reward (c)", justify="right")
    table.add_column("Profit", justify="right", style="bold green")
    table.add_column("ROI", justify="right")
    table.add_column("Listings", justify="right")

    for rank, entry in enumerate(entries[:limit], start=1):
        roi_color = "green" if entry.roi_pct > 20 else ("yellow" if entry.roi_pct > 0 else "red")
        profit_str = f"+{entry.profit:,.1f}c" if entry.profit >= 0 else f"{entry.profit:,.1f}c"

        table.add_row(
            str(rank),
            entry.orb_name,
            f"{entry.orb_price:,.1f}",
            f"{entry.est_reward_value:,.1f}",
            profit_str,
            f"[{roi_color}]{entry.roi_pct:.1f}%[/{roi_color}]",
            str(entry.listings),
        )

    console.print(table)
    console.print("[dim]Reward estimates are community-calibrated averages × Mirage encounter multiplier.[/dim]")
    console.print("[dim]Actual returns depend on map tier, atlas passives, and delirium reward stacking.[/dim]")
