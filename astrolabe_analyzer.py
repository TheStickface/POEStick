"""
POEStick — Astrolabe & Memory Vault Analyzer.

3.28 Mirage: Astrolabes replace the Sextant system.
Apply an Astrolabe to an Atlas map → create a Shaped Region (cluster of maps).
Clear all maps in the region → unlock a Memory Vault with high-value loot.

10 Astrolabe types (excluding Heist and Kingsmarch):
  Templar (boss encounters) + 9 league mechanics.

4 Memory Vault types, one per Atlas quadrant:
  Arkhon's (Uniques), Zealot's (Currency), Templar (Boss/Keystones), Merchant's (Mixed).
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


@dataclass
class AstrolabeEntry:
    name: str
    price: float          # raw chaos value
    safe_price: float     # trend-adjusted
    listings: int
    astrolabe_type: str   # "Boss" or "League Mechanic"
    mechanic: str         # "Breach", "Expedition", etc.
    vault_name: str       # which Memory Vault it unlocks
    vault_ev: float       # estimated Vault reward (chaos) — heuristic
    clear_cost: float     # estimated map cost to clear the Shaped Region
    net_roi: float        # vault_ev - safe_price - clear_cost
    roi_pct: float


# Memory Vault estimated EVs (community heuristics, week 1 of 3.28).
# Arkhon's (Unique) and Zealot's (Currency) are top-tier.
# Update as league economy matures.
VAULT_EV = {
    "Arkhon's Vault":   120.0,   # Unique items — premium target
    "Zealot's Vault":   100.0,   # Currency — consistent
    "Templar Vault":     80.0,   # Boss drops, Keystones
    "Merchant's Vault":  85.0,   # Scarabs, Maps, mixed loot
}

# Astrolabe type → (type_label, vault_name)
# Vault assignment based on Atlas quadrant associations (community-verified).
ASTROLABE_MAP: dict[str, tuple[str, str, str]] = {
    "Templar Astrolabe":    ("Boss",            "Templar",  "Templar Vault"),
    "Breach Astrolabe":     ("League Mechanic", "Vaal",     "Zealot's Vault"),
    "Expedition Astrolabe": ("League Mechanic", "Karui",    "Arkhon's Vault"),
    "Ritual Astrolabe":     ("League Mechanic", "Maraketh", "Merchant's Vault"),
    "Delirium Astrolabe":   ("League Mechanic", "Vaal",     "Zealot's Vault"),
    "Essence Astrolabe":    ("League Mechanic", "Templar",  "Templar Vault"),
    "Bestiary Astrolabe":   ("League Mechanic", "Karui",    "Arkhon's Vault"),
    "Legion Astrolabe":     ("League Mechanic", "Maraketh", "Merchant's Vault"),
    "Blight Astrolabe":     ("League Mechanic", "Karui",    "Arkhon's Vault"),
    "Abyss Astrolabe":      ("League Mechanic", "Vaal",     "Zealot's Vault"),
}

# Shaped Region = ~8 influenced maps to clear.
# Rough map juice cost per region (conservative — t14+ maps + basic scarabs).
CLEAR_COST_PER_REGION = 15.0


def analyze_astrolabes(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
) -> list[AstrolabeEntry]:
    """
    Fetch Astrolabe prices from poe.ninja and calculate Memory Vault ROI.

    Astrolabes may appear under Currency or Fragment endpoints depending on
    how GGG categorizes them. We check both plus itemoverview.
    """
    found: dict[str, AstrolabeEntry] = {}

    # Check Currency and Fragment endpoints
    for endpoint in ("Currency", "Fragment"):
        url = f"https://poe.ninja/api/data/currencyoverview?league={league}&type={endpoint}"
        data = fetch_json(url, endpoint, console)
        for line in data.get("lines", []):
            name = line.get("currencyTypeName", "")
            if "Astrolabe" not in name or name in found:
                continue
            price = line.get("chaosEquivalent", 0.0)
            if price <= 0:
                continue
            listings = (line.get("receive") or {}).get("listing_count", 0)
            _add_entry(found, name, price, listings, db_conn)

    # Also check itemoverview (Astrolabe may be a standalone item type)
    for item_type in ("Astrolabe", "Currency"):
        url = f"https://poe.ninja/api/data/itemoverview?league={league}&type={item_type}"
        data = fetch_json(url, item_type, console)
        for line in data.get("lines", []):
            name = line.get("name", "")
            if "Astrolabe" not in name or name in found:
                continue
            price = line.get("chaosValue", 0.0)
            if price <= 0:
                continue
            listings = line.get("listingCount", 0)
            _add_entry(found, name, price, listings, db_conn)

    results = sorted(found.values(), key=lambda x: x.roi_pct, reverse=True)
    return results


def _add_entry(
    found: dict[str, AstrolabeEntry],
    name: str,
    price: float,
    listings: int,
    db_conn: sqlite3.Connection,
) -> None:
    safe_price = get_safe_price(db_conn, name, price)
    info = ASTROLABE_MAP.get(name)
    if info:
        astro_type, _quadrant, vault_name = info
    else:
        astro_type = "Unknown"
        vault_name = "Merchant's Vault"  # fallback

    vault_ev = VAULT_EV.get(vault_name, 80.0)
    mechanic = name.replace(" Astrolabe", "")
    net_roi = vault_ev - safe_price - CLEAR_COST_PER_REGION
    total_cost = safe_price + CLEAR_COST_PER_REGION
    roi_pct = (net_roi / total_cost * 100) if total_cost > 0 else 0.0

    found[name] = AstrolabeEntry(
        name=name,
        price=price,
        safe_price=safe_price,
        listings=listings,
        astrolabe_type=astro_type,
        mechanic=mechanic,
        vault_name=vault_name,
        vault_ev=vault_ev,
        clear_cost=CLEAR_COST_PER_REGION,
        net_roi=round(net_roi, 2),
        roi_pct=round(roi_pct, 1),
    )


def print_astrolabe_table(entries: list[AstrolabeEntry], console: Console, limit: int = 15):
    if not entries:
        console.print(
            "[yellow]No Astrolabe data found on poe.ninja yet.[/yellow]\n"
            "[dim]Astrolabes may appear under Currency or Fragment once indexed.[/dim]"
        )
        _print_vault_reference(console)
        return

    table = Table(
        title="🌐 Astrolabe → Memory Vault ROI — 3.28 Mirage",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Astrolabe")
    table.add_column("Type", justify="center")
    table.add_column("Cost (c)", justify="right")
    table.add_column("Vault", style="bold")
    table.add_column("Vault EV (c)", justify="right")
    table.add_column("Clear Cost (c)", justify="right")
    table.add_column("Net ROI", justify="right")
    table.add_column("ROI %", justify="right")

    for rank, entry in enumerate(entries[:limit], start=1):
        roi_color = "green" if entry.roi_pct > 0 else "red"
        vault_colors = {
            "Arkhon's Vault": "magenta",
            "Zealot's Vault": "cyan",
            "Templar Vault":  "yellow",
            "Merchant's Vault": "white",
        }
        vault_style = vault_colors.get(entry.vault_name, "white")

        table.add_row(
            str(rank),
            entry.name,
            f"[dim]{entry.astrolabe_type}[/dim]",
            f"{entry.safe_price:.1f}",
            f"[{vault_style}]{entry.vault_name}[/{vault_style}]",
            f"{entry.vault_ev:.0f}",
            f"{entry.clear_cost:.0f}",
            f"[{roi_color}]{entry.net_roi:+.1f}c[/{roi_color}]",
            f"[{roi_color}]{entry.roi_pct:+.1f}%[/{roi_color}]",
        )

    console.print(table)
    console.print(
        f"[dim]Clear cost = ~{CLEAR_COST_PER_REGION:.0f}c per Shaped Region (~8 maps). "
        "Vault EV = week-1 community heuristic — will shift as market prices settle. "
        "Target Arkhon's (Unique) and Zealot's (Currency) for peak value.[/dim]"
    )


def _print_vault_reference(console: Console):
    """Static reference table of vault types and estimated values."""
    table = Table(
        title="Memory Vault Reference (Heuristic EVs)",
        show_header=True,
        header_style="bold dim",
        border_style="bright_black",
    )
    table.add_column("Vault")
    table.add_column("Reward Focus")
    table.add_column("Est. EV (c)", justify="right")
    table.add_column("Priority", justify="center")

    arkhon_ev = VAULT_EV["Arkhon's Vault"]
    zealot_ev = VAULT_EV["Zealot's Vault"]
    merchant_ev = VAULT_EV["Merchant's Vault"]
    templar_ev = VAULT_EV["Templar Vault"]
    vault_rows = [
        ("Arkhon's Vault",   "Unique Items",          f"~{arkhon_ev:.0f}c",   "S-Tier"),
        ("Zealot's Vault",   "Currency",              f"~{zealot_ev:.0f}c",   "S-Tier"),
        ("Merchant's Vault", "Scarabs, Maps, Mixed",  f"~{merchant_ev:.0f}c", "A-Tier"),
        ("Templar Vault",    "Boss Drops, Keystones", f"~{templar_ev:.0f}c",  "A-Tier"),
    ]
    for vault, focus, ev, priority in vault_rows:
        table.add_row(vault, focus, ev, priority)

    console.print(table)
