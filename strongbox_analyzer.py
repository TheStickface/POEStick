"""
POEStick — Strongbox & Operative Strongbox Analyzer.

3.28 Mirage: The Mirage mechanic can transform regular Strongboxes into
Operative Strongboxes, which drop valuable scarabs directly.
Community reports 8-9 Divines/hour with an optimized Ambush Scarab setup.

How it works:
  - Ambush Scarabs add/upgrade Strongboxes in the map
  - The Mirage mechanic has a chance to convert a Strongbox into an
    Operative Strongbox, which drops premium scarabs instead of standard loot
  - Higher-tier Ambush Scarab variants increase Strongbox count and quality

Tracks:
  - Ambush Scarab variant costs (all tiers)
  - Expected scarab value from Operative Strongbox drops
  - ROI vs standard Strongbox + Ambush setup
  - Mirage conversion multiplier on Operative spawn chance
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import sqlite3
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from api import fetch_json
from pricing import get_safe_price


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class AmbushVariant:
    name: str
    cost: float
    tier: str   # "Basic", "Advanced", "Premium"


@dataclass
class StrongboxROIResult:
    # Best Ambush Scarab for the Operative setup
    best_ambush: str
    ambush_cost: float
    # Expected Operative Strongbox spawns per map (heuristic)
    operative_spawns: float
    # Expected scarab drop value per Operative box
    scarab_value_per_box: float
    # Total expected value per map
    total_map_value: float
    # Net ROI after scarab cost
    net_roi: float
    roi_pct: float
    mirage_multiplier: float
    # All Ambush variants ranked by cost
    all_variants: list[AmbushVariant]
    # Top scarabs by price (what Operative boxes tend to drop)
    top_scarabs: list[tuple[str, float]]


# ── Constants ────────────────────────────────────────────────────────────────

AMBUSH_SCARABS = [
    "Ambush Scarab",
    "Ambush Scarab of Hidden Compartments",
    "Ambush Scarab of Discernment",
    "Ambush Scarab of Containment",
]

AMBUSH_TIERS = {
    "Ambush Scarab": "Basic",
    "Ambush Scarab of Hidden Compartments": "Advanced",
    "Ambush Scarab of Discernment": "Advanced",
    "Ambush Scarab of Containment": "Premium",
}

# Community heuristic: Operative Strongbox spawns per map.
# Mirage has ~30-40% chance to convert a Strongbox into Operative.
# With a full Ambush Scarab setup (~4 boxes per map), expect ~1.2-1.5 Operative per map.
BASE_OPERATIVE_SPAWNS = 1.2  # without Mirage multiplier boost
MIRAGE_OPERATIVE_BONUS = 0.4  # additional spawns from Mirage conversion chance

# Heuristic: average scarab drop value from one Operative Strongbox.
# Community reports scarab drops worth 30-80c per Operative box.
# Using conservative 45c as base estimate.
SCARAB_VALUE_PER_OPERATIVE_BOX = 45.0

# Number of top scarabs to show in the reference table
TOP_SCARABS_DISPLAY = 8


# ── Analysis ─────────────────────────────────────────────────────────────────

def analyze_strongbox(
    league: str,
    db_conn: sqlite3.Connection,
    mirage_multiplier: float = 1.5,
    console: Optional[Console] = None,
) -> Optional[StrongboxROIResult]:
    """
    Fetch Ambush Scarab prices, estimate Operative Strongbox ROI,
    and surface top scarab prices for reference.
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab"
    data = fetch_json(url, "Scarab", console)
    lines = data.get("lines", [])

    scarab_prices: dict[str, float] = {}
    for line in lines:
        name  = line.get("name")
        price = line.get("chaosValue", 0.0)
        if name and price > 0:
            scarab_prices[name] = get_safe_price(db_conn, name, price)

    # Ambush Scarab variants
    all_variants: list[AmbushVariant] = []
    for name in AMBUSH_SCARABS:
        cost = scarab_prices.get(name, 0.0)
        if cost > 0:
            all_variants.append(AmbushVariant(
                name=name,
                cost=round(cost, 2),
                tier=AMBUSH_TIERS.get(name, "Basic"),
            ))
    all_variants.sort(key=lambda x: x.cost)

    if not all_variants:
        return None

    best = all_variants[0]

    # Mirage boosts Operative spawn rate
    operative_spawns = BASE_OPERATIVE_SPAWNS + (MIRAGE_OPERATIVE_BONUS * (mirage_multiplier - 1.0))

    # Total map value
    total_map_value = operative_spawns * SCARAB_VALUE_PER_OPERATIVE_BOX
    net_roi  = total_map_value - best.cost
    roi_pct  = (net_roi / best.cost * 100) if best.cost > 0 else 0.0

    # Top scarabs by price (what Operative boxes tend to drop)
    top_scarabs = sorted(
        [(name, price) for name, price in scarab_prices.items() if price >= 10.0],
        key=lambda x: x[1],
        reverse=True,
    )[:TOP_SCARABS_DISPLAY]

    return StrongboxROIResult(
        best_ambush=best.name,
        ambush_cost=best.cost,
        operative_spawns=round(operative_spawns, 2),
        scarab_value_per_box=SCARAB_VALUE_PER_OPERATIVE_BOX,
        total_map_value=round(total_map_value, 2),
        net_roi=round(net_roi, 2),
        roi_pct=round(roi_pct, 1),
        mirage_multiplier=mirage_multiplier,
        all_variants=all_variants,
        top_scarabs=top_scarabs,
    )


