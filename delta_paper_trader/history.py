"""Fetch historical candles from Delta Exchange API"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from delta_paper_trader.models import Candle


async def fetch_historical_candles(
    symbol: str,
    resolution: str = "1",  # 1 minute candles
    limit: int = 100,
) -> list[Candle]:
    """
    Fetch historical candles from Delta Exchange API.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSD", "ETHUSD")
        resolution: Candle resolution in minutes (default "1" for 1-minute)
        limit: Number of candles to fetch (default 100)
    
    Returns:
        List of Candle objects sorted by timestamp (oldest first)
    """
    # Calculate time range (fetch last `limit` minutes)
    now = int(time.time())
    from_ts = now - (limit * int(resolution) * 60)
    to_ts = now
    
    url = "https://cdn.india.deltaex.org/v2/chart/history"
    
    # Format symbol for the API (add MARK: prefix for mark prices)
    api_symbol = f"MARK:{symbol}" if ":" not in symbol else symbol
    
    params = {
        "symbol": api_symbol,
        "resolution": resolution,
        "from": from_ts,
        "to": to_ts,
        "cache_ttl": "1m",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise ValueError(f"Failed to fetch candles for {symbol}: {str(exc)}") from exc
    
    if data.get("s") != "ok":
        raise ValueError(f"API returned error for {symbol}: {data.get('s')}")
    
    # Parse the API response
    timestamps = data.get("t", [])  # Unix timestamps
    opens = data.get("o", [])
    closes = data.get("c", [])
    highs = data.get("h", [])
    lows = data.get("l", [])
    volumes = data.get("v", [])
    
    if not timestamps:
        return []
    
    # Build candles
    candles = []
    for i, ts in enumerate(timestamps):
        if i >= len(opens) or i >= len(closes) or i >= len(highs) or i >= len(lows):
            break
        
        # Convert Unix timestamp to ISO format
        from datetime import datetime, timezone
        candle_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        
        candle = Candle(
            symbol=symbol,
            start=candle_time,
            open=Decimal(str(opens[i])),
            high=Decimal(str(highs[i])),
            low=Decimal(str(lows[i])),
            close=Decimal(str(closes[i])),
            volume=Decimal(str(volumes[i] if i < len(volumes) else 0)),
        )
        candles.append(candle)
    
    return candles
