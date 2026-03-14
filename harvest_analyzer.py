"""
POEStick — Harvest Analyzer.

3.28 Mirage: Harvest is S-tier. The Mirage mechanic doubles your Harvest
encounter per map — same scarab investment, effectively double lifeforce.
The Cornucopia strategy (Harvest Scarab of Cornucopia) is the premier setup.

Tracks:
- Vivid / Wild / Primal Crystallised Lifeforce prices + 4h trends
- New Catalyst prices (prefix/suffix modifier Catalyst is highest value early league)
- Cornucopia Harvest Scarab cost vs expected lifeforce yield
- Mirage encounter multiplier applied to per-map value estimates
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


# ── Data models ─────────────────────────────────────────────────────────────

@dataclass
class LifeforceEntry:
    name: str
    lf_type: str          # "Vivid", "Wild", "Primal"
    price: float
    safe_price: float
    listings: int
    trend: float


@dataclass
class CatalystEntry:
    name: str
    price: float
    safe_price: float
    listings: int
    trend: float


@dataclass
class HarvestROIResult:
    scarab_name: str
    scarab_cost: float
    base_encounter_value: float       # expected chaos value per Harvest encounter (no Mirage)
    mirage_encounter_value: float     # × mirage_multiplier
    net_roi: float                    # mirage_encounter_value - scarab_cost
    roi_pct: float
    mirage_multiplier: float


# ── Constants ────────────────────────────────────────────────────────────────

LIFEFORCE_NAMES = [
    "Vivid Crystallised Lifeforce",
    "Wild Crystallised Lifeforce",
    "Primal Crystallised Lifeforce",
]

HARVEST_SCARABS = [
    "Harvest Scarab of Cornucopia",   # S-tier — targets Cornucopia encounters
    "Harvest Scarab of Doubling",
    "Harvest Scarab of the Grove",
    "Harvest Scarab",
]

# Community-estimated average lifeforce units per Cornucopia Harvest encounter.
# Cornucopia encounters yield significantly more than standard Harvest.
# Breakdown approximate based on week-1 community data.
CORNUCOPIA_YIELD: dict[str, float] = {
    "Vivid Crystallised Lifeforce": 350.0,
    "Wild Crystallised Lifeforce":  220.0,
    "Primal Crystallised Lifeforce": 130.0,
}

LF_TYPE_MAP = {
    "Vivid Crystallised Lifeforce":   "Vivid",
    "Wild Crystallised Lifeforce":    "Wild",
    "Primal Crystallised Lifeforce":  "Primal",
}


# ── Analysis ─────────────────────────────────────────────────────────────────

def analyze_harvest(
    league: str,
    db_conn: sqlite3.Connection,
    mirage_multiplier: float = 1.5,
    console: Optional[Console] = None,
) -> tuple[list[LifeforceEntry], list[CatalystEntry], Optional[HarvestROIResult]]:
    """
    Fetch lifeforce and catalyst prices, calculate Cornucopia Harvest ROI
    with and without the Mirage encounter multiplier.

    Returns (lifeforce_list, catalyst_list, roi_result).
    """
    # ── Lifeforce prices (Currency endpoint) ──────────────────────────────
    curr_url = f"https://poe.ninja/api/data/currencyoverview?league={league}&type=Currency"
    curr_data = fetch_json(curr_url, "Currency", console)
    curr_lines = curr_data.get("lines", [])

    lifeforce_entries: list[LifeforceEntry] = []
    lifeforce_prices: dict[str, float] = {}

    for line in curr_lines:
        name = line.get("currencyTypeName", "")
        if name not in LIFEFORCE_NAMES:
            continue
        price = line.get("chaosEquivalent", 0.0)
        if price <= 0:
            continue
        listings = (line.get("receive") or {}).get("listing_count", 0)
        safe  = get_safe_price(db_conn, name, price)
        trend = get_4h_trend(db_conn, name, price) or 0.0
        lifeforce_prices[name] = safe
        lifeforce_entries.append(LifeforceEntry(
            name=name,
            lf_type=LF_TYPE_MAP.get(name, "Unknown"),
            price=price,
            safe_price=safe,
            listings=listings,
            trend=trend,
        ))

    lifeforce_entries.sort(key=lambda x: x.safe_price, reverse=True)

    # ── Catalyst prices (Currency + BaseType endpoints) ────────────────────
    catalyst_entries: list[CatalystEntry] = []

    for line in curr_lines:
        name = line.get("currencyTypeName", "")
        if "Catalyst" not in name:
            continue
        price = line.get("chaosEquivalent", 0.0)
        if price <= 0:
            continue
        listings = (line.get("receive") or {}).get("listing_count", 0)
        safe  = get_safe_price(db_conn, name, price)
        trend = get_4h_trend(db_conn, name, price) or 0.0
        catalyst_entries.append(CatalystEntry(
            name=name, price=price, safe_price=safe,
            listings=listings, trend=trend,
        ))

    # Also check itemoverview for catalysts (they sometimes appear there)
    for item_type in ("Currency", "BaseType"):
        item_url = f"https://poe.ninja/api/data/itemoverview?league={league}&type={item_type}"
        item_data = fetch_json(item_url, item_type, console)
        for line in item_data.get("lines", []):
            name = line.get("name", "")
            if "Catalyst" not in name:
                continue
            if any(c.name == name for c in catalyst_entries):
                continue
            price = line.get("chaosValue", 0.0)
            if price <= 0:
                continue
            listings = line.get("listingCount", 0)
            safe  = get_safe_price(db_conn, name, price)
            trend = get_4h_trend(db_conn, name, price) or 0.0
            catalyst_entries.append(CatalystEntry(
                name=name, price=price, safe_price=safe,
                listings=listings, trend=trend,
            ))

    catalyst_entries.sort(key=lambda x: x.safe_price, reverse=True)

    # ── Harvest Scarab prices ──────────────────────────────────────────────
    scarab_url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab"
    scarab_data = fetch_json(scarab_url, "Scarab", console)
    scarab_prices = {
        l.get("name"): l.get("chaosValue", 0.0)
        for l in scarab_data.get("lines", [])
        if l.get("name")
    }

    best_scarab: Optional[str] = None
    best_scarab_cost = float("inf")
    for s in HARVEST_SCARABS:
        cost = scarab_prices.get(s, 0.0)
        if 0 < cost < best_scarab_cost:
            best_scarab_cost = cost
            best_scarab = s

    # ── ROI calculation ────────────────────────────────────────────────────
    roi: Optional[HarvestROIResult] = None
    if best_scarab and lifeforce_prices:
        base_value = sum(
            CORNUCOPIA_YIELD.get(name, 0.0) * lifeforce_prices.get(name, 0.0)
            for name in LIFEFORCE_NAMES
        )
        # poe.ninja prices are per unit; convert yield units → chaos value
        # (prices are per 1 lifeforce unit)
        mirage_value = base_value * mirage_multiplier
        net_roi = mirage_value - best_scarab_cost
        roi_pct = (net_roi / best_scarab_cost * 100) if best_scarab_cost > 0 else 0.0

        roi = HarvestROIResult(
            scarab_name=best_scarab,
            scarab_cost=round(best_scarab_cost, 2),
            base_encounter_value=round(base_value, 2),
            mirage_encounter_value=round(mirage_value, 2),
            net_roi=round(net_roi, 2),
            roi_pct=round(roi_pct, 1),
            mirage_multiplier=mirage_multiplier,
        )

    return lifeforce_entries, catalyst_entries, roi


# ── Display ──────────────────────────────────────────────────────────────────

def print_harvest_table(
    lifeforce: list[LifeforceEntry],
    catalysts: list[CatalystEntry],
    roi: Optional[HarvestROIResult],
    console: Console,
    limit: int = 20,
):
    # ── ROI panel ─────────────────────────────────────────────────────────
    if roi:
        roi_color = "green" if roi.net_roi > 0 else "red"
        t = Text()
        t.append("  Best Harvest Scarab:     ", style="dim")
        t.append(f"{roi.scarab_name}", style="bold white")
        t.append(f"  @ {roi.scarab_cost:.1f}c\n", style="yellow")
        t.append("  Base Encounter Value:    ", style="dim")
        t.append(f"{roi.base_encounter_value:.1f}c\n", style="white")
        t.append(f"  × Mirage ×{roi.mirage_multiplier:.1f} Value:   ", style="dim")
        t.append(f"{roi.mirage_encounter_value:.1f}c\n", style="bold white")
        t.append("  Net ROI (with Mirage):   ", style="dim")
        t.append(
            f"{roi.net_roi:+.1f}c  ({roi.roi_pct:+.1f}%)",
            style=f"bold {roi_color}",
        )
        console.print(Panel(
            t,
            title="🌿 Cornucopia Harvest ROI  (Mirage doubles encounter)",
            border_style="green",
        ))
    else:
        console.print("[yellow]No Harvest Scarab pricing found yet.[/yellow]")

    # ── Lifeforce table ────────────────────────────────────────────────────
    if lifeforce:
        lf_table = Table(
            title="🌿 Crystallised Lifeforce Prices — 3.28 Mirage",
            show_header=True,
            header_style="bold green",
            border_style="bright_black",
            expand=True,
        )
        lf_table.add_column("Lifeforce")
        lf_table.add_column("Type",      justify="center", width=7)
        lf_table.add_column("Price (c)", justify="right")
        lf_table.add_column("Safe (c)",  justify="right")
        lf_table.add_column("4h Trend",  justify="right")
        lf_table.add_column("Yield/enc", justify="right")
        lf_table.add_column("Value/enc", justify="right", style="bold green")

        lf_colors = {"Vivid": "magenta", "Wild": "cyan", "Primal": "red"}
        for lf in lifeforce[:3]:
            trend_str   = f"{lf.trend:+.1f}%" if lf.trend else "—"
            trend_color = "green" if lf.trend > 2 else ("red" if lf.trend < -2 else "dim")
            yield_qty   = CORNUCOPIA_YIELD.get(lf.name, 0.0)
            enc_value   = yield_qty * lf.safe_price
            lf_table.add_row(
                lf.name,
                f"[{lf_colors.get(lf.lf_type, 'white')}]{lf.lf_type}[/{lf_colors.get(lf.lf_type, 'white')}]",
                f"{lf.price:.4f}",
                f"{lf.safe_price:.4f}",
                f"[{trend_color}]{trend_str}[/{trend_color}]",
                f"~{yield_qty:.0f}",
                f"{enc_value:.1f}c",
            )
        console.print(lf_table)

    # ── Catalyst table ─────────────────────────────────────────────────────
    if catalysts:
        cat_table = Table(
            title="⚗️ Catalyst Prices — 3.28 Mirage  (new prefix/suffix Catalyst = highest value)",
            show_header=True,
            header_style="bold magenta",
            border_style="bright_black",
            expand=True,
        )
        cat_table.add_column("#",         style="dim", width=3, justify="right")
        cat_table.add_column("Catalyst")
        cat_table.add_column("Price (c)", justify="right", style="bold green")
        cat_table.add_column("Safe (c)",  justify="right")
        cat_table.add_column("4h Trend",  justify="right")
        cat_table.add_column("Listings",  justify="right")

        for rank, cat in enumerate(catalysts[:limit], start=1):
            trend_str   = f"{cat.trend:+.1f}%" if cat.trend else "—"
            trend_color = "green" if cat.trend > 2 else ("red" if cat.trend < -2 else "dim")
            cat_table.add_row(
                str(rank),
                cat.name,
                f"{cat.price:.1f}",
                f"{cat.safe_price:.1f}",
                f"[{trend_color}]{trend_str}[/{trend_color}]",
                str(cat.listings),
            )
        console.print(cat_table)
    else:
        console.print("[dim]No Catalyst data found yet — may appear as the league matures.[/dim]")

    console.print(
        "[dim]Lifeforce yield estimates = Cornucopia encounter community average (week 1). "
        "Mirage doubles the encounter, effectively doubling lifeforce per map. "
        "Prefix/suffix modifier Catalyst is the highest-value early-league Catalyst.[/dim]"
    )
