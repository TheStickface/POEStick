"""
POEStick — Rich TUI display and export functions.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import io
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

from analysis import Opportunity, MultiHopRoute
from supply_shock import ShockEntry, build_shock_live_panel


def _trend_arrow(trend: float) -> str:
    """Convert a trend % to a colored arrow string."""
    if trend > 5:
        return "[green]▲▲[/green]"
    elif trend > 0:
        return "[green]▲[/green]"
    elif trend < -5:
        return "[red]▼▼[/red]"
    elif trend < 0:
        return "[red]▼[/red]"
    return "[dim]━[/dim]"


def _delta_str(delta: Optional[float], is_new: bool) -> str:
    """Format the margin delta for display."""
    if is_new:
        return "[bold cyan]NEW[/bold cyan]"
    if delta is None:
        return "[dim]—[/dim]"
    if delta > 0:
        return f"[green]+{delta:.1f}%[/green]"
    elif delta < 0:
        return f"[red]{delta:.1f}%[/red]"
    return "[dim]0.0%[/dim]"


def _confidence_bar(confidence: float) -> str:
    """Render confidence as a colored label."""
    if confidence >= 0.8:
        return f"[bold green]{confidence:.0%}[/bold green]"
    elif confidence >= 0.5:
        return f"[yellow]{confidence:.0%}[/yellow]"
    else:
        return f"[red]{confidence:.0%}[/red]"


def _margin_color(margin: float, threshold: float) -> str:
    """Color the margin based on how good it is."""
    if margin >= threshold:
        return f"[bold green]{margin:.1f}%[/bold green]"
    elif margin >= 50:
        return f"[green]{margin:.1f}%[/green]"
    elif margin >= 20:
        return f"[yellow]{margin:.1f}%[/yellow]"
    else:
        return f"[white]{margin:.1f}%[/white]"


def _staleness_tag(opp: Opportunity) -> str:
    """Generate a staleness/snipe indicator."""
    if opp.is_new:
        return "[bold magenta blink]🆕 SNIPE[/bold magenta blink]"
    if opp.scans_seen >= 5 and opp.margin_pct >= 50:
        return "[dim yellow]⏳ STALE[/dim yellow]"
    if opp.scans_seen >= 3:
        return f"[dim]{opp.scans_seen}x[/dim]"
    return ""


def _flip_str(opp: Opportunity) -> str:
    """Format flip calculator: invest → profit."""
    if opp.flip_profit <= 0:
        return "[dim]—[/dim]"
    return (
        f"[dim]{opp.flip_volume}×[/dim] "
        f"[white]{opp.flip_invest:.0f}c[/white]→"
        f"[bold green]+{opp.flip_profit:.0f}c[/bold green]"
    )


def build_opportunity_table(
    opps: list[Opportunity],
    top_n: int = 15,
    alert_threshold: float = 100.0,
    sort_by: str = "profit",
) -> Table:
    """Build a Rich Table of opportunities."""
    table = Table(
        title=None,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        pad_edge=True,
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Item")
    table.add_column("Type", width=9)
    table.add_column("Buy (c)", justify="right")
    table.add_column("Sell (c)", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Margin", justify="right")
    table.add_column("Gold Eff", justify="right", width=9)
    table.add_column("Flip Calc")
    table.add_column("Conf.", justify="right", width=5)
    table.add_column("Trend", justify="center", width=5)
    table.add_column("Δ", justify="right", width=7)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Listings", justify="right", width=8)

    for rank, opp in enumerate(opps[:top_n], start=1):
        is_alert = opp.margin_pct >= alert_threshold
        row_style = "on grey11" if is_alert else ""

        name_str = f"[bold]{opp.name}[/bold]" if is_alert else opp.name

        table.add_row(
            str(rank),
            name_str,
            opp.category,
            f"{opp.buy_price:.2f}",
            f"{opp.sell_price:.2f}",
            f"{opp.spread:.2f}",
            _margin_color(opp.margin_pct, alert_threshold),
            f"[bold gold1]{opp.gold_efficiency}[/bold gold1]c/kG",
            _flip_str(opp),
            _confidence_bar(opp.confidence),
            _trend_arrow(opp.trend),
            _delta_str(opp.margin_delta, opp.is_new),
            _staleness_tag(opp),
            str(opp.total_listings),
            style=row_style,
        )

    return table


def build_multihop_table(routes: list[MultiHopRoute]) -> Optional[Table]:
    """Build a Rich Table of multi-hop arbitrage routes."""
    if not routes:
        return None

    table = Table(
        title=None,
        show_header=True,
        header_style="bold magenta",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Route", min_width=40)
    table.add_column("Net Return", justify="right", width=12)
    table.add_column("Return %", justify="right", width=10)

    for i, route in enumerate(routes[:5], start=1):
        path_str = " → ".join(
            name.replace("Chaos Orb", "[bold yellow]Chaos[/bold yellow]")
            for name in route.path
        )
        color = "green" if route.return_pct > 10 else "yellow" if route.return_pct > 5 else "white"
        table.add_row(
            str(i),
            path_str,
            f"[{color}]{route.net_return:.4f}c[/{color}]",
            f"[{color}]{route.return_pct:.1f}%[/{color}]",
        )

    return table


def build_dashboard(
    opps: list[Opportunity],
    multi_hops: list[MultiHopRoute],
    league: str,
    scan_time: datetime,
    next_refresh_in: int,
    config_top_n: int = 15,
    alert_threshold: float = 100.0,
    total_found: int = 0,
    sort_by: str = "profit",
    shocks: Optional[list[ShockEntry]] = None,
) -> Panel:
    """Build the full dashboard as a Rich Panel."""

    sort_label = {"profit": "Chaos/Trade", "margin": "Margin %", "confidence": "Confidence"}.get(sort_by, sort_by)

    # Header
    header_text = (
        f"[bold cyan]⚡ POEStick Arbitrage Scanner[/bold cyan]  │  "
        f"[white]League:[/white] [bold yellow]{league}[/bold yellow]  │  "
        f"[white]Scanned:[/white] [dim]{scan_time.strftime('%H:%M:%S')}[/dim]  │  "
        f"[white]Next refresh:[/white] [bold]{next_refresh_in}s[/bold]  │  "
        f"[white]Total opps:[/white] [bold green]{total_found}[/bold green]  │  "
        f"[white]Sort:[/white] [bold]{sort_label}[/bold]"
    )
    header = Panel(header_text, border_style="cyan", padding=(0, 1))

    # Opportunity table
    opp_table = build_opportunity_table(opps, config_top_n, alert_threshold, sort_by)
    opp_panel = Panel(
        opp_table,
        title="[bold]💰 Top Arbitrage Opportunities[/bold]",
        border_style="green",
        padding=(0, 0),
    )

    # Multi-hop section
    multihop_table = build_multihop_table(multi_hops)

    # Compose everything into a single group
    from typing import Any
    from rich.console import Group
    parts: list[Any] = [header, opp_panel]

    if multihop_table:
        hop_panel = Panel(
            multihop_table,
            title="[bold]🔄 Multi-Hop Arbitrage Routes[/bold]",
            border_style="magenta",
            padding=(0, 0),
        )
        parts.append(hop_panel)

    # Supply shock panel (only shown when drops are detected)
    if shocks:
        shock_panel = build_shock_live_panel(shocks)
        if shock_panel:
            parts.append(shock_panel)

    # Footer
    footer_text = (
        "[dim]Press [bold]Ctrl+C[/bold] to exit  │  "
        "Data from poe.ninja  │  "
        "Flip Calc = volume × buy→profit  │  "
        "🆕 SNIPE = new this scan  │  "
        "⏳ STALE = 5+ scans at high margin[/dim]"
    )
    parts.append(Text.from_markup(footer_text))

    return Panel(
        Group(*parts),
        border_style="bright_black",
        padding=(0, 0),
    )


def build_alert_panel(opp: Opportunity) -> Panel:
    """Build a highlighted alert panel for a high-margin opportunity."""
    alert_text = (
        f"[bold white on red] 🚨 ALERT [/bold white on red]  "
        f"[bold]{opp.name}[/bold] ({opp.category})  │  "
        f"Margin: [bold green]{opp.margin_pct:.1f}%[/bold green]  │  "
        f"Spread: {opp.spread:.2f}c  │  "
        f"Buy {opp.buy_price:.2f}c → Sell {opp.sell_price:.2f}c  │  "
        f"Flip: [bold green]+{opp.flip_profit:.0f}c[/bold green] ({opp.flip_volume}×)"
    )
    return Panel(alert_text, border_style="red", padding=(0, 1))


# ──────────────────────────────────────────────────────────────────
# Export functions
# ──────────────────────────────────────────────────────────────────

def export_csv(opps: list[Opportunity], path: str = "") -> str:
    """Export opportunities to a CSV file. Returns the path written."""
    if not path:
        path = str(Path(__file__).parent / "poestick_export.csv")
    fieldnames = [
        "rank", "name", "category", "buy_price", "sell_price", "spread",
        "margin_pct", "confidence", "profit_score", "trend",
        "total_listings", "pay_listings", "recv_listings", "chaos_equivalent",
        "flip_volume", "flip_invest", "flip_return", "flip_profit",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rank, opp in enumerate(opps, start=1):
            writer.writerow({
                "rank": rank,
                "name": opp.name,
                "category": opp.category,
                "buy_price": opp.buy_price,
                "sell_price": opp.sell_price,
                "spread": opp.spread,
                "margin_pct": opp.margin_pct,
                "confidence": opp.confidence,
                "profit_score": opp.profit_score,
                "trend": opp.trend,
                "total_listings": opp.total_listings,
                "pay_listings": opp.pay_listings,
                "recv_listings": opp.recv_listings,
                "chaos_equivalent": opp.chaos_equivalent,
                "flip_volume": opp.flip_volume,
                "flip_invest": opp.flip_invest,
                "flip_return": opp.flip_return,
                "flip_profit": opp.flip_profit,
            })

    return path


def export_json(opps: list[Opportunity], path: str = "") -> str:
    """Export opportunities to a JSON file. Returns the path written."""
    if not path:
        path = str(Path(__file__).parent / "poestick_export.json")
    data = []
    for rank, opp in enumerate(opps, start=1):
        data.append({
            "rank": rank,
            "name": opp.name,
            "category": opp.category,
            "buy_price": opp.buy_price,
            "sell_price": opp.sell_price,
            "spread": opp.spread,
            "margin_pct": opp.margin_pct,
            "confidence": opp.confidence,
            "profit_score": opp.profit_score,
            "trend": opp.trend,
            "total_listings": opp.total_listings,
            "pay_listings": opp.pay_listings,
            "recv_listings": opp.recv_listings,
            "chaos_equivalent": opp.chaos_equivalent,
            "flip_volume": opp.flip_volume,
            "flip_invest": opp.flip_invest,
            "flip_return": opp.flip_return,
            "flip_profit": opp.flip_profit,
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return path
