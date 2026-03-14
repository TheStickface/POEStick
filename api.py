"""
POEStick — poe.ninja API client.

Handles network requests, rate-limiting, retries, and league auto-detection.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import requests

BASE_URL = "https://poe.ninja/api/data/currencyoverview"
INDEX_URL = "https://poe.ninja/api/data/getindexstate"

REQUEST_TIMEOUT = 15
RATE_LIMIT_PAUSE = 5
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "POEStick-Arbitrage/2.0 (contact: github.com/poestick)",
    "Accept": "application/json",
}


def fetch_json(url: str, label: str, console=None) -> dict:
    """
    GET *url* and return parsed JSON.
    Handles timeouts, HTTP errors, and 429 rate-limits with retries.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        resp = None
        try:
            if console:
                console.log(f"[dim]\\[{label}] Fetching (attempt {attempt}/{MAX_RETRIES})...[/dim]")

            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", RATE_LIMIT_PAUSE))
                if console:
                    console.log(f"[yellow]⚠ Rate-limited (429). Waiting {retry_after}s...[/yellow]")
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.Timeout:
            if console:
                console.log(f"[yellow]⚠ Timeout after {REQUEST_TIMEOUT}s (attempt {attempt}).[/yellow]")
        except requests.exceptions.ConnectionError as exc:
            if console:
                console.log(f"[yellow]⚠ Connection error: {exc}[/yellow]")
        except requests.exceptions.HTTPError as exc:
            if resp is not None and resp.status_code == 404:
                # Don't retry 404s, they won't magically appear
                return {}
            if console:
                console.log(f"[yellow]⚠ HTTP error: {exc}[/yellow]")

        if attempt < MAX_RETRIES:
            wait = 2 ** attempt
            if console:
                console.log(f"[dim]   Retrying in {wait}s...[/dim]")
            time.sleep(wait)

    if console:
        console.log(f"[red]✗ Failed to fetch {label} after {MAX_RETRIES} attempts.[/red]")
    return {}


def detect_league(console=None) -> str:
    """
    Auto-detect the current challenge league from poe.ninja's index state.
    Falls back to 'Standard' if detection fails.
    """
    if console:
        console.log("[dim]Auto-detecting current league...[/dim]")

    data = fetch_json(INDEX_URL, "LeagueDetect", console)

    if not data:
        if console:
            console.log("[yellow]⚠ Could not detect league (API unavailable), falling back to 'Mirage'[/yellow]")
        return "Mirage"

    # The index state contains economyLeagues with a list of league objects
    economy_leagues = data.get("economyLeagues", [])
    for league_info in economy_leagues:
        name = league_info.get("name", "")
        # Skip Standard, Hardcore, and Ruthless variants
        if name and name not in ("Standard", "Hardcore", "Ruthless", "Solo Self-Found"):
            if "Hardcore" not in name and "Ruthless" not in name and "SSF" not in name:
                if console:
                    console.log(f"[green]✓ Detected league: {name}[/green]")
                return name

    if console:
        console.log("[yellow]⚠ No challenge league found, falling back to 'Mirage'[/yellow]")
    return "Mirage"


def fetch_currency_data(league: str, currency_type: str, console=None) -> dict:
    """Fetch currency overview data for a given league and type (Currency / Fragment)."""
    url = f"{BASE_URL}?league={league}&type={currency_type}"
    return fetch_json(url, currency_type, console)
