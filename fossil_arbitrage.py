"""
POEStick — Fossil Arbitrage Analyzer.

3.28 Mirage: Fossils now drop exclusively from Delve.
Tracks fossil prices, ranks by value, and calculates Delve ROI
based on Sulphite Scarab cost vs expected fossil yield value.
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
from pricing import get_safe_price, get_4h_trend


@dataclass
class FossilEntry:
    name: str
    price: float          # raw poe.ninja chaos value
    safe_price: float     # trend-adjusted conservative price
    listings: int
    trend: float          # 4h price change %
    tier: str             # "Premium", "Valuable", "Common"


@dataclass
class DelveROIResult:
    sulphite_scarab_name: str
    sulphite_scarab_cost: float
    expected_fossils: float       # avg fossils per Delve run (heuristic)
    expected_fossil_value: float  # expected chaos from avg fossil drop
    net_roi: float                # expected_fossil_value - scarab_cost
    roi_pct: float


# Tier classification by safe price
FOSSIL_TIERS = [
    ("Premium",  50.0),
    ("Valuable", 10.0),
    ("Common",    0.0),
]

# Fossils to highlight — known crafting staples with sustained demand
PRIORITY_FOSSILS = {
    "Hollow Fossil", "Sanctified Fossil", "Pristine Fossil",
    "Corroded Fossil", "Jagged Fossil", "Bound Fossil",
    "Gilded Fossil", "Faceted Fossil", "Perfect Fossil",
    "Lucent Fossil", "Metallic Fossil", "Dense Fossil",
    "Aberrant Fossil", "Serrated Fossil", "Frigid Fossil",
}

# Sulphite Scarabs used to efficiently run Delve
SULPHITE_SCARABS = [
    "Sulphite Scarab",
    "Sulphite Scarab of Sustained Delving",
    "Sulphite Scarab of Greed",
    "Sulphite Scarab of Revelation",
]

# Conservative heuristic: avg fossil drops per map at depth 250-350.
# Based on community data (fractured walls + off-path nodes).
EXPECTED_FOSSILS_PER_RUN = 2.5


def _classify_tier(price: float) -> str:
    for tier_name, threshold in FOSSIL_TIERS:
        if price >= threshold:
            return tier_name
    return "Common"


def analyze_fossils(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
) -> tuple[list[FossilEntry], Optional[DelveROIResult]]:
    """
    Fetch all fossil prices from poe.ninja, rank them, and calculate Delve ROI.
    Returns (fossil_list sorted by safe_price desc, delve_roi or None).
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Fossil"
    data = fetch_json(url, "Fossil", console)
    lines = data.get("lines", [])

    fossils: list[FossilEntry] = []
    for line in lines:
        name = line.get("name")
        price = line.get("chaosValue", 0.0)
        listings = line.get("listingCount", 0)
        if not name or price <= 0 or listings < 2:
            continue

        safe_price = get_safe_price(db_conn, name, price)
        trend = get_4h_trend(db_conn, name, price) or 0.0
        tier = _classify_tier(safe_price)

        fossils.append(FossilEntry(
            name=name,
            price=price,
            safe_price=safe_price,
            listings=listings,
            trend=trend,
            tier=tier,
        ))

    fossils.sort(key=lambda x: x.safe_price, reverse=True)

    # Fetch Sulphite Scarab prices for the ROI panel
    scarab_url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab"
    scarab_data = fetch_json(scarab_url, "Scarab", console)
    scarab_prices = {l.get("name"): l.get("chaosValue", 0.0) for l in scarab_data.get("lines", [])}

    best_scarab: Optional[str] = None
    best_scarab_cost = float("inf")
    for s in SULPHITE_SCARABS:
        cost = scarab_prices.get(s, 0.0)
        if 0 < cost < best_scarab_cost:
            best_scarab_cost = cost
            best_scarab = s

    delve_roi: Optional[DelveROIResult] = None
    if best_scarab and fossils:
        # Weighted average fossil value (by listing count = proxy for drop frequency)
        total_listings = sum(f.listings for f in fossils)
        if total_listings > 0:
            weighted_avg = sum(f.safe_price * f.listings for f in fossils) / total_listings
        else:
            weighted_avg = sum(f.safe_price for f in fossils) / len(fossils)

        expected_value = weighted_avg * EXPECTED_FOSSILS_PER_RUN
        net_roi = expected_value - best_scarab_cost
        roi_pct = (net_roi / best_scarab_cost * 100) if best_scarab_cost > 0 else 0.0

        delve_roi = DelveROIResult(
            sulphite_scarab_name=best_scarab,
            sulphite_scarab_cost=round(best_scarab_cost, 2),
            expected_fossils=EXPECTED_FOSSILS_PER_RUN,
            expected_fossil_value=round(expected_value, 2),
            net_roi=round(net_roi, 2),
            roi_pct=round(roi_pct, 1),
        )

    return fossils, delve_roi


