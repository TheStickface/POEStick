"""
POEStick — Stacked Deck EV Calculator.
Calculates the expected chaos value of a single Stacked Deck.
Uses community-derived rarity weightings for Divination Cards.
"""

from __future__ import annotations
from typing import Optional, TypedDict, List, Dict, Any, cast
import sqlite3
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.panel import Panel

from api import fetch_json
from pricing import get_safe_price

# Weighted distribution model (Representative heuristics for 3.28)
# Higher tier = lower weight (rarer)
RARITY_WEIGHTS = {
    "Tier 0": 1,        # Ultra-Rare (Apothecary, House of Mirrors)
    "Tier 1": 50,       # High-Value (The Doctor, The Fiend, Seven Years Bad Luck)
    "Tier 2": 250,      # Valuable (The Immortal, Wealth and Power)
    "Tier 3": 1500,     # Uncommon (The Saint's Treasure, The Dragon's Heart)
    "Tier 4": 10000,    # Common (The Scholar, Her Mask, etc.)
}

class StackedDeckResult(TypedDict):
    ev: float
    deck_price: float
    profit_per_deck: float
    margin_pct: float
    tier_data: Dict[str, float]
    # Cloister Scarab adjusted fields (0 if scarab not factored in)
    cloister_scarab_cost: float
    decks_per_map: float          # heuristic: extra decks from Cloister Scarab per map
    cost_per_deck_with_scarab: float
    profit_per_deck_with_scarab: float

def analyze_stacked_deck_ev(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
    cloister_scarab_cost: float = 0.0,
    mirage_multiplier: float = 1.0,
) -> StackedDeckResult:
    """
    Fetch all Divination Card prices and apply heuristic weights to find EV.

    If cloister_scarab_cost > 0, also calculates adjusted cost-per-deck
    for the Divination Scarab of The Cloister farming strategy.
    Heuristic: Cloister Scarab yields ~85 Stacked Decks per map (midpoint of
    80-100 community reports from week-1 Mirage). Mirage may double-spawn
    Cloister packs — apply mirage_multiplier to the deck yield if confirmed.
    """
    CLOISTER_DECKS_PER_MAP = 85.0
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=DivinationCard"
    data = fetch_json(url, "DivinationCard", console)
    lines: List[Dict[str, Any]] = data.get("lines", [])
    
    # Sort cards by price to bucket them into tiers
    processed_cards: List[Dict[str, Any]] = []
    for card in lines:
        name = card.get("name")
        chaos_value = card.get("chaosValue")
        if name and isinstance(chaos_value, (int, float)):
            safe_value = get_safe_price(db_conn, str(name), float(chaos_value))
            processed_cards.append({"name": str(name), "chaosValue": float(safe_value)})

    # Use a clear key function for sorting to help type checker
    def get_val(c: Dict[str, Any]) -> float:
        v = c.get("chaosValue", 0.0)
        return float(v) if isinstance(v, (int, float)) else 0.0

    sorted_cards = sorted(processed_cards, key=get_val, reverse=True)
    
    # Bucket into 5 tiers based on price ranges
    buckets: Dict[str, List[float]] = {
        "Tier 0": [], # > 2000c
        "Tier 1": [], # 500c - 2000c
        "Tier 2": [], # 100c - 500c
        "Tier 3": [], # 10c - 100c
        "Tier 4": [], # < 10c
    }
    
    for card in sorted_cards:
        val = get_val(card)
        if val > 2000: buckets["Tier 0"].append(val)
        elif val > 500: buckets["Tier 1"].append(val)
        elif val > 100: buckets["Tier 2"].append(val)
        elif val > 10:  buckets["Tier 3"].append(val)
        else:           buckets["Tier 4"].append(val)

    # Calculate average value per tier
    tier_averages: Dict[str, float] = {}
    for tier, vals in buckets.items():
        tier_averages[tier] = sum(vals) / len(vals) if vals else 0.0
        
    # Calculate weighted EV
    weighted_sum = 0.0
    total_weight = float(sum(RARITY_WEIGHTS.values()))
    
    for tier, weight in RARITY_WEIGHTS.items():
        weighted_sum += tier_averages[tier] * float(weight)
        
    ev = weighted_sum / total_weight
    
    # Get current bulk price of Stacked Decks and apply safe pricing
    url_curr = f"https://poe.ninja/api/data/currencyoverview?league={league}&type=Currency"
    curr_data = fetch_json(url_curr, "Currency", console)
    curr_lines: List[Dict[str, Any]] = curr_data.get("lines", [])
    
    raw_deck_price = 0.0
    for l in curr_lines:
        if l.get("currencyTypeName") == "Stacked Deck":
            raw_deck_price = float(l.get("chaosEquivalent", 0.0))
            break
            
    deck_price = get_safe_price(db_conn, "Stacked Deck", raw_deck_price)

    # Cloister Scarab adjusted metrics (Mirage may double-spawn Cloister packs)
    cost_per_deck_with_scarab = 0.0
    profit_per_deck_with_scarab = 0.0
    effective_decks = CLOISTER_DECKS_PER_MAP * mirage_multiplier
    if cloister_scarab_cost > 0 and effective_decks > 0:
        # Scarab cost amortized over the decks it generates (Mirage-adjusted)
        cost_per_deck_with_scarab = float(deck_price + cloister_scarab_cost / effective_decks)
        profit_per_deck_with_scarab = float(ev - cost_per_deck_with_scarab)

    return {
        "ev": float(ev),
        "deck_price": float(deck_price),
        "profit_per_deck": float(ev - deck_price),
        "margin_pct": float(((ev - deck_price) / deck_price * 100) if deck_price > 0 else 0.0),
        "tier_data": tier_averages,
        "cloister_scarab_cost": float(cloister_scarab_cost),
        "decks_per_map": effective_decks,
        "cost_per_deck_with_scarab": cost_per_deck_with_scarab,
        "profit_per_deck_with_scarab": profit_per_deck_with_scarab,
    }