# ── Display ──────────────────────────────────────────────────────────────────

def print_strongbox_table(result: Optional[StrongboxROIResult], console: Console):
    if result is None:
        console.print(
            "[yellow]No Ambush Scarab data found on poe.ninja.[/yellow]\n"
            "[dim]Check back as scarab prices populate later in the league.[/dim]"
        )
        return

    roi_color = "green" if result.roi_pct > 0 else "red"

    # ROI summary panel
    t = Text()
    t.append("  Best Ambush Scarab:         ", style="dim")
    t.append(f"{result.best_ambush}", style="bold white")
    t.append(f"  @ {result.ambush_cost:.1f}c\n", style="yellow")
    t.append("  Operative spawns/map:       ", style="dim")
    t.append(f"~{result.operative_spawns:.1f}", style="white")
    t.append(f"  [dim](base {BASE_OPERATIVE_SPAWNS:.1f} + Mirage ×{result.mirage_multiplier:.1f} bonus)[/dim]\n")
    t.append("  Scarab value/Operative box: ", style="dim")
    t.append(f"~{result.scarab_value_per_box:.0f}c  ", style="white")
    t.append("[dim](community heuristic, conservative)[/dim]\n")
    t.append("  Total Map Value:            ", style="dim")
    t.append(f"{result.total_map_value:.1f}c\n", style="bold white")
    t.append("  Net ROI:                    ", style="dim")
    t.append(
        f"{result.net_roi:+.1f}c  ({result.roi_pct:+.1f}%)",
        style=f"bold {roi_color}",
    )
    console.print(Panel(
        t,
        title="📦 Strongbox → Operative Strongbox ROI  (Mirage conversion)",
        border_style="yellow",
    ))

    # Ambush Scarab variant table
    var_table = Table(
        title="Ambush Scarab Variants",
        show_header=True,
        header_style="bold yellow",
        border_style="bright_black",
        expand=True,
    )
    var_table.add_column("Scarab")
    var_table.add_column("Tier",     justify="center")
    var_table.add_column("Cost (c)", justify="right")
    var_table.add_column("Notes")

    tier_colors = {"Basic": "dim", "Advanced": "yellow", "Premium": "bold magenta"}
    for v in result.all_variants:
        is_best = v.name == result.best_ambush
        tier_style = tier_colors.get(v.tier, "white")
        var_table.add_row(
            f"[bold white]{v.name}[/bold white]" if is_best else v.name,
            f"[{tier_style}]{v.tier}[/{tier_style}]",
            f"{v.cost:.1f}",
            "[green]✓ Cheapest combo[/green]" if is_best else "",
        )
    console.print(var_table)

    # Top scarab reference prices
    if result.top_scarabs:
        sca_table = Table(
            title=f"Top {TOP_SCARABS_DISPLAY} Scarabs by Price  (Operative box drop pool reference)",
            show_header=True,
            header_style="bold dim",
            border_style="bright_black",
            expand=True,
        )
        sca_table.add_column("#",         style="dim", width=3, justify="right")
        sca_table.add_column("Scarab")
        sca_table.add_column("Price (c)", justify="right", style="bold green")

        for rank, (name, price) in enumerate(result.top_scarabs, start=1):
            sca_table.add_row(str(rank), name, f"{price:.1f}")
        console.print(sca_table)

    console.print(
        "[dim]Mirage converts Strongboxes → Operative Strongboxes (scarab drops). "
        f"Operative spawn rate: base {BASE_OPERATIVE_SPAWNS:.1f}/map + Mirage bonus. "
        "Community reports 8-9 Divines/hour with optimized setup. "
        "Scarab value/box is a conservative week-1 heuristic.[/dim]"
    )
