"""
POEStick — Breach Fortress Analyzer.

3.28 Mirage: Marshall Scarab converts Abyss encounters into Fortresses.
             Hive Scarab guarantees Breach spawns.
Combined, they guarantee an Ailith encounter (Breach Fortress),
which yields significantly more loot than a standard Breach map.

Community reports: ~2-3 Divines per optimized Breach Fortress map.
This module tracks scarab costs and estimates ROI vs standard Breach.
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
class BreachFortressResult:
    # Cheapest viable combo
    marshall_scarab: str
    marshall_cost: float
    hive_scarab: str
    hive_cost: float
    combo_cost: float
    # Standard Breach baseline
    standard_breach_scarab: str
    standard_breach_cost: float
    # ROI vs estimated fortress value
    fortress_ev: float
    net_roi: float
    roi_pct: float
    # Premium over standard Breach setup
    combo_premium: float
    combo_premium_pct: float
    # All variants found (for user selection)
    marshall_variants: list[tuple[str, float]]
    hive_variants: list[tuple[str, float]]
    breach_variants: list[tuple[str, float]]


# Known scarab families for this combo
MARSHALL_SCARABS = [
    "Marshall Scarab",
    "Marshall Scarab of Fortification",
    "Marshall Scarab of the Bulwark",
    "Marshall Scarab of Abundance",
]

HIVE_SCARABS = [
    "Hive Scarab",
    "Hive Scarab of Haemorrhage",
    "Hive Scarab of Proliferation",
    "Hive Scarab of Bloodlines",
]

BREACH_SCARABS = [
    "Breach Scarab",
    "Breach Scarab of Snaring",
    "Breach Scarab of Haemorrhage",
    "Breach Scarab of Lordship",
]

# Conservative EV heuristic (community week-1 reports: 2-3 Divine/map).
# Using 1.8 Divine at 200c/Divine = 360c as conservative lower bound.
FORTRESS_EV_CHAOS = 360.0

# Standard Breach map EV without the Marshall/Hive combo.
STANDARD_BREACH_EV_CHAOS = 120.0


def analyze_breach_fortress(
    league: str,
    db_conn: sqlite3.Connection,
    console: Optional[Console] = None,
) -> Optional[BreachFortressResult]:
    """
    Fetch Marshall + Hive Scarab prices, find cheapest combo, estimate Fortress ROI.
    Returns None if neither scarab family is indexed on poe.ninja yet.
    """
    url = f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab"
    data = fetch_json(url, "Scarab", console)
    raw_prices = {l.get("name"): l.get("chaosValue", 0.0) for l in data.get("lines", []) if l.get("name")}

    def _variants(names: list[str]) -> list[tuple[str, float]]:
        out = []
        for name in names:
            cost = raw_prices.get(name, 0.0)
            if cost > 0:
                out.append((name, round(get_safe_price(db_conn, name, cost), 2)))
        return sorted(out, key=lambda x: x[1])

    marshall_variants = _variants(MARSHALL_SCARABS)
    hive_variants = _variants(HIVE_SCARABS)
    breach_variants = _variants(BREACH_SCARABS)

    if not marshall_variants and not hive_variants:
        return None

    # Cheapest viable option per family (fallback to 0 if not found yet)
    best_marshall = marshall_variants[0] if marshall_variants else ("(not indexed)", 0.0)
    best_hive = hive_variants[0] if hive_variants else ("(not indexed)", 0.0)
    best_breach = breach_variants[0] if breach_variants else ("(not indexed)", 0.0)

    combo_cost = best_marshall[1] + best_hive[1]
    net_roi = FORTRESS_EV_CHAOS - combo_cost
    roi_pct = (net_roi / combo_cost * 100) if combo_cost > 0 else 0.0

    # How much more does the Fortress combo cost vs just running Breach?
    combo_premium = combo_cost - best_breach[1]
    combo_premium_pct = (combo_premium / best_breach[1] * 100) if best_breach[1] > 0 else 0.0

    return BreachFortressResult(
        marshall_scarab=best_marshall[0],
        marshall_cost=best_marshall[1],
        hive_scarab=best_hive[0],
        hive_cost=best_hive[1],
        combo_cost=round(combo_cost, 2),
        standard_breach_scarab=best_breach[0],
        standard_breach_cost=best_breach[1],
        fortress_ev=FORTRESS_EV_CHAOS,
        net_roi=round(net_roi, 2),
        roi_pct=round(roi_pct, 1),
        combo_premium=round(combo_premium, 2),
        combo_premium_pct=round(combo_premium_pct, 1),
        marshall_variants=marshall_variants,
        hive_variants=hive_variants,
        breach_variants=breach_variants,
    )


def print_breach_fortress_table(result: Optional[BreachFortressResult], console: Console):
    if result is None:
        console.print(
            "[yellow]No Marshall or Hive Scarab data found on poe.ninja yet.[/yellow]\n"
            "[dim]These scarabs may not yet be indexed. Check back as the league progresses.[/dim]"
        )
        _print_combo_howto(console)
        return

    roi_color = "green" if result.roi_pct > 0 else "red"
    premium_color = "yellow" if result.combo_premium_pct < 100 else "red"

    summary = Text()
    summary.append("  Marshall Scarab:      ", style="dim")
    summary.append(f"{result.marshall_scarab}", style="bold white")
    summary.append(f"  @ {result.marshall_cost:.1f}c\n", style="yellow")
    summary.append("  Hive Scarab:          ", style="dim")
    summary.append(f"{result.hive_scarab}", style="bold white")
    summary.append(f"  @ {result.hive_cost:.1f}c\n", style="yellow")
    summary.append("  ─────────────────────────────────────────\n", style="dim")
    summary.append("  Combo Cost:           ", style="dim")
    summary.append(f"{result.combo_cost:.1f}c", style="bold red")
    summary.append("   vs Standard Breach: ", style="dim")
    summary.append(f"{result.standard_breach_cost:.1f}c\n", style="white")
    summary.append("  Combo Premium:        ", style="dim")
    summary.append(f"+{result.combo_premium:.1f}c  ({result.combo_premium_pct:+.1f}%)\n", style=f"bold {premium_color}")
    summary.append("  Fortress EV (est.):   ", style="dim")
    summary.append(f"{result.fortress_ev:.0f}c  ", style="white")
    summary.append("[dim](community heuristic, ~1.8 Divine conservative)[/dim]\n")
    summary.append("  Net ROI:              ", style="dim")
    summary.append(f"{result.net_roi:+.1f}c  ({result.roi_pct:+.1f}%)", style=f"bold {roi_color}")

    console.print(Panel(summary, title="🏰 Breach Fortress Combo Analysis", border_style="purple"))

    # All variant pricing
    table = Table(
        title="Scarab Variant Pricing",
        show_header=True,
        header_style="bold dim",
        border_style="bright_black",
        expand=True,
    )
    table.add_column("Scarab")
    table.add_column("Role", justify="center")
    table.add_column("Cost (c)", justify="right")
    table.add_column("Notes")

    for name, cost in result.marshall_variants:
        is_best = name == result.marshall_scarab
        table.add_row(
            f"[bold white]{name}[/bold white]" if is_best else name,
            "[bold blue]Marshall[/bold blue]",
            f"{cost:.1f}",
            "[green]✓ Cheapest[/green]" if is_best else "",
        )
    for name, cost in result.hive_variants:
        is_best = name == result.hive_scarab
        table.add_row(
            f"[bold white]{name}[/bold white]" if is_best else name,
            "[bold purple]Hive[/bold purple]",
            f"{cost:.1f}",
            "[green]✓ Cheapest[/green]" if is_best else "",
        )
    for name, cost in result.breach_variants:
        is_best = name == result.standard_breach_scarab
        table.add_row(
            f"[bold white]{name}[/bold white]" if is_best else name,
            "[dim]Breach (baseline)[/dim]",
            f"{cost:.1f}",
            "[dim]Standard — no Fortress[/dim]" if is_best else "",
        )

    console.print(table)
    console.print(
        "[dim]Marshall converts Abyss encounters → Fortresses. "
        "Hive guarantees Breach spawns → Ailith. "
        "Combined: Breach Fortress = guaranteed Ailith. "
        "Fortress EV is conservative community estimate (week 1).[/dim]"
    )


def _print_combo_howto(console: Console):
    text = Text()
    text.append("\nHow Breach Fortress works:\n", style="bold")
    text.append("  1. Equip Marshall Scarab → converts Abyss encounters into Fortresses\n")
    text.append("  2. Equip Hive Scarab     → guarantees Breach spawns in your map\n")
    text.append("  3. Together they guarantee an Ailith (Breach Fortress) encounter\n")
    text.append("  4. Fortress drops significantly more loot than a standard Breach\n")
    text.append("     Community reports: 2-3 Divines per optimized Fortress map\n", style="bold green")
    console.print(Panel(text, border_style="dim"))
