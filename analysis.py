"""
POEStick — Arbitrage analysis engine.

Extracts opportunities, computes confidence scores, detects multi-hop cycles,
calculates deltas between scans, and tracks opportunity staleness.
"""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from pricing import get_4h_trend, get_safe_price


@dataclass
class Opportunity:
    """A single arbitrage opportunity."""
    name: str
    category: str           # "Currency" or "Fragment"
    buy_price: float        # Chaos cost to acquire 1 unit
    sell_price: float       # Chaos received when selling 1 unit
    spread: float           # sell - buy (after slippage)
    margin_pct: float       # (spread / buy) × 100
    pay_listings: int       # listings on the sell-to-buyer side
    recv_listings: int      # listings on the buy-from-seller side
    total_listings: int
    confidence: float       # 0.0–1.0 score
    profit_score: float     # spread × min(pay, recv) — practical volume metric
    trend: float            # sparkline totalChange % (positive = rising)
    chaos_equivalent: float # poe.ninja's chaosEquivalent value
    gold_cost: int = 0      # estimated Gold cost for a single unit flip
    gold_efficiency: float = 0.0 # profit per 1000 Gold spent

    # Flip calculator fields
    flip_volume: int = 0            # realistic trade size = min(pay, recv) listings
    flip_invest: float = 0.0       # total Chaos to invest for flip_volume units
    flip_return: float = 0.0       # total Chaos received after selling flip_volume units
    flip_profit: float = 0.0       # net profit = flip_return - flip_invest

    # Delta tracking (filled in after comparison with previous scan)
    margin_delta: Optional[float] = None  # change in margin since last scan
    is_new: bool = False                  # True if this item wasn't in last scan

    # Staleness tracking
    scans_seen: int = 1             # consecutive scans this opportunity has appeared
    first_seen_ts: Optional[str] = None  # ISO timestamp when first detected


@dataclass
class MultiHopRoute:
    """A profitable multi-hop currency cycle."""
    path: list[str]         # e.g. ["Chaos", "Exalt", "Divine", "Chaos"]
    net_return: float       # net Chaos profit per 1c invested
    return_pct: float       # net_return × 100


def _sparkline_stability(sparkline_data: dict | None) -> float:
    """
    Convert a sparkline's totalChange into a stability factor (0–1).
    Low change = high stability = good confidence.
    """
    if not sparkline_data:
        return 0.5  # unknown stability
    total_change = abs(sparkline_data.get("totalChange", 0))
    # 0% change → 1.0, 100%+ change → ~0.1
    return max(0.1, 1.0 / (1.0 + total_change / 50.0))


