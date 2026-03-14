"""
POEStick — Configuration loader.

Reads config.toml and merges with CLI overrides into a Config dataclass.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Default config file location (next to this script)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.toml"


@dataclass
class Config:
    """Merged configuration from TOML + CLI overrides."""

    # General
    league: str = "Mirage"  # default to Mirage to avoid broken API auto-detect
    refresh_interval: int = 20
    
    # Pro Features
    auto_copy_snipes: bool = True
    desktop_notifications: bool = True
    ignore_items: list[str] = field(default_factory=list)
    target_items: list[str] = field(default_factory=list)

    # Filters
    min_listings: int = 10
    min_margin_pct: float = 1.0
    top_n: int = 15
    sort_by: str = "profit"  # profit | margin | confidence

    # Analysis
    slippage_pct: float = 2.0
    multi_hop_enabled: bool = True
    max_hops: int = 3
    multi_hop_extra_roots: list[str] = field(default_factory=lambda: ["Divine Orb", "Exalted Orb"])
    mirage_encounter_multiplier: float = 1.5

    # Alerts
    alert_margin_threshold: float = 100.0
    sound_enabled: bool = True

    # History
    db_path: str = "poestick_history.db"

    # Runtime (set by CLI, not in TOML)
    output_format: str = "table"  # table | csv | json
    run_once: bool = False


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from TOML file, falling back to defaults."""
    path = config_path or DEFAULT_CONFIG_PATH
    cfg = Config()

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)

        general = data.get("general", {})
        cfg.league = general.get("league", cfg.league)
        cfg.refresh_interval = max(20, general.get("refresh_interval", cfg.refresh_interval))

        pro = data.get("pro", {})
        cfg.auto_copy_snipes = pro.get("auto_copy_snipes", cfg.auto_copy_snipes)
        cfg.desktop_notifications = pro.get("desktop_notifications", cfg.desktop_notifications)
        cfg.ignore_items = pro.get("ignore_items", cfg.ignore_items)
        cfg.target_items = pro.get("target_items", cfg.target_items)

        filters = data.get("filters", {})
        cfg.min_listings = filters.get("min_listings", cfg.min_listings)
        cfg.min_margin_pct = filters.get("min_margin_pct", cfg.min_margin_pct)
        cfg.top_n = filters.get("top_n", cfg.top_n)
        cfg.sort_by = filters.get("sort_by", cfg.sort_by)

        analysis = data.get("analysis", {})
        cfg.slippage_pct = analysis.get("slippage_pct", cfg.slippage_pct)
        cfg.multi_hop_enabled = analysis.get("multi_hop_enabled", cfg.multi_hop_enabled)
        cfg.max_hops = analysis.get("max_hops", cfg.max_hops)
        cfg.multi_hop_extra_roots = analysis.get("multi_hop_extra_roots", cfg.multi_hop_extra_roots)
        cfg.mirage_encounter_multiplier = analysis.get("mirage_encounter_multiplier", cfg.mirage_encounter_multiplier)

        alerts = data.get("alerts", {})
        cfg.alert_margin_threshold = alerts.get("margin_threshold", cfg.alert_margin_threshold)
        cfg.sound_enabled = alerts.get("sound_enabled", cfg.sound_enabled)

        history = data.get("history", {})
        cfg.db_path = history.get("db_path", cfg.db_path)

    return cfg


def apply_cli_overrides(cfg: Config, args) -> Config:
    """Apply CLI argument overrides onto an existing Config."""
    if args.league:
        cfg.league = args.league
    if args.min_margin is not None:
        cfg.min_margin_pct = args.min_margin
    if args.min_listings is not None:
        cfg.min_listings = args.min_listings
    if args.top is not None:
        cfg.top_n = args.top
    if args.interval is not None:
        cfg.refresh_interval = max(60, args.interval)
    if args.output:
        cfg.output_format = args.output
    if args.sort:
        cfg.sort_by = args.sort
    if args.no_sound:
        cfg.sound_enabled = False
    if args.once:
        cfg.run_once = True
    return cfg
