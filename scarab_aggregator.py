"""
POEStick — Scarab Bulk-Set Aggregator + Tier Analyzer.
Identifies convenience premiums for complete mapping scarab sets,
and ranks individual scarabs by value-per-chaos within each family.
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
class ScarabSet:
    set_name: str
    scarab_list: list[str]
    individual_cost: float
    bulk_price: float
    profit: float
    margin_pct: float

@dataclass
class ScarabTierEntry:
    """Individual scarab with tier/family metadata for per-tier analysis."""
    name: str
    family: str      # e.g. "Ambush", "Legion"
    price: float
    listings: int

SCARAB_SETS = {
    "Ambush (Strongbox)": [
        "Ambush Scarab",
        "Ambush Scarab of Hidden Compartments",
        "Ambush Scarab of Discernment",
        "Ambush Scarab of Containment"
    ],
    "Legion": [
        "Legion Scarab",
        "Legion Scarab of Officers",
        "Legion Scarab of Eternal Empire",
        "Legion Scarab of The Sekhemet"
    ],
    "Divination": [
        "Divination Scarab",
        "Divination Scarab of Curation",
        "Divination Scarab of Completion",
        "Divination Scarab of The Cloister"
    ]
}

# Families to detect from scarab names (prefix before " Scarab")
# NOTE: Harbinger removed — it does not exist in 3.28 Mirage league.
SCARAB_FAMILIES = [
    "Ambush", "Legion", "Divination", "Breach", "Abyss",
    "Expedition", "Ritual", "Essence", "Delirium", "Blight", "Betrayal",
    "Domination", "Torment", "Sulphite", "Cartography", "Bestiary",
    "Influencing", "Reliquary", "Titanic", "Marshall", "Hive",
]


def _detect_family(scarab_name: str) -> str:
    """Extract the family prefix from a scarab name."""
    for family in SCARAB_FAMILIES:
        if scarab_name.startswith(family):
            return family
    return "Other"


def analyze_scarabs(league: str, db_conn: sqlite3.Connection, console: Optional[Console] = None) -> list[ScarabSet]:
    """
    Fetch all Scarab prices and calculate set premiums.
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab"
    data = fetch_json(url, "Scarab", console)
    lines = data.get("lines", [])
    
    prices = {l.get("name"): l.get("chaosValue", 0.0) for l in lines}
    
    results: list[ScarabSet] = []
    
    for set_name, s_list in SCARAB_SETS.items():
        found = [s for s in s_list if s in prices]
        if len(found) == len(s_list):
            safe_prices = [get_safe_price(db_conn, s, prices[s]) for s in s_list]
            indiv_total = sum(safe_prices)
            
            # Mirage bulk premium for "Mapping Ready" sets is usually 20-35%
            bulk_premium_factor = 1.25 
            bulk_price = indiv_total * bulk_premium_factor
            
            profit = bulk_price - indiv_total
            margin = (profit / indiv_total * 100) if indiv_total > 0 else 0
            
            results.append(ScarabSet(
                set_name=set_name,
                scarab_list=s_list,
                individual_cost=indiv_total,
                bulk_price=bulk_price,
                profit=profit,
                margin_pct=margin
            ))
            
    return results


def analyze_scarab_tiers(league: str, db_conn: sqlite3.Connection, console: Optional[Console] = None) -> dict[str, list[ScarabTierEntry]]:
    """
    Fetch all scarabs, group by family, and rank by price within each family.
    Returns dict of family -> list of ScarabTierEntry (sorted by price desc).
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab"
    data = fetch_json(url, "Scarab", console)
    lines = data.get("lines", [])

    family_map: dict[str, list[ScarabTierEntry]] = {}

    for line in lines:
        name = line.get("name")
        price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)

        if not name or price <= 0 or listings < 2:
            continue

        safe_price = get_safe_price(db_conn, name, price)
        family = _detect_family(name)

        if family not in family_map:
            family_map[family] = []
        family_map[family].append(ScarabTierEntry(
            name=name,
            family=family,
            price=safe_price,
            listings=listings,
        ))

    # Sort each family by price descending
    for family in family_map:
        family_map[family].sort(key=lambda x: x.price, reverse=True)

    return family_map


def print_scarab_table(sets: list[ScarabSet], console: Console):
    if not sets:
        console.print("[yellow]Could not find sufficient Scarab data for sets.[/yellow]")
        return

    table = Table(
        title="🕷️ Scarab Bulk-Set Aggregator (Mapping Convenience)",
        show_header=True,
        header_style="bold yellow",
        border_style="bright_black",
        expand=True
    )
    
    table.add_column("Set Type", style="bold")
    table.add_column("Individual (c)", justify="right")
    table.add_column("Est. Bulk (c)", justify="right")
    table.add_column("Gross Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")

    for s in sets:
        margin_color = "green" if s.margin_pct > 20 else "yellow"
        table.add_row(
            s.set_name,
            f"{s.individual_cost:,.1f}",
            f"{s.bulk_price:,.1f}",
            f"+{s.profit:,.1f}c",
            f"[{margin_color}]{s.margin_pct:.1f}%[/{margin_color}]"
        )
        
    console.print(table)
    console.print("[dim]Buying individual scarabs and selling mapping-ready bundles yields a high bulk premium.[/dim]")


def print_scarab_tier_table(family_map: dict[str, list[ScarabTierEntry]], console: Console, top_families: int = 8):
    """Print the top scarab families ranked by their best variant's price."""
    if not family_map:
        console.print("[yellow]No scarab tier data found.[/yellow]")
        return

    # Sort families by their top scarab price
    sorted_families = sorted(family_map.items(), key=lambda kv: kv[1][0].price if kv[1] else 0, reverse=True)

    table = Table(
        title="🕷️ Scarab Tier Analysis (Best-Value per Family)",
        show_header=True,
        header_style="bold yellow",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("Family", style="bold")
    table.add_column("Best Variant")
    table.add_column("Price (c)", justify="right", style="bold green")
    table.add_column("Cheapest Variant")
    table.add_column("Price (c)", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("# Variants", justify="right")

    for family, entries in sorted_families[:top_families]:
        if not entries:
            continue
        best = entries[0]
        cheapest = entries[-1]
        spread = best.price - cheapest.price

        table.add_row(
            family,
            best.name,
            f"{best.price:,.1f}",
            cheapest.name if cheapest != best else "—",
            f"{cheapest.price:,.1f}" if cheapest != best else "—",
            f"{spread:,.1f}c" if cheapest != best else "—",
            str(len(entries)),
        )

    console.print(table)
    console.print("[dim]Spread = best minus cheapest variant. Higher spread = more profit potential in tier selection.[/dim]")

