"""
POEStick — Central Pricing and Trend Engine.
Tracks raw price history in SQLite and provides trend-aware valuation.
"""

from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict

# Database name (shared with history.py)
DB_PATH = "poestick_history.db"

def init_pricing_db(conn: sqlite3.Connection):
    """Ensure the price history table exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            item_name TEXT NOT NULL,
            price REAL NOT NULL,
            confidence REAL DEFAULT 0
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_name_ts ON price_history(item_name, timestamp);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_ts ON price_history(timestamp);")
    conn.commit()

def record_prices(conn: sqlite3.Connection, price_map: Dict[str, float], confidence_map: Optional[Dict[str, float]] = None):
    """
    Log a fresh snapshot of prices. 
    Expects price_map: { 'Item Name': PriceInChaos }
    """
    ts = datetime.now()
    records = []
    for name, price in price_map.items():
        conf = confidence_map.get(name, 0.0) if confidence_map else 0.0
        records.append((ts, name, price, conf))
        
    conn.executemany(
        "INSERT INTO price_history (timestamp, item_name, price, confidence) VALUES (?, ?, ?, ?)",
        records
    )
    conn.commit()

def get_4h_trend(conn: sqlite3.Connection, item_name: str, current_price: float) -> float:
    """
    Returns the percentage change from 4 hours ago.
    Formula: ((current - historical) / historical) * 100
    """
    four_hours_ago = (datetime.now() - timedelta(hours=4)).isoformat()
    
    # Get the oldest price within the last 4 hours (closest to the start of the window)
    row = conn.execute("""
        SELECT price FROM price_history 
        WHERE item_name = ? AND timestamp >= ? 
        ORDER BY timestamp ASC LIMIT 1
    """, (item_name, four_hours_ago)).fetchone()
    
    if not row:
        return 0.0
        
    hist_price = row[0]
    if hist_price <= 0:
        return 0.0
        
    return ((current_price - hist_price) / hist_price) * 100

def get_safe_price(conn: sqlite3.Connection, item_name: str, current_price: float) -> float:
    """
    Returns a 'trend-conservative' price.
    - If trending DOWN: Use the current price (worst case for reward).
    - If trending UP: Use the 4h-old price (conservative floor).
    - If no trend: Use current.
    """
    trend = get_4h_trend(conn, item_name, current_price)
    
    # If the item is mooning, don't FOMO the profit calculation.
    # Use the price from 4 hours ago to be safe.
    if trend > 2.0: # Significant upswing
         four_hours_ago = (datetime.now() - timedelta(hours=4)).isoformat()
         row = conn.execute("""
            SELECT price FROM price_history 
            WHERE item_name = ? AND timestamp >= ? 
            ORDER BY timestamp ASC LIMIT 1
         """, (item_name, four_hours_ago)).fetchone()
         if row:
             return row[0]
             
    return current_price

def cleanup_price_history(conn: sqlite3.Connection, days: int = 3):
    """Vacuum old records to keep the DB snappy."""
    conn.execute("DELETE FROM price_history WHERE timestamp < datetime('now', ?)", (f"-{days} days",))
    conn.commit()
