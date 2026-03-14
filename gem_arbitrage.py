"""
POEStick — Gem Arbitrage Scanner.
Identifies profit in Awakened/Exceptional gem leveling and quality flips.
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
class GemFlip:
    gem_name: str
    flip_type: str        # "Level", "Quality", or "Exceptional"
    buy_label: str        # e.g. "Lv1 0q" or "0q"
    sell_label: str       # e.g. "Lv5 20q" or "20q"
    buy_price: float
    sell_price: float
    profit: float
    margin_pct: float
    buy_listings: int
    sell_listings: int


def _build_gem_lookup(lines: list[dict], db_conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """
    Group gem lines by base name. Each entry keeps level, quality, price, listings.
    """
    lookup: dict[str, list[dict]] = {}
    for line in lines:
        name = line.get("name")
        if not name:
            continue

        level = line.get("gemLevel", 1)
        quality = line.get("gemQuality", 0)
        raw_price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)
        corrupted = line.get("corrupted", False)

        if raw_price <= 0 or listings < 2:
            continue

        # Skip corrupted gems — can't be leveled
        if corrupted:
            continue

        price = get_safe_price(db_conn, f"{name}_L{level}_Q{quality}", raw_price)

        if name not in lookup:
            lookup[name] = []
        lookup[name].append({
            "level": level,
            "quality": quality,
            "price": price,
            "listings": listings,
        })

    return lookup


def analyze_gems(
    league: str,
    db_conn: sqlite3.Connection,
    min_listings: int = 3,
    console: Optional[Console] = None,
) -> list[GemFlip]:
    """
    Fetch SkillGem data and identify profitable flips:
    1. Level 1 → Level 5+ awakened/exceptional gems
    2. 0 quality → 20 quality flips
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=SkillGem"
    data = fetch_json(url, "SkillGem", console)
    lines = data.get("lines", [])

    lookup = _build_gem_lookup(lines, db_conn)
    results: list[GemFlip] = []

    for gem_name, variants in lookup.items():
        # Sort by level ascending, then quality ascending
        variants.sort(key=lambda v: (v["level"], v["quality"]))

        # --- Level flips: buy low level, sell high level (same quality bracket) ---
        # Group by quality bracket (0, 20)
        by_quality: dict[int, list[dict]] = {}
        for v in variants:
            q = v["quality"]
            q_key = 20 if q >= 20 else 0
            if q_key not in by_quality:
                by_quality[q_key] = []
            by_quality[q_key].append(v)

        for q_key, q_variants in by_quality.items():
            if len(q_variants) < 2:
                continue

            # Find cheapest (buy) and most expensive (sell) by level
            buy_v = min(q_variants, key=lambda v: v["price"])
            sell_v = max(q_variants, key=lambda v: v["price"])

            if buy_v["level"] >= sell_v["level"]:
                continue  # same level, skip

            if buy_v["listings"] < min_listings or sell_v["listings"] < min_listings:
                continue

            profit = sell_v["price"] - buy_v["price"]
            margin = (profit / buy_v["price"] * 100) if buy_v["price"] > 0 else 0

            if profit > 1.0:  # At least 1c profit
                flip_type = "Level"
                if gem_name.startswith("Awakened "):
                    flip_type = "Awakened"
                elif "Exceptional" in gem_name or gem_name.startswith("Divergent ") or gem_name.startswith("Anomalous ") or gem_name.startswith("Phantasmal "):
                    flip_type = "Alt Qual"

                results.append(GemFlip(
                    gem_name=gem_name,
                    flip_type=flip_type,
                    buy_label=f"Lv{buy_v['level']} {buy_v['quality']}q",
                    sell_label=f"Lv{sell_v['level']} {sell_v['quality']}q",
                    buy_price=buy_v["price"],
                    sell_price=sell_v["price"],
                    profit=profit,
                    margin_pct=margin,
                    buy_listings=buy_v["listings"],
                    sell_listings=sell_v["listings"],
                ))

        # --- Quality flips: buy 0q, sell 20q at same level ---
        by_level: dict[int, list[dict]] = {}
        for v in variants:
            lv = v["level"]
            if lv not in by_level:
                by_level[lv] = []
            by_level[lv].append(v)

        for lv, lv_variants in by_level.items():
            low_q = [v for v in lv_variants if v["quality"] < 10]
            high_q = [v for v in lv_variants if v["quality"] >= 20]

            if not low_q or not high_q:
                continue

            buy_v = min(low_q, key=lambda v: v["price"])
            sell_v = max(high_q, key=lambda v: v["price"])

            if buy_v["listings"] < min_listings or sell_v["listings"] < min_listings:
                continue

            profit = sell_v["price"] - buy_v["price"]
            margin = (profit / buy_v["price"] * 100) if buy_v["price"] > 0 else 0

            if profit > 1.0:
                results.append(GemFlip(
                    gem_name=gem_name,
                    flip_type="Quality",
                    buy_label=f"Lv{lv} {buy_v['quality']}q",
                    sell_label=f"Lv{lv} {sell_v['quality']}q",
                    buy_price=buy_v["price"],
                    sell_price=sell_v["price"],
                    profit=profit,
                    margin_pct=margin,
                    buy_listings=buy_v["listings"],
                    sell_listings=sell_v["listings"],
                ))

    results.sort(key=lambda x: x.profit, reverse=True)
    return results


def print_gem_table(entries: list[GemFlip], console: Console, limit: int = 20):
    if not entries:
        console.print("[yellow]No profitable Gem flips found at current prices.[/yellow]")
        return

    table = Table(
        title="💠 Gem Arbitrage Scanner (Level & Quality Flips)",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Gem Name")
    table.add_column("Type", width=9)
    table.add_column("Buy", justify="right")
    table.add_column("Sell", justify="right")
    table.add_column("Buy (c)", justify="right")
    table.add_column("Sell (c)", justify="right")
    table.add_column("Profit", justify="right", style="bold green")
    table.add_column("Margin", justify="right")
    table.add_column("Listings", justify="right")

    for rank, e in enumerate(entries[:limit], start=1):
        margin_color = "green" if e.margin_pct > 30 else ("yellow" if e.margin_pct > 0 else "red")

        type_color = {
            "Awakened": "bold magenta",
            "Alt Qual": "bold blue",
            "Level": "white",
            "Quality": "cyan",
        }.get(e.flip_type, "white")

        table.add_row(
            str(rank),
            e.gem_name,
            f"[{type_color}]{e.flip_type}[/{type_color}]",
            e.buy_label,
            e.sell_label,
            f"{e.buy_price:,.1f}",
            f"{e.sell_price:,.1f}",
            f"+{e.profit:,.1f}c",
            f"[{margin_color}]{e.margin_pct:.1f}%[/{margin_color}]",
            f"{e.buy_listings}/{e.sell_listings}",
        )

    console.print(table)
    console.print("[dim]Level flips require XP investment. Quality flips require GCP or Gemcutter's Prisms.[/dim]")
    console.print("[dim]Corrupted gems are excluded. Profit does not include leveling time or GCP cost.[/dim]")