def extract_opportunities(
    data: dict,
    category: str,
    db_conn: sqlite3.Connection,
    min_listings: int = 10,
    min_margin_pct: float = 1.0,
    slippage_pct: float = 2.0,
    ignore_items: list[str] | None = None,
    target_items: list[str] | None = None,
) -> list[Opportunity]:
    """Parse poe.ninja data and find viable arbitrage flips."""
    if not data or "lines" not in data:
        return []

    ignore_items = ignore_items or []
    target_items = target_items or []

    opportunities = []
    lines = data.get("lines", [])

    for line in lines:
        name = line.get("currencyTypeName", "Unknown")
        if name in ignore_items:
            continue
        if target_items and name not in target_items:
            continue

        pay_block = line.get("pay")
        recv_block = line.get("receive")

        # Both sides must be present to calculate a spread
        if not pay_block or not recv_block:
            continue

        pay_value = pay_block.get("value")       # currency per 1 Chaos (invert for sell price)
        recv_value = recv_block.get("value")      # Chaos per 1 unit (buy price directly)

        if not pay_value or not recv_value or pay_value == 0:
            continue

        pay_listings = pay_block.get("listing_count", 0)
        recv_listings = recv_block.get("listing_count", 0)
        total_listings = pay_listings + recv_listings

        # Require a minimum of liquidity on both sides to avoid fake/stale flips
        min_side_listings_req = max(min_listings // 3, 3)
        if total_listings < min_listings or pay_listings < min_side_listings_req or recv_listings < min_side_listings_req:
            continue

        # Buy price  = Chaos cost to acquire 1 unit = recv_value (direct)
        # Sell price  = Chaos received selling 1 unit = 1 / pay_value (inverted)
        # Use safe prices for the spread calculation
        buy_price = recv_value # Original poe.ninja buy price
        sell_price = 1.0 / pay_value # Original poe.ninja sell price
        
        # Trend-adjusted "safe" prices
        safe_buy = get_safe_price(db_conn, name, buy_price)
        safe_sell = get_safe_price(db_conn, name, sell_price)
        
        # Internal 4h trend
        observed_trend = get_4h_trend(db_conn, name, sell_price)
        
        # Apply slippage to the safe spread
        buy_with_slippage = safe_buy * (1 + slippage_pct / 100.0)
        sell_with_slippage = safe_sell * (1 - slippage_pct / 100.0)

        spread = sell_with_slippage - buy_with_slippage
        margin_pct = (spread / safe_buy) * 100.0 # Use safe_buy as the base for margin calculation

        if margin_pct < min_margin_pct:
            continue

        # Confidence scoring
        listing_factor = min(total_listings / 50.0, 1.0)
        recv_stability = _sparkline_stability(line.get("receiveSparkLine"))
        pay_stability = _sparkline_stability(line.get("paySparkLine"))
        confidence = listing_factor * ((recv_stability + pay_stability) / 2.0)

        # Profit score: practical volume-weighted metric
        min_side_listings = min(pay_listings, recv_listings) if pay_listings > 0 else recv_listings
        profit_score = spread * max(min_side_listings, 1)

        # Flip calculator: realistic batch trade
        flip_volume = max(min_side_listings, 1)
        flip_invest = safe_buy * flip_volume # Use safe_buy for investment
        flip_return = safe_sell * flip_volume # Use safe_sell for return
        flip_profit = flip_return - flip_invest

        # Trend from receive sparkline (poe.ninja's trend)
        recv_sparkline = line.get("receiveSparkLine", {})
        ninja_trend = recv_sparkline.get("totalChange", 0) if recv_sparkline else 0

        chaos_eq = line.get("chaosEquivalent", buy_price)

        # Faustus Gold Cost Estimation (3.28 Mirage Heuristic)
        # Assuming avg 1500 gold for currency swaps, 2500 for fragments
        base_gold = 2500 if category == "Fragment" else 1500
        # Scaling by trade value (simplified)
        gold_est = base_gold + int(buy_price * 2) 
        
        # Gold efficiency: Chaos profit per 1k gold spent
        gold_efficiency = (spread / gold_est) * 1000 if gold_est > 0 else 0

        opportunities.append(Opportunity(
            name=name,
            category=category,
            buy_price=round(buy_price, 4),
            sell_price=round(sell_price, 4),
            spread=round(spread, 4),
            margin_pct=round(margin_pct, 2),
            pay_listings=pay_listings,
            recv_listings=recv_listings,
            total_listings=total_listings, # Kept original total_listings
            confidence=round(confidence, 3),
            profit_score=round(profit_score, 2),
            trend=observed_trend or ninja_trend, # Use observed_trend if available, else ninja_trend
            chaos_equivalent=chaos_eq,
            flip_volume=flip_volume,
            flip_invest=round(flip_invest, 1),
            flip_return=round(flip_return, 1),
            flip_profit=round(flip_profit, 1),
            gold_cost=gold_est,
            gold_efficiency=round(gold_efficiency, 2)
        ))

    return opportunities


def detect_multi_hop(
    all_data: list[dict],
    max_hops: int = 3,
    extra_roots: list[str] | None = None,
) -> list[MultiHopRoute]:
    """
    Build a currency graph from all pay/receive pairs and find profitable
    cycles of length 2–max_hops that start and end at a root currency.

    poe.ninja only provides Chaos-relative rates, so we derive cross-rates:
      Currency X → Currency Y = (sell X for Chaos) × (buy Y with Chaos)

    Edges store a *multiplier*: how many units of root you end up with per
    1 unit invested in traversing that edge.

    extra_roots: additional currencies to use as cycle roots alongside
    "Chaos Orb". Useful in 3.28 where Chaos sinks were removed and
    Divine/Exalted Orb cycles may be more profitable.
    e.g. extra_roots=["Divine Orb", "Exalted Orb"]
    """
    # Collect per-currency rates (Chaos-relative)
    # buy_rates[name]  = Chaos cost to buy 1 unit  (= recv_value)
    # sell_rates[name] = Chaos received selling 1 unit (= 1 / pay_value)
    buy_rates: dict[str, float] = {}
    sell_rates: dict[str, float] = {}
    min_listings_threshold = 3

    for data in all_data:
        lines = data.get("lines", [])
        for line in lines:
            name = line.get("currencyTypeName", "Unknown")
            recv_block = line.get("receive")
            pay_block = line.get("pay")

            if recv_block:
                recv_value = recv_block.get("value", 0)
                recv_listings = recv_block.get("listing_count", 0)
                if recv_value > 0 and recv_listings >= min_listings_threshold:
                    buy_rates[name] = recv_value  # Chaos per 1 unit

            if pay_block:
                pay_value = pay_block.get("value", 0)
                pay_listings = pay_block.get("listing_count", 0)
                if pay_value > 0 and pay_listings >= min_listings_threshold:
                    sell_rates[name] = 1.0 / pay_value  # Chaos per 1 unit

    # Build adjacency graph with multipliers
    # Edge (A → B) multiplier = sell_rate_A / buy_rate_B
    #   i.e. sell 1 unit of A for Chaos, then buy B with those Chaos
    #   if multiplier > 1, you gain value traversing A → B
    graph: dict[str, list[tuple[str, float]]] = {}

    # Chaos → Currency edges: multiplier = sell_rate / buy_rate for that currency
    # (buy 1 unit at buy_rate, later sell at sell_rate)
    currencies = set(buy_rates.keys()) | set(sell_rates.keys())
    for name in currencies:
        if name in buy_rates:
            # Chaos → Currency: invest buy_rates[name] Chaos, get 1 unit
            # multiplier applied later when selling
            graph.setdefault("Chaos Orb", []).append((name, 1.0 / buy_rates[name]))
        if name in sell_rates:
            # Currency → Chaos: sell 1 unit, get sell_rates[name] Chaos
            graph.setdefault(name, []).append(("Chaos Orb", sell_rates[name]))

    # Cross-rate edges: Currency X → Currency Y
    sellable = [n for n in currencies if n in sell_rates and n in buy_rates]
    for src in sellable:
        for dst in sellable:
            if src != dst and dst in buy_rates:
                # Sell 1 unit of src → get sell_rates[src] Chaos
                # Buy dst with that Chaos → get sell_rates[src] / buy_rates[dst] units of dst
                cross_rate = sell_rates[src] / buy_rates[dst]
                graph.setdefault(src, []).append((dst, cross_rate))

    # Build root currency list — always include Chaos, optionally others
    roots = ["Chaos Orb"] + (extra_roots or [])

    # DFS to find profitable cycles originating from any root currency
    routes: list[MultiHopRoute] = []

    def dfs(root: str, current: str, path: list[str], value: float, depth: int):
        if depth > max_hops:
            return

        for neighbor, rate in graph.get(current, []):
            new_value = value * rate
            if neighbor == root and len(path) >= 2:
                # Complete cycle back to root
                net_return = new_value - 1.0
                if net_return > 0.01:  # at least 1% profit
                    routes.append(MultiHopRoute(
                        path=path + [neighbor],
                        net_return=round(net_return, 4),
                        return_pct=round(net_return * 100, 2),
                    ))
            elif neighbor not in path and neighbor not in roots:
                dfs(root, neighbor, path + [neighbor], new_value, depth + 1)

    # Start DFS from each root currency
    for root in roots:
        for neighbor, rate in graph.get(root, []):
            if neighbor not in roots:
                dfs(root, neighbor, [root, neighbor], rate, 1)

    # Sort by return % descending, deduplicate similar routes
    routes.sort(key=lambda r: r.return_pct, reverse=True)

    # Deduplicate: keep only the best route for each set of currencies
    seen: set[frozenset[str]] = set()
    unique_routes: list[MultiHopRoute] = []
    for route in routes:
        key = frozenset(route.path)
        if key not in seen:
            seen.add(key)
            unique_routes.append(route)

    return unique_routes[:10]  # top 10 routes


def compute_deltas(
    current: list[Opportunity],
    previous: list[Opportunity],
) -> list[Opportunity]:
    """
    Compare current opportunities with previous scan to compute margin deltas.
    Modifies current opportunities in-place and returns them.
    """
    prev_map = {opp.name: opp for opp in previous}

    for opp in current:
        prev = prev_map.get(opp.name)
        if prev:
            opp.margin_delta = round(opp.margin_pct - prev.margin_pct, 2)
            opp.is_new = False
        else:
            opp.margin_delta = None
            opp.is_new = True

    return current
