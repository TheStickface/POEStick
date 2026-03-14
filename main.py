#!/usr/bin/env python3
"""
POEStick — Live PoE currency arbitrage scanner powered by poe.ninja.

A Rich TUI dashboard that monitors currency markets in real-time,
identifies arbitrage opportunities, and tracks price movements.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict


from rich.console import Console

from rich.live import Live

from cli import parse_args
from config import load_config, apply_cli_overrides
from foulborn import analyze_foulborn_crafts, print_foulborn_table
from div_arbitrage import analyze_div_cards, print_div_card_table
from evaluator import analyze_wombgifts, print_wombgift_table
from gold_squeeze import analyze_gold_squeeze, print_gold_squeeze_table
from breach_upgrades import analyze_breach_upgrades, print_breach_table
from fragment_aggregator import analyze_fragments, print_fragment_table
from stacked_deck_ev import analyze_stacked_deck_ev, print_stacked_deck_table
from scarab_aggregator import analyze_scarabs, print_scarab_table, analyze_scarab_tiers, print_scarab_tier_table
from delirium_orbs import analyze_delirium_orbs, print_delirium_orb_table
from essence_tier import analyze_essences, print_essence_table
from gem_arbitrage import analyze_gems, print_gem_table
from expedition_logbook import analyze_logbooks, print_logbook_table
from supply_shock import (
    init_listing_db, record_listings, detect_shocks,
    extract_snapshot, run_supply_shock_scan, print_shock_table,
)
from harvest_analyzer import analyze_harvest, print_harvest_table
from strongbox_analyzer import analyze_strongbox, print_strongbox_table
from fossil_arbitrage import analyze_fossils, print_fossil_table
from astrolabe_analyzer import analyze_astrolabes, print_astrolabe_table
from breach_fortress import analyze_breach_fortress, print_breach_fortress_table
from api import detect_league, fetch_currency_data, fetch_json
from analysis import (
    extract_opportunities,
    detect_multi_hop,
    compute_deltas,
    Opportunity,
)
from display import (
    build_dashboard,
    build_alert_panel,
    export_csv,
    export_json,
)
from history import init_db, log_scan, get_previous_opps, cleanup_old_scans
from pricing import init_pricing_db, record_prices, cleanup_price_history

import pyperclip
try:
    from win11toast import toast
except ImportError:
    toast = None

console = Console()

# Graceful shutdown flag
_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    _shutdown = True


# Sort key functions
SORT_KEYS = {
    "profit": lambda o: o.profit_score,
    "margin": lambda o: o.margin_pct,
    "confidence": lambda o: o.confidence,
}


def _apply_staleness(
    current: list[Opportunity],
    staleness_tracker: dict[str, tuple[int, str]],
    scan_time: datetime,
) -> dict[str, tuple[int, str]]:
    """
    Update staleness tracking and apply it to current opportunities.
    Returns updated tracker.
    """
    ts_iso = scan_time.isoformat()
    new_tracker: dict[str, tuple[int, str]] = {}

    for opp in current:
        if opp.name in staleness_tracker:
            prev_count, first_ts = staleness_tracker[opp.name]
            opp.scans_seen = prev_count + 1
            opp.first_seen_ts = first_ts
        else:
            opp.scans_seen = 1
            opp.first_seen_ts = ts_iso

        new_tracker[opp.name] = (opp.scans_seen, opp.first_seen_ts or ts_iso)

    return new_tracker


def run_scan(league: str, config, db_conn, previous_opps: list[Opportunity]):
    """
    Execute a single scan cycle:
    1. Fetch data from poe.ninja
    2. Extract opportunities
    3. Detect multi-hop routes
    4. Compute deltas
    5. Log to database
    """
    # Fetch data
    curr_data = fetch_currency_data(league, "Currency", console)
    frag_data = fetch_currency_data(league, "Fragment", console)

    all_raw_data: list[dict] = []
    if curr_data:
        all_raw_data.append(curr_data)
    if frag_data:
        all_raw_data.append(frag_data)

    # Global Price Tracking
    total_lines = curr_data.get("lines", []) + frag_data.get("lines", [])
    price_map = { (l.get("name") or l.get("currencyTypeName")): (l.get("chaosValue") or l.get("chaosEquivalent")) 
                  for l in total_lines if (l.get("name") or l.get("currencyTypeName")) }
    if db_conn:
        record_prices(db_conn, price_map)

    # Step 2: Analysis
    all_opps: list[Opportunity] = []
    if curr_data:
        all_opps.extend(extract_opportunities(
            curr_data, "Currency", db_conn,
            min_listings=getattr(config, "min_listings", 10),
            min_margin_pct=getattr(config, "min_margin_pct", 1.0),
            slippage_pct=getattr(config, "slippage_pct", 2.0),
            ignore_items=getattr(config, "ignore_items", []),
            target_items=getattr(config, "target_items", []),
        ))
    if frag_data:
        all_opps.extend(extract_opportunities(
            frag_data, "Fragment", db_conn,
            min_listings=getattr(config, "min_listings", 10),
            min_margin_pct=getattr(config, "min_margin_pct", 1.0),
            slippage_pct=getattr(config, "slippage_pct", 2.0),
            ignore_items=getattr(config, "ignore_items", []),
            target_items=getattr(config, "target_items", []),
        ))

    # Sort by configured key (default: profit_score)
    sort_fn = SORT_KEYS.get(config.sort_by, SORT_KEYS["profit"])
    all_opps.sort(key=sort_fn, reverse=True)

    # Compute deltas from previous scan
    if previous_opps:
        compute_deltas(all_opps, previous_opps)

    # Detect multi-hop routes (Chaos + Divine/Exalted roots per 3.28 Chaos devaluation)
    multi_hops = []
    if config.multi_hop_enabled and all_raw_data:
        multi_hops = detect_multi_hop(
            all_raw_data,
            config.max_hops,
            extra_roots=getattr(config, "multi_hop_extra_roots", []),
        )

    # Record listing snapshot for supply shock detection
    shocks = []
    if db_conn:
        snapshot: dict = {}
        snapshot.update(extract_snapshot(curr_data, "Currency"))
        snapshot.update(extract_snapshot(frag_data, "Fragment"))
        record_listings(db_conn, snapshot)
        shocks = detect_shocks(db_conn)

    # Log to database
    scan_time = datetime.now()
    if db_conn:
        log_scan(db_conn, league, all_opps, scan_time)

    return all_opps, multi_hops, scan_time, shocks


def run_once(league: str, config, db_conn):
    """Single scan mode — print/export results and exit."""
    previous_opps = get_previous_opps(db_conn) if db_conn else []
    all_opps, multi_hops, scan_time, shocks = run_scan(league, config, db_conn, previous_opps)

    if not all_opps:
        console.print("[yellow]No arbitrage opportunities found. Try lowering min-margin or min-listings.[/yellow]")
        sys.exit(0)

    # Handle export modes
    if config.output_format == "csv":
        path = export_csv(all_opps)
        console.print(f"[green]✓ Exported {len(all_opps)} opportunities to {path}[/green]")
        return

    if config.output_format == "json":
        path = export_json(all_opps)
        console.print(f"[green]✓ Exported {len(all_opps)} opportunities to {path}[/green]")
        return

    # Table output
    dashboard = build_dashboard(
        opps=all_opps,
        multi_hops=multi_hops,
        league=league,
        scan_time=scan_time,
        next_refresh_in=0,
        config_top_n=config.top_n,
        alert_threshold=config.alert_margin_threshold,
        total_found=len(all_opps),
        sort_by=config.sort_by,
        shocks=shocks,
    )
    console.print(dashboard)

    # Show best opportunity summary
    if all_opps:
        best = all_opps[0]
        console.print(
            f"\n  💰 [bold]Best opportunity:[/bold] {best.name} "
            f"({best.category}) at [bold green]{best.margin_pct:.1f}%[/bold green] margin "
            f"(buy {best.buy_price:.2f}c → sell {best.sell_price:.2f}c) "
            f"— Flip profit: [bold green]+{best.flip_profit:.0f}c[/bold green]\n"
        )


def run_live(league: str, config, db_conn):
    """Live dashboard mode — continuously refresh with countdown."""
    global _shutdown

    # Set up graceful shutdown (handle SIGINT; SIGTERM not reliable on Windows)
    signal.signal(signal.SIGINT, _signal_handler)
    if os.name != "nt":
        signal.signal(signal.SIGTERM, _signal_handler)

    previous_opps: list[Opportunity] = get_previous_opps(db_conn) if db_conn else []
    seen_alerts: set[str] = set()
    staleness_tracker: dict[str, tuple[int, str]] = {}

    console.print(
        f"\n[bold cyan]⚡ POEStick Live Dashboard[/bold cyan]  │  "
        f"League: [bold yellow]{league}[/bold yellow]  │  "
        f"Refresh: {config.refresh_interval}s  │  "
        f"Sort: {config.sort_by}  │  "
        f"Press [bold]Ctrl+C[/bold] to exit\n"
    )

    # Periodic old-scan cleanup
    if db_conn:
        cleanup_old_scans(db_conn)

    with Live(console=console, refresh_per_second=4, screen=True, auto_refresh=False) as live:
        while not _shutdown:
            # Run scan
            all_opps, multi_hops, scan_time, shocks = run_scan(
                league, config, db_conn, previous_opps
            )

            # Apply staleness tracking
            staleness_tracker = _apply_staleness(all_opps, staleness_tracker, scan_time)

            # Check for new high-margin alerts
            for opp in all_opps:
                if opp.margin_pct >= config.alert_margin_threshold:
                    if opp.name not in seen_alerts:
                        seen_alerts.add(opp.name)
                        
                        # Trigger system mechanisms
                        if config.sound_enabled:
                            print("\a", end="", flush=True)  # terminal bell
                        
                        if opp.is_new:  # Only for freshly generated snipes
                            if config.auto_copy_snipes:
                                pyperclip.copy(opp.name)
                            
                            if config.desktop_notifications and toast:
                                toast(
                                    "⚡ POEStick Snipe Alert",
                                    f"{opp.name} | +{opp.flip_profit:.0f}c Profit\nBuy {opp.buy_price:.2f}c -> Sell {opp.sell_price:.2f}c"
                                )

            # Countdown loop — update display every 5s to avoid flicker
            remaining = config.refresh_interval
            while remaining >= 0 and not _shutdown:
                dashboard = build_dashboard(
                    opps=all_opps,
                    multi_hops=multi_hops,
                    league=league,
                    scan_time=scan_time,
                    next_refresh_in=remaining,
                    config_top_n=config.top_n,
                    alert_threshold=config.alert_margin_threshold,
                    total_found=len(all_opps),
                    sort_by=config.sort_by,
                    shocks=shocks,
                )
                live.update(dashboard, refresh=True)

                # Sleep in 1s chunks but only re-render every 5s
                sleep_chunk = min(5, remaining) if remaining > 0 else 0
                if sleep_chunk > 0:
                    for _ in range(sleep_chunk):
                        if _shutdown:
                            break
                        time.sleep(1)
                    remaining -= sleep_chunk
                else:
                    break

            # Save current as previous for next delta
            previous_opps = all_opps.copy()

    # Clean shutdown
    console.print("\n[bold cyan]⚡ POEStick shutting down. Good luck with the flips![/bold cyan]\n")


def main():
    args = parse_args()
    config = load_config()
    console = Console()

    # Apply configuration defaults to missing arguments
    console = Console() # Keep console init here
    apply_cli_overrides(config, args)

    # Global variables from merged config
    league = config.league
    top_n = config.top_n
    min_listings = config.min_listings

    # 1. Initialize Database First
    db_conn = None
    try:
        db_path = getattr(config, "db_path", "poestick_history.db")
        db_conn = init_db(db_path)
        init_pricing_db(db_conn)
        init_listing_db(db_conn)
        cleanup_old_scans(db_conn)
        cleanup_price_history(db_conn)
    except Exception as exc:
        console.print(f"[yellow]⚠ Database error: {exc}. Moving on without trends/history.[/yellow]")

    # 2. Handle Specialized Scanners (Individual Modes)
    
    # --- Foulborn Crafts Mode ---
    if hasattr(args, 'foulborn') and args.foulborn:
        with console.status("[bold green]Scanning for Foulborn upgrades...", spinner="dots"):
            # Record prices before analysis to seed trends
            curr = fetch_currency_data(league, "Currency", console)
            unique_data = fetch_json(f"https://poe.ninja/api/data/itemoverview?league={league}&type=UniqueWeapon", "Unique", console)
            if db_conn:
                record_prices(db_conn, {l.get("name"): l.get("chaosValue") for l in curr.get("lines", []) if l.get("name")})
                record_prices(db_conn, {l.get("name"): l.get("chaosValue") for l in unique_data.get("lines", []) if l.get("name")})
            
            crafts = analyze_foulborn_crafts(league, db_conn, min_listings=max(min_listings // 3, 3), console=console)
        print_foulborn_table(crafts, console, limit=top_n)
        return

    # --- Divination Card Arbitrage Mode ---
    if hasattr(args, 'div_cards') and args.div_cards:
        with console.status("[bold magenta]Scanning Divination Cards...", spinner="dots"):
            crafts = analyze_div_cards(league, db_conn, min_listings=min_listings, console=console)
        print_div_card_table(crafts, console, limit=top_n)
        return

    # --- Wombgift Evaluator Mode ---
    if hasattr(args, 'wombgift') and args.wombgift:
        with console.status("[bold green]Evaluating Wombgifts...", spinner="dots"):
            upgrades = analyze_wombgifts(league, db_conn, console=console)
        print_wombgift_table(upgrades, console, limit=top_n)
        return

    # --- Gold Squeeze Advisor Mode ---
    if hasattr(args, 'gold_squeeze') and args.gold_squeeze:
        with console.status("[bold gold1]Analyzing Gold Squeeze...", spinner="dots"):
            entries = analyze_gold_squeeze(league, db_conn, console=console)
        print_gold_squeeze_table(entries, console, limit=top_n)
        return

    # --- Breachstone Upgrader Mode ---
    if hasattr(args, 'breachstone') and args.breachstone:
        with console.status("[bold purple]Evaluating Breachstones...", spinner="dots"):
            upgrades = analyze_breach_upgrades(league, db_conn, console=console)
        print_breach_table(upgrades, console)
        return

    # --- Bulk Fragment Finder Mode ---
    if hasattr(args, 'bulk_fragments') and args.bulk_fragments:
        with console.status("[bold blue]Calculating Fragment Premiums...", spinner="dots"):
            sets = analyze_fragments(league, db_conn, console=console)
        print_fragment_table(sets, console)
        return

    # --- Stacked Deck EV Mode ---
    if hasattr(args, 'stacked_deck') and args.stacked_deck:
        with console.status("[bold cyan]Calculating Stacked Deck EV...", spinner="dots"):
            # Auto-fetch Cloister Scarab price to factor into cost-per-deck
            cloister_cost = 0.0
            try:
                scarab_data = fetch_json(
                    f"https://poe.ninja/api/data/itemoverview?league={league}&type=Scarab",
                    "Scarab", console
                )
                for s in scarab_data.get("lines", []):
                    if s.get("name") == "Divination Scarab of The Cloister":
                        cloister_cost = s.get("chaosValue", 0.0)
                        break
            except Exception:
                pass
            result = analyze_stacked_deck_ev(league, db_conn, console=console,
                                            cloister_scarab_cost=cloister_cost,
                                            mirage_multiplier=config.mirage_encounter_multiplier)
        print_stacked_deck_table(result, console)
        return

    # --- Scarab Aggregator Mode ---
    if hasattr(args, 'scarabs') and args.scarabs:
        with console.status("[bold yellow]Analyzing Scarab Sets...", spinner="dots"):
            sets = analyze_scarabs(league, db_conn, console=console)
        print_scarab_table(sets, console)
        return

    # --- Delirium Orb Mode ---
    if hasattr(args, 'delirium_orbs') and args.delirium_orbs:
        with console.status("[bold magenta]Scanning Delirium Orbs...", spinner="dots"):
            orbs = analyze_delirium_orbs(league, db_conn, console=console,
                                         mirage_multiplier=config.mirage_encounter_multiplier)
        print_delirium_orb_table(orbs, console, limit=top_n)
        return

    # --- Essence Tier Mode ---
    if hasattr(args, 'essences') and args.essences:
        with console.status("[bold cyan]Evaluating Essences...", spinner="dots"):
            entries = analyze_essences(league, db_conn, console=console)
        print_essence_table(entries, console, limit=top_n)
        return

    # --- Gem Arbitrage Mode ---
    if hasattr(args, 'gem_arbitrage') and args.gem_arbitrage:
        with console.status("[bold green]Scanning Gem Flips...", spinner="dots"):
            flips = analyze_gems(league, db_conn, console=console)
        print_gem_table(flips, console, limit=top_n)
        return

    # --- Expedition Logbook Mode ---
    if hasattr(args, 'logbooks') and args.logbooks:
        with console.status("[bold yellow]Analyzing Logbooks...", spinner="dots"):
            entries = analyze_logbooks(league, db_conn, console=console,
                                       mirage_multiplier=config.mirage_encounter_multiplier)
        print_logbook_table(entries, console, limit=top_n)
        return

    # --- Scarab Tier Analysis Mode ---
    if hasattr(args, 'scarab_tiers') and args.scarab_tiers:
        with console.status("[bold yellow]Analyzing Scarab Tiers...", spinner="dots"):
            family_map = analyze_scarab_tiers(league, db_conn, console=console)
        print_scarab_tier_table(family_map, console)
        return

    # --- Harvest Analyzer Mode ---
    if hasattr(args, 'harvest') and args.harvest:
        with console.status("[bold green]Analyzing Harvest prices...", spinner="dots"):
            lifeforce, catalysts, roi = analyze_harvest(
                league, db_conn,
                mirage_multiplier=config.mirage_encounter_multiplier,
                console=console,
            )
        print_harvest_table(lifeforce, catalysts, roi, console, limit=top_n)
        return

    # --- Strongbox Analyzer Mode ---
    if hasattr(args, 'strongbox') and args.strongbox:
        with console.status("[bold yellow]Analyzing Strongbox ROI...", spinner="dots"):
            result = analyze_strongbox(
                league, db_conn,
                mirage_multiplier=config.mirage_encounter_multiplier,
                console=console,
            )
        print_strongbox_table(result, console)
        return

    # --- Supply Shock Detector Mode ---
    if hasattr(args, 'supply_shock') and args.supply_shock:
        with console.status("[bold red]Scanning for supply shocks across all categories...", spinner="dots"):
            shocks = run_supply_shock_scan(league, db_conn, console=console)
        print_shock_table(shocks, console, limit=top_n)
        return

    # --- Fossil Arbitrage Mode ---
    if hasattr(args, 'fossils') and args.fossils:
        with console.status("[bold yellow]Fetching Fossil prices...", spinner="dots"):
            fossils, delve_roi = analyze_fossils(league, db_conn, console=console)
        print_fossil_table(fossils, delve_roi, console, limit=top_n)
        return

    # --- Astrolabe Analyzer Mode ---
    if hasattr(args, 'astrolabes') and args.astrolabes:
        with console.status("[bold cyan]Analyzing Astrolabes...", spinner="dots"):
            entries = analyze_astrolabes(league, db_conn, console=console)
        print_astrolabe_table(entries, console, limit=top_n)
        return

    # --- Breach Fortress Mode ---
    if hasattr(args, 'breach_fortress') and args.breach_fortress:
        with console.status("[bold purple]Analyzing Breach Fortress combo...", spinner="dots"):
            result = analyze_breach_fortress(league, db_conn, console=console)
        print_breach_fortress_table(result, console)
        return

    # 3. Standard Scanning Mode (TUI Dashboard)
    config.league = league # Sync back for run loops
    if config.run_once:
        run_once(league, config, db_conn)
    else:
        run_live(league, config, db_conn)

    if db_conn:
        db_conn.close()


if __name__ == "__main__":
    main()
