"""
POEStick — CLI argument parsing.
"""

from __future__ import annotations

import argparse


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="poestick",
        description="POEStick — Live PoE currency arbitrage scanner powered by poe.ninja",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python main.py                        # live dashboard, auto-detect league
  python main.py --once --top 10        # single scan, top 10
  python main.py --league Mirage --interval 90
  python main.py --once --output csv    # export to CSV
  python main.py --once --output json   # export to JSON
  python main.py --div-cards            # divination card arbitrage
  python main.py --wombgift             # wombgift evaluator
  python main.py --gold-squeeze         # gold squeeze advisor
  python main.py --breachstone          # breachstone multi-tier upgrader
  python main.py --bulk-fragments       # boss fragment aggregation
  python main.py --delirium-orbs        # delirium orb profit calculator
  python main.py --essences             # essence upgrade path evaluator
  python main.py --gem-arbitrage        # exceptional/awakened gem scanner
  python main.py --logbooks             # expedition logbook estimator
  python main.py --scarab-tiers         # scarab per-family tier analysis
  python main.py --stacked-deck         # stacked deck ev calculator
  python main.py --scarabs              # scarab set aggregator
  python main.py --harvest              # harvest lifeforce + catalyst prices + Cornucopia ROI
  python main.py --strongbox            # operative strongbox ROI (Mirage scarab drops)
  python main.py --supply-shock         # detect supply drops/surges across all categories
  python main.py --fossils              # fossil price index + delve ROI (3.28 meta)
  python main.py --astrolabes          # astrolabe -> memory vault ROI (3.28 new)
  python main.py --breach-fortress     # breach fortress combo analyzer (3.28 new)
        """,
    )

    parser.add_argument(
        "--league", "-l",
        type=str,
        default="",
        help="League name (auto-detected if omitted)",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=None,
        help="Minimum margin %% to display (default: from config.toml)",
    )
    parser.add_argument(
        "--min-listings",
        type=int,
        default=None,
        help="Minimum total listing count filter (default: from config.toml)",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=None,
        help="Number of top opportunities to display (default: from config.toml)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=None,
        help="Refresh interval in seconds (min 60, default: from config.toml)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        choices=["table", "csv", "json"],
        default="",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--sort", "-s",
        type=str,
        choices=["profit", "margin", "confidence"],
        default="",
        help="Sort opportunities by: profit (chaos/trade), margin (%%), or confidence",
    )
    parser.add_argument(
        "--no-sound",
        action="store_true",
        help="Disable alert sounds",
    )
    parser.add_argument(
        "--foulborn",
        action="store_true",
        help="Calculate the most profitable Foulborn unique upgrades",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit (no live dashboard)",
    )
    parser.add_argument(
        "--div-cards",
        action="store_true",
        help="Analyze Divination Card set completion profit",
    )
    parser.add_argument(
        "--wombgift",
        action="store_true",
        help="Analyze Wombgift and Chitinous implicit upgrades",
    )
    parser.add_argument(
        "--gold-squeeze",
        action="store_true",
        help="Compare Faustus vs Player Trade (Gold Squeeze Advisor)",
    )
    parser.add_argument(
        "--breachstone",
        action="store_true",
        help="Analyze Breachstone upgrade profitability",
    )
    parser.add_argument(
        "--bulk-fragments",
        action="store_true",
        help="Find Boss Fragment set aggregation premiums",
    )
    parser.add_argument(
        "--stacked-deck",
        action="store_true",
        help="Calculate Expected Value for Stacked Decks",
    )
    parser.add_argument(
        "--scarabs",
        action="store_true",
        help="Analyze Scarab mapping set premiums",
    )
    parser.add_argument(
        "--delirium-orbs",
        action="store_true",
        help="Calculate Delirium Orb application profits per map type",
    )
    parser.add_argument(
        "--essences",
        action="store_true",
        help="Evaluate Essence upgrade paths (Remnant of Corruption/Corruption)",
    )
    parser.add_argument(
        "--gem-arbitrage",
        action="store_true",
        help="Scan Awakened/Exceptional gem flip opportunities",
    )
    parser.add_argument(
        "--logbooks",
        action="store_true",
        help="Estimate Expedition Logbook currency yields per NPC",
    )
    parser.add_argument(
        "--scarab-tiers",
        action="store_true",
        help="Analyze per-family Scarab tier pricing and spreads",
    )
    parser.add_argument(
        "--harvest",
        action="store_true",
        help="Harvest lifeforce + catalyst prices + Cornucopia ROI (Mirage-multiplied)",
    )
    parser.add_argument(
        "--strongbox",
        action="store_true",
        help="Strongbox → Operative Strongbox ROI (Mirage conversion, scarab drops)",
    )
    parser.add_argument(
        "--supply-shock",
        action="store_true",
        help="Detect sudden listing count drops/surges across all item categories",
    )
    parser.add_argument(
        "--fossils",
        action="store_true",
        help="Fossil price index + Delve ROI calculator (3.28: Delve-exclusive supply)",
    )
    parser.add_argument(
        "--astrolabes",
        action="store_true",
        help="Astrolabe → Memory Vault ROI analyzer (3.28 new mechanic)",
    )
    parser.add_argument(
        "--breach-fortress",
        action="store_true",
        help="Breach Fortress combo analyzer (Marshall + Hive Scarab ROI)",
    )

    return parser.parse_args()
