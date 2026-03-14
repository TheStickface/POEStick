"""
POEStick — Wombgift & Chitinous Implicit Evaluator.
Prices 3.28 Mirage specific crafting rewards and upgrades.
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
class WombgiftUpgrade:
    base_name: str
    upgraded_name: str
    base_price: float
    upgraded_price: float
    profit: float
    margin_pct: float
    listings: int

def fetch_category_data(league: str, category: str, console: Optional[Console] = None) -> list[dict]:
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type={category}"
    data = fetch_json(url, category, console)
    return data.get("lines", [])

def analyze_wombgifts(league: str, db_conn: sqlite3.Connection, console: Optional[Console] = None) -> list[WombgiftUpgrade]:
    """
    Search for items that are typically upgraded via Wombgifts or have Chitinous versions.
    """
    # Categories to check — UniqueWeapon excluded: Wombgifts can no longer
    # grow Weapon or Quiver items on the Genesis Tree (3.28 patch notes).
    categories = ["UniqueArmour", "UniqueAccessory"]
    all_items = {}
    
    for cat in categories:
        lines = fetch_category_data(league, cat, console)
        for line in lines:
            name = line.get("name")
            price = line.get("chaosValue", 0.0)
            listings = line.get("listingCount", 0)
            if name and price > 0:
                all_items[name] = {"price": price, "listings": listings}

    upgrades: list[WombgiftUpgrade] = []
    
    for name, data in all_items.items():
        # Look for "Chitinous" variants or others
        if name.startswith("Chitinous "):
            base_name = name.replace("Chitinous ", "")
            if base_name in all_items:
                base_data = all_items[base_name]
                
                # Trend-Safe Price for the upgraded item
                raw_up_price = data["price"]
                up_price = get_safe_price(db_conn, name, raw_up_price)
                
                profit = up_price - base_data["price"]
                margin = (profit / base_data["price"] * 100) if base_data["price"] > 0 else 0
                
                upgrades.append(WombgiftUpgrade(
                    base_name=base_name,
                    upgraded_name=name,
                    base_price=base_data["price"],
                    upgraded_price=data["price"],
                    profit=profit,
                    margin_pct=margin,
                    listings=data["listings"]
                ))

    # Sort by profit descending
    upgrades.sort(key=lambda x: x.profit, reverse=True)
    return upgrades

def print_wombgift_table(upgrades: list[WombgiftUpgrade], console: Console, limit: int = 15):
    if not upgrades:
        console.print("[yellow]No Chitinous upgrades found in current market data.[/yellow]")
        return

    table = Table(
        title="🧪 Wombgift & Chitinous Evaluator (3.28 Mirage)",
        show_header=True,
        header_style="bold green",
        border_style="bright_black",
        expand=True
    )
    
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Base Item")
    table.add_column("Upgraded (Chitinous)")
    table.add_column("Base (c)", justify="right")
    table.add_column("Upgrade (c)", justify="right")
    table.add_column("Gross Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")

    for rank, upg in enumerate(upgrades[:limit], start=1):
        margin_color = "green" if upg.margin_pct > 20 else ("yellow" if upg.margin_pct > 0 else "red")
        
        table.add_row(
            str(rank),
            upg.base_name,
            upg.upgraded_name,
            f"{upg.base_price:,.1f}",
            f"{upg.upgraded_price:,.1f}",
            f"+{upg.profit:,.1f}c",
            f"[{margin_color}]{upg.margin_pct:.1f}%[/{margin_color}]"
        )
        
    console.print(table)
    console.print("[dim]Note: Profitable Chitinous upgrades usually signify a high-value Wombgift roll.[/dim]")