def print_fossil_table(
    fossils: list[FossilEntry],
    delve_roi: Optional[DelveROIResult],
    console: Console,
    limit: int = 20,
):
    if not fossils:
        console.print("[yellow]No Fossil data found on poe.ninja.[/yellow]")
        console.print("[dim]Check that the league name is correct or try again later.[/dim]")
        return

    # ROI summary panel
    if delve_roi:
        roi_color = "green" if delve_roi.net_roi > 0 else "red"
        roi_text = Text()
        roi_text.append("  Cheapest Sulphite Scarab:  ", style="dim")
        roi_text.append(f"{delve_roi.sulphite_scarab_name}", style="bold white")
        roi_text.append(f" @ {delve_roi.sulphite_scarab_cost:.1f}c\n", style="yellow")
        roi_text.append(f"  Avg fossil drop × {delve_roi.expected_fossils:.1f}:  ", style="dim")
        roi_text.append(f"{delve_roi.expected_fossil_value:.1f}c expected\n", style="white")
        roi_text.append("  Net Delve ROI:             ", style="dim")
        roi_text.append(
            f"{delve_roi.net_roi:+.1f}c  ({delve_roi.roi_pct:+.1f}%)",
            style=f"bold {roi_color}",
        )
        console.print(Panel(roi_text, title="⛏️ Delve ROI Estimate", border_style="yellow"))

    tier_colors = {"Premium": "bold magenta", "Valuable": "bold yellow", "Common": "dim"}

    table = Table(
        title="⛏️ Fossil Price Index — 3.28 Mirage (Delve-Exclusive Supply)",
        show_header=True,
        header_style="bold yellow",
        border_style="bright_black",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Fossil")
    table.add_column("Tier", justify="center")
    table.add_column("Price (c)", justify="right", style="bold green")
    table.add_column("Safe (c)", justify="right")
    table.add_column("4h Trend", justify="right")
    table.add_column("Listings", justify="right")

    for rank, fossil in enumerate(fossils[:limit], start=1):
        trend_str = f"{fossil.trend:+.1f}%" if fossil.trend != 0 else "—"
        trend_color = "green" if fossil.trend > 2 else ("red" if fossil.trend < -2 else "dim")
        tier_style = tier_colors.get(fossil.tier, "dim")
        name_style = "bold white" if fossil.name in PRIORITY_FOSSILS else "white"

        table.add_row(
            str(rank),
            f"[{name_style}]{fossil.name}[/{name_style}]",
            f"[{tier_style}]{fossil.tier}[/{tier_style}]",
            f"{fossil.price:,.1f}",
            f"{fossil.safe_price:,.1f}",
            f"[{trend_color}]{trend_str}[/{trend_color}]",
            str(fossil.listings),
        )

    console.print(table)
    console.print(
        "[dim]3.28 Mirage: Fossils are Delve-exclusive. "
        "Safe = trend-conservative price. "
        "Highlighted = high-demand crafting staples. "
        "ROI heuristic: ~2.5 fossils per Delve run at depth 250-350.[/dim]"
    )