def print_stacked_deck_table(result: StackedDeckResult, console: Console):
    ev = result["ev"]
    deck_p = result["deck_price"]
    profit = result["profit_per_deck"]
    margin = result["margin_pct"]
    
    title = Text("🃏 Stacked Deck Expected Value (3.28 Mirage)", style="bold cyan")
    console.print(title)
    
    # Summary Info
    color = "bold green" if profit > 0 else "bold red"
    
    summary_text = Text()
    summary_text.append(f" Market Price:   ", style="dim")
    summary_text.append(f"{deck_p:,.2f}c\n", style="yellow")
    summary_text.append(f" Expected Value: ", style="dim")
    summary_text.append(f"{ev:,.2f}c\n", style="white")
    summary_text.append(f" Profit/Deck:    ", style="dim")
    summary_text.append(f"{profit:+.2f}c\n", style=color)
    summary_text.append(f" Margin:         ", style="dim")
    summary_text.append(f"{margin:.1f}%\n", style=color)
    
    rec = "OPEN" if profit > 0 else "SELL BULK"
    summary_text.append(f" Recommendation: ", style="bold")
    summary_text.append(rec, style="bold white underline")

    # Cloister Scarab section
    scarab_cost = result.get("cloister_scarab_cost", 0.0)
    if scarab_cost > 0:
        cost_adj = result.get("cost_per_deck_with_scarab", 0.0)
        profit_adj = result.get("profit_per_deck_with_scarab", 0.0)
        decks = result.get("decks_per_map", 0.0)
        scarab_color = "green" if profit_adj > 0 else "red"
        summary_text.append(f"\n\n [bold]Cloister Scarab Strategy[/bold]\n")
        summary_text.append(f" Scarab Cost:     ", style="dim")
        summary_text.append(f"{scarab_cost:.1f}c\n", style="yellow")
        summary_text.append(f" Decks per map:   ", style="dim")
        summary_text.append(f"~{decks:.0f}\n", style="white")
        summary_text.append(f" Cost/deck (adj): ", style="dim")
        summary_text.append(f"{cost_adj:.2f}c\n", style="white")
        summary_text.append(f" Profit/deck:     ", style="dim")
        summary_text.append(f"{profit_adj:+.2f}c", style=f"bold {scarab_color}")

    console.print(Panel(summary_text, border_style="bright_black"))

    # Tier Breakdown Table
    table = Table(title="Tier Probability & Value Breakdown", border_style="dim", expand=True)
    table.add_column("Tier", style="dim")
    table.add_column("Avg Card Value", justify="right")
    table.add_column("Est. Weight", justify="right")
    table.add_column("Chance", justify="right")
    
    total_w = float(sum(RARITY_WEIGHTS.values()))
    for tier, weight in RARITY_WEIGHTS.items():
        chance = (float(weight) / total_w) * 100
        table.add_row(
            tier,
            f"{result['tier_data'][tier]:,.1f}c",
            str(weight),
            f"{chance:.4f}%"
        )
    console.print(table)
    console.print(Text("Weights are heuristic based on aggregate pull data.", style="dim italic"))
