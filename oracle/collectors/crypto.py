"""
ORACLE Crypto Collector
=======================
Fetches real-time cryptocurrency data from:
  - CoinGecko v3 API  (prices, market caps, 24h/7d change, ranks)
  - alternative.me    (Fear & Greed Index)

Refresh interval: 30 seconds (configurable via REFRESH_INTERVAL_CRYPTO).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from loguru import logger

from oracle.config import get_settings
from oracle.models import (
    CoinData,
    CryptoState,
    FearGreedCategory,
    FearGreedData,
    MarketTrend,
)

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=2&format=json"
COINGECKO_MARKETS_URL = "{base}/coins/markets"


def _classify_fear_greed(value: int) -> FearGreedCategory:
    if value <= 20:
        return FearGreedCategory.EXTREME_FEAR
    elif value <= 40:
        return FearGreedCategory.FEAR
    elif value <= 60:
        return FearGreedCategory.NEUTRAL
    elif value <= 80:
        return FearGreedCategory.GREED
    return FearGreedCategory.EXTREME_GREED


def _infer_market_trend(coins: list[CoinData]) -> MarketTrend:
    """Simple majority-vote trend from 24h changes."""
    if not coins:
        return MarketTrend.NEUTRAL
    changes = [c.change_24h_pct for c in coins if c.change_24h_pct is not None]
    if not changes:
        return MarketTrend.NEUTRAL
    avg = sum(changes) / len(changes)
    positive_ratio = sum(1 for c in changes if c > 0) / len(changes)
    if avg > 3 and positive_ratio > 0.7:
        return MarketTrend.BULLISH
    elif avg < -3 and positive_ratio < 0.3:
        return MarketTrend.BEARISH
    elif max(abs(c) for c in changes) > 10:
        return MarketTrend.VOLATILE
    return MarketTrend.NEUTRAL


async def fetch_fear_greed(client: httpx.AsyncClient) -> Optional[FearGreedData]:
    """Fetch the Crypto Fear & Greed Index from alternative.me."""
    try:
        resp = await client.get(FEAR_GREED_URL, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        entries: list[dict] = data.get("data", [])
        if not entries:
            return None

        current = entries[0]
        val = int(current["value"])
        cat = _classify_fear_greed(val)

        prev_val: Optional[int] = None
        prev_cat: Optional[FearGreedCategory] = None
        if len(entries) > 1:
            prev_val = int(entries[1]["value"])
            prev_cat = _classify_fear_greed(prev_val)

        return FearGreedData(
            value=val,
            category=cat,
            previous_value=prev_val,
            previous_category=prev_cat,
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.warning(f"[crypto] Fear & Greed fetch failed: {exc}")
        return None


async def fetch_coingecko_markets(
    client: httpx.AsyncClient,
    top_n: int = 20,
) -> list[CoinData]:
    """Fetch top-N coins by market cap from CoinGecko /coins/markets."""
    settings = get_settings()
    url = COINGECKO_MARKETS_URL.format(base=settings.coingecko_base_url)

    params: dict[str, Any] = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": top_n,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h,7d",
    }

    try:
        resp = await client.get(
            url,
            params=params,
            headers=settings.coingecko_headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        raw: list[dict] = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(f"[crypto] CoinGecko HTTP {exc.response.status_code}: {exc}")
        return []
    except Exception as exc:
        logger.error(f"[crypto] CoinGecko fetch failed: {exc}")
        return []

    coins: list[CoinData] = []
    for item in raw:
        try:
            coins.append(
                CoinData(
                    id=item["id"],
                    symbol=item["symbol"],
                    name=item["name"],
                    price_usd=float(item["current_price"] or 0),
                    change_24h_pct=item.get("price_change_percentage_24h"),
                    change_7d_pct=item.get("price_change_percentage_7d_in_currency"),
                    market_cap_usd=item.get("market_cap"),
                    volume_24h_usd=item.get("total_volume"),
                    rank=item.get("market_cap_rank"),
                    ath_usd=item.get("ath"),
                    ath_change_pct=item.get("ath_change_percentage"),
                )
            )
        except Exception as exc:
            logger.warning(f"[crypto] Skipping coin {item.get('id')}: {exc}")

    return coins


async def collect_crypto() -> CryptoState:
    """
    Main entry point — returns a fully populated CryptoState.
    Runs both fetches concurrently via a shared httpx.AsyncClient.
    """
    import asyncio

    async with httpx.AsyncClient() as client:
        settings = get_settings()
        coins_task = asyncio.create_task(
            fetch_coingecko_markets(client, top_n=settings.crypto_top_n)
        )
        fg_task = asyncio.create_task(fetch_fear_greed(client))
        coins, fear_greed = await asyncio.gather(coins_task, fg_task)

    # Derive totals
    total_market_cap: Optional[float] = None
    total_volume: Optional[float] = None
    btc_dominance: Optional[float] = None

    if coins:
        total_market_cap = sum(c.market_cap_usd for c in coins if c.market_cap_usd)
        total_volume = sum(c.volume_24h_usd for c in coins if c.volume_24h_usd)
        btc_data = next((c for c in coins if c.symbol.lower() == "btc"), None)
        if btc_data and btc_data.market_cap_usd and total_market_cap:
            btc_dominance = round(btc_data.market_cap_usd / total_market_cap * 100, 2)

    # Top gainers / losers
    sorted_by_change = sorted(
        [c for c in coins if c.change_24h_pct is not None],
        key=lambda c: c.change_24h_pct,  # type: ignore[arg-type]
        reverse=True,
    )
    top_gainers = [c.symbol.upper() for c in sorted_by_change[:3]]
    top_losers = [c.symbol.upper() for c in sorted_by_change[-3:]]

    trend = _infer_market_trend(coins)

    logger.info(
        f"[crypto] Fetched {len(coins)} coins | "
        f"F&G: {fear_greed.value if fear_greed else 'N/A'} | "
        f"trend: {trend.value}"
    )

    return CryptoState(
        coins=coins,
        fear_greed=fear_greed,
        total_market_cap_usd=total_market_cap,
        total_volume_24h_usd=total_volume,
        btc_dominance_pct=btc_dominance,
        market_trend=trend,
        top_gainers=top_gainers,
        top_losers=top_losers,
    )
