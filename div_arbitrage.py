"""
POEStick — Divination Card Arbitrage Analyzer.
Calculates the profit from completing Divination Card sets.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Dict

import sqlite3
from rich.console import Console
from rich.table import Table

from api import fetch_json
from pricing import get_safe_price

@dataclass
class DivCardCraft:
    card_name: str
    reward_name: str
    stack_size: int
    card_price: float
    reward_price: float
    set_cost: float
    profit: float
    margin_pct: float
    card_listings: int

def fetch_category_data(league: str, category: str, console: Optional[Console] = None) -> list[dict]:
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type={category}"
    data = fetch_json(url, category, console)
    return data.get("lines", [])

def analyze_div_cards(league: str, db_conn: sqlite3.Connection, min_listings: int = 10, console: Optional[Console] = None) -> list[DivCardCraft]:
    """
    Fetch Divination Card data and reward categories, then find profitable sets.
    """
    if min_listings is None:
        min_listings = 10
        
    card_lines = fetch_category_data(league, "DivinationCard", console)
    
    # We need reward data from other categories to price the outcomes
    reward_categories = [
        "Currency", "UniqueArmour", "UniqueAccessory", "UniqueWeapon", 
        "UniqueJewel", "Fragment", "Essence", "Resonator", "Artifact"
    ]
    
    all_reward_lines: List[Dict] = []
    for cat in reward_categories:
        all_reward_lines.extend(fetch_category_data(league, cat, console))

    # Pass 1: Collect rewards and their safe prices
    rewards_by_name: Dict[str, float] = {}
    for line in all_reward_lines:
        name = line.get("name")
        chaos_value = line.get("chaosValue")
        
        if not chaos_value:
            # For currency types
            receive = line.get("receive")
            if isinstance(receive, dict):
                chaos_value = receive.get("value", 0.0)
        
        if isinstance(name, str) and name and isinstance(chaos_value, (int, float)) and chaos_value > 0:
            rewards_by_name[name] = get_safe_price(db_conn, name, float(chaos_value))

    crafts: list[DivCardCraft] = []
    
    # Pass 2: Pair with cards
    for card in card_lines:
        card_name = card.get("name")
        stack_size = card.get("stackSize", 0)
        card_price = card.get("chaosValue", 0.0)
        listings = card.get("listingCount", 0)
        
        if not isinstance(card_name, str) or not card_name or stack_size <= 0 or listings < min_listings or card_price <= 0:
            continue
            
        # Parse the reward name from explicitModifiers
        reward_name: Optional[str] = None
        mods = card.get("explicitModifiers", [])
        for mod in mods:
            m_text = mod.get("text", "")
            if m_text.startswith("<item>"):
                reward_name = m_text.replace("<item>{", "").replace("}", "")
                break
        
        if not reward_name or reward_name not in rewards_by_name:
            continue

        raw_reward_price = rewards_by_name[reward_name]
        # reward price is already trend-safe from Pass 1
        
        f_stack = int(stack_size)
        f_card_p = float(card_price)
        f_reward_p = float(raw_reward_price)
        
        cost = f_stack * f_card_p
        profit = f_reward_p - cost
        margin_pct = (profit / cost * 100) if cost > 0 else 0
        
        crafts.append(DivCardCraft(
            card_name=str(card_name),
            reward_name=str(reward_name),
            stack_size=f_stack,
            card_price=f_card_p,
            reward_price=f_reward_p,
            set_cost=cost,
            profit=profit,
            margin_pct=margin_pct,
            card_listings=int(listings)
        ))

    # Sort by profit descending
    crafts.sort(key=lambda x: x.profit, reverse=True)
    return crafts

def print_div_card_table(crafts: list[DivCardCraft], console: Console, limit: int = 15):
    if not crafts:
        console.print("[yellow]No Divination Card arbitrage found. Check filters or API status.[/yellow]")
        return

    table = Table(
        title="🎴 Divination Card Arbitrage (Set Completion)",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True
    )
    
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Card Name")
    table.add_column("Set Size", justify="right")
    table.add_column("Reward", style="bold magenta")
    table.add_column("Set Cost (c)", justify="right")
    table.add_column("Reward Val (c)", justify="right")
    table.add_column("Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")

    for rank, craft in enumerate(crafts[:limit], start=1):
        margin_color = "green" if craft.margin_pct > 15 else ("yellow" if craft.margin_pct > 0 else "red")
        
        table.add_row(
            str(rank),
            craft.card_name,
            str(craft.stack_size),
            craft.reward_name,
            f"{craft.set_cost:,.1f}",
            f"{craft.reward_price:,.1f}",
            f"{craft.profit:,.1f}c",
            f"[{margin_color}]{craft.margin_pct:.1f}%[/{margin_color}]"
        )
        
    console.print(table)
    console.print("[dim]Note: Only identifies cards with explicit item rewards indexed by poe.ninja.[/dim]")
