"""
POEStick — Gold Squeeze Advisor.
Compares Faustus (Instant) prices with Player Trade prices.
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
class GoldSqueezeEntry:
    item_name: str
    faustus_price: float
    player_price: float
    chaos_saved: float
    gold_cost: int
    chaos_per_k_gold: float

def analyze_gold_squeeze(league: str, db_conn: sqlite3.Connection, console: Optional[Console] = None) -> list[GoldSqueezeEntry]:
    """
    Simulate comparing Faustus (poe.ninja data) to Player Trade.
    In a real app, this would query the PoE Trade API.
    For this implementation, we compare ninja 'chaosEquivalent' vs 'pay' rates 
    which often diverge, or heuristic player discounts.
    """
    # Fetch Currency data as the main squeeze area
    url = f"https://poe.ninja/api/data/currencyoverview?league={league}&type=Currency"
    data = fetch_json(url, "Currency", console)
    lines = data.get("lines", [])
    
    results: list[GoldSqueezeEntry] = []
    
    for line in lines:
        name = line.get("currencyTypeName")
        faustus_price = line.get("chaosEquivalent", 0.0)
        
        # Heuristic: Player trade is often 5-15% cheaper for bulk, but let's look for
        # items where ninja's receive value (Faustus) is significantly higher than 
        # its own pay value (Player Trade representation in ninja data).
        pay_block = line.get("pay")
        if not pay_block or not name:
            continue
            
        player_price = 1.0 / pay_block.get("value") if pay_block.get("value", 0) > 0 else 0
        
        if player_price > 0 and faustus_price > player_price:
            # Current Market Price (Trend-Safe) for the Trade side
            trade_price = get_safe_price(db_conn, name, player_price)
            
            chaos_saved = faustus_price - trade_price
            # Standard trade Gold cost = 1500
            gold_cost = 1500 
            
            # Gold efficiency: profit per gold
            profit_per_gold = chaos_saved / gold_cost if gold_cost > 0 else 0
            efficiency = profit_per_gold * 1000 # Chaos saved per 1000 Gold
            
            if efficiency > 0.5: # Only show meaningful savings
                results.append(GoldSqueezeEntry(
                    item_name=name,
                    faustus_price=faustus_price,
                    player_price=trade_price,
                    chaos_saved=chaos_saved,
                    gold_cost=gold_cost,
                    chaos_per_k_gold=efficiency
                ))

    # Sort by efficiency descending
    results.sort(key=lambda x: x.chaos_per_k_gold, reverse=True)
    return results

def print_gold_squeeze_table(entries: list[GoldSqueezeEntry], console: Console, limit: int = 15):
    if not entries:
        console.print("[yellow]No significant Gold-to-Chaos savings detected.[/yellow]")
        return

    table = Table(
        title="💰 Gold Squeeze Advisor (Faustus vs Player Trade)",
        show_header=True,
        header_style="bold gold1",
        border_style="bright_black",
        expand=True
    )
    
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Item Name")
    table.add_column("Faustus (c)", justify="right")
    table.add_column("Player (c)", justify="right")
    table.add_column("Chaos Saved", justify="right", style="bold green")
    table.add_column("Squeeze Efficiency", justify="right")

    for rank, entry in enumerate(entries[:limit], start=1):
        table.add_row(
            str(rank),
            entry.item_name,
            f"{entry.faustus_price:,.2f}",
            f"{entry.player_price:,.2f}",
            f"{entry.chaos_saved:,.2f}c",
            f"[bold cyan]{entry.chaos_per_k_gold:.2f}[/bold cyan] c/kG"
        )
        
    console.print(table)
    console.print("[dim]Efficiency = Chaos saved per 1,000 Gold spent on Faustus.[/dim]")
    console.print("[dim]Higher efficiency = better for players with low Gold and high patience.[/dim]")
