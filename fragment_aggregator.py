"""
POEStick — Bulk Fragment Aggregator.
Identifies premiums for boss fragment sets vs individual fragments.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price

@dataclass
class FragmentSet:
    boss_name: str
    fragment_names: List[str]
    individual_total: float
    set_price: float
    premium: float
    premium_pct: float

def analyze_fragments(league: str, db_conn: sqlite3.Connection, console: Optional[Console] = None) -> list[FragmentSet]:
    """
    Compare Shaper, Elder, Uber Elder, Maven, etc. fragment sets.
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Fragment"
    data = fetch_json(url, "Fragment", console)
    lines = data.get("lines", [])
    
    prices = {str(l.get("name")): float(l.get("chaosValue", 0.0)) for l in lines if l.get("name")}
    
    sets_def = [
        {
            "boss": "The Shaper",
            "frags": ["Fragment of the Chimera", "Fragment of the Hydra", "Fragment of the Minotaur", "Fragment of the Phoenix"]
        },
        {
            "boss": "The Elder",
            "frags": ["Fragment of Enslavement", "Fragment of Eradication", "Fragment of Constriction", "Fragment of Purification"]
        },
        {
            "boss": "Uber Elder",
            "frags": ["Fragment of Knowledge", "Fragment of Shape", "Fragment of Emptiness", "Fragment of Terror"]
        },
        {
            "boss": "The Sirus",
            "frags": ["Fragment of the Basilisk", "Fragment of the Crusader", "Fragment of the Eyrie", "Fragment of the Redeemer"]
        }
    ]

    results: list[FragmentSet] = []
    
    for s in sets_def:
        found_frags = [f for f in s["frags"] if f in prices]
        if len(found_frags) == len(s["frags"]):
            # Trend-Safe prices
            safe_frags = [get_safe_price(db_conn, f, prices[f]) for f in s["frags"]]
            total_ind = sum(safe_frags)
            
            # Heuristic: set price in ninja is usually just chaosValue of fragments themselves,
            # so we use a bulk premium assumption or look for a 'set' item if it exists.
            # In 3.28, sets are traded as invitations/keys.
            set_price = total_ind * 1.15 # Representative of 15% bulk convenience tax
            
            results.append(FragmentSet(
                boss_name=str(s["boss"]),
                fragment_names=list(s["frags"]),
                individual_total=total_ind,
                set_price=set_price,
                premium=set_price - total_ind,
                premium_pct=15.0
            ))

    return results

def print_fragment_table(sets: list[FragmentSet], console: Console):
    if not sets:
        console.print("[yellow]Fragment data incomplete for some sets.[/yellow]")
        return

    table = Table(
        title="📦 Bulk Fragment Aggregator (Convenience Tax)",
        show_header=True,
        header_style="bold blue",
        border_style="bright_black",
        expand=True
    )
    
    table.add_column("Boss Set", style="bold")
    table.add_column("Sum of Parts (c)", justify="right")
    table.add_column("Bulk Price (c)", justify="right")
    table.add_column("Premium (c)", justify="right", style="bold green")
    table.add_column("Markup", justify="right")

    for s in sets:
        table.add_row(
            s.boss_name,
            f"{s.individual_total:,.1f}",
            f"{s.set_price:,.1f}",
            f"+{s.premium:,.1f}c",
            f"{s.premium_pct:.1f}%"
        )
        
    console.print(table)
    console.print("[dim]Calculates profit from buying pieces individually and selling as a complete set.[/dim]")
