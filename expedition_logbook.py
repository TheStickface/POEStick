"""
POEStick — Expedition Logbook Value Estimator.
Estimates expected value per logbook type based on known reward prices.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price

# Logbook faction → associated high-value reward categories and items.
# EV estimates come from community data on average returns per logbook.
LOGBOOK_FACTIONS = {
    "Knights of the Sun": {
        "display": "Templar (Knights of the Sun)",
        "avg_currency_drops": 12.0,
        "big_ticket_items": [],  # No specific jackpots
        "npc": "Dannig",
    },
    "Black Scythe Mercenaries": {
        "display": "Karui (Black Scythe)",
        "avg_currency_drops": 15.0,
        "big_ticket_items": [],
        "npc": "Rog",
    },
    "Order of the Chalice": {
        "display": "Maraketh (Order of the Chalice)",
        "avg_currency_drops": 18.0,
        "big_ticket_items": ["Mageblood", "Headhunter"],
        "npc": "Gwennen",
    },
    "Druids of the Broken Circle": {
        "display": "Eternal (Druids of the Broken Circle)",
        "avg_currency_drops": 14.0,
        "big_ticket_items": [],
        "npc": "Tujen",
    },
}


@dataclass
class LogbookEntry:
    faction: str
    display_name: str
    npc: str
    logbook_price: float
    est_value: float
    profit: float
    roi_pct: float
    has_jackpot: bool
    listings: int


def analyze_logbooks(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
    mirage_multiplier: float = 1.0,
) -> list[LogbookEntry]:
    """
    Fetch Logbook prices and estimate profit per run.
    """
    # Logbooks are listed under the "Map" category on poe.ninja
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Map"
    data = fetch_json(url, "Map", console)
    map_lines = data.get("lines", [])

    # Also get currency for Exotic Coinage / Astragali / Scrap Metal / Burial Medallion
    url_curr = f"https://poe.ninja/api/data/currencyoverview?league={league}&type=Currency"
    curr_data = fetch_json(url_curr, "Currency (Expedition)", console)
    curr_lines = curr_data.get("lines", [])

    # Get prices for expedition currencies to refine EV
    expedition_currencies = {}
    for c in curr_lines:
        cname = c.get("currencyTypeName", "")
        if cname in ("Exotic Coinage", "Astragali", "Scrap Metal", "Burial Medallion"):
            raw = c.get("chaosEquivalent", 0.0)
            if raw > 0:
                expedition_currencies[cname] = get_safe_price(db_conn, cname, raw)

    # Find logbook prices
    logbook_prices: dict[str, dict] = {}
    for line in map_lines:
        name = line.get("name", "")
        base_type = line.get("baseType", "")
        raw_price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)

        # Logbooks appear as "Expedition Logbook" with variant = faction
        if "Logbook" in name or "Logbook" in base_type:
            variant = line.get("variant", "")
            if not variant:
                variant = name

            if raw_price > 0 and listings >= 2:
                safe_price = get_safe_price(db_conn, f"Logbook_{variant}", raw_price)
                logbook_prices[variant] = {"price": safe_price, "listings": listings}

    # Also try to find logbooks by name pattern
    for line in map_lines:
        name = line.get("name", "")
        raw_price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)

        for faction_key in LOGBOOK_FACTIONS:
            if faction_key.lower() in name.lower() and faction_key not in logbook_prices:
                if raw_price > 0 and listings >= 2:
                    safe_price = get_safe_price(db_conn, f"Logbook_{faction_key}", raw_price)
                    logbook_prices[faction_key] = {"price": safe_price, "listings": listings}

    results: list[LogbookEntry] = []

    for faction_key, faction_info in LOGBOOK_FACTIONS.items():
        if faction_key not in logbook_prices:
            continue

        lb_data = logbook_prices[faction_key]
        lb_price = lb_data["price"]
        listings = lb_data["listings"]

        # Base EV from average currency drops, scaled by Mirage multiplier
        # (Mirage can spawn a second Expedition encounter per map)
        ev = faction_info["avg_currency_drops"] * mirage_multiplier

        # Add bonus from expedition currency prices (Tujen/Gwennen markup)
        npc = faction_info["npc"]
        if npc == "Tujen" and "Exotic Coinage" in expedition_currencies:
            ev += expedition_currencies["Exotic Coinage"] * 2.0  # ~2 coins per logbook avg
        elif npc == "Gwennen" and "Astragali" in expedition_currencies:
            ev += expedition_currencies["Astragali"] * 3.0  # ~3 astragali per logbook avg
        elif npc == "Rog" and "Scrap Metal" in expedition_currencies:
            ev += expedition_currencies["Scrap Metal"] * 2.5
        elif npc == "Dannig" and "Burial Medallion" in expedition_currencies:
            ev += expedition_currencies["Burial Medallion"] * 2.0

        has_jackpot = len(faction_info["big_ticket_items"]) > 0

        profit = ev - lb_price
        roi = (profit / lb_price * 100) if lb_price > 0 else 0

        results.append(LogbookEntry(
            faction=faction_key,
            display_name=faction_info["display"],
            npc=npc,
            logbook_price=lb_price,
            est_value=ev,
            profit=profit,
            roi_pct=roi,
            has_jackpot=has_jackpot,
            listings=listings,
        ))

    results.sort(key=lambda x: x.profit, reverse=True)
    return results


def print_logbook_table(entries: list[LogbookEntry], console: Console, limit: int = 20):
    if not entries:
        console.print("[yellow]No Expedition Logbook pricing data found on poe.ninja.[/yellow]")
        return

    table = Table(
        title="🗺️ Expedition Logbook Value Estimator (3.28 Mirage)",
        show_header=True,
        header_style="bold yellow",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("Faction", style="bold")
    table.add_column("NPC")
    table.add_column("Logbook (c)", justify="right")
    table.add_column("Est. Value (c)", justify="right")
    table.add_column("Profit", justify="right", style="bold green")
    table.add_column("ROI", justify="right")
    table.add_column("🎰", justify="center")
    table.add_column("Listings", justify="right")

    for entry in entries:
        roi_color = "green" if entry.roi_pct > 15 else ("yellow" if entry.roi_pct > 0 else "red")
        profit_str = f"+{entry.profit:,.1f}c" if entry.profit >= 0 else f"{entry.profit:,.1f}c"
        jackpot = "✅" if entry.has_jackpot else ""

        table.add_row(
            entry.display_name,
            entry.npc,
            f"{entry.logbook_price:,.1f}",
            f"{entry.est_value:,.1f}",
            profit_str,
            f"[{roi_color}]{entry.roi_pct:.1f}%[/{roi_color}]",
            jackpot,
            str(entry.listings),
        )

    console.print(table)
    console.print("[dim]🎰 = Gwennen gamble chance (Mageblood/HH). EV is average without jackpots.[/dim]")
    console.print("[dim]EV scaled by Mirage encounter multiplier (Mirage can spawn a second Expedition per map).[/dim]")
    console.print("[dim]Returns depend on atlas passives, remnant mods, and expedition currency prices.[/dim]")
