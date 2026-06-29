"""
ORACLE Macro Collector
======================
Fetches equity, ETF, and macro indicator data via yfinance:
  - Stocks: SPY, NVDA, TSLA
  - Crypto (cross-reference): BTC-USD, ETH-USD, SOL-USD
  - Macro: DX-Y.NYB (DXY Dollar Index), ^VIX (Volatility Index)

Refresh interval: 15 minutes (configurable via REFRESH_INTERVAL_MACRO).

Note: yfinance is a synchronous library. We run it in a thread pool executor
to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from oracle.config import get_settings
from oracle.models import MacroState, MarketTrend, TickerData

_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="oracle-yf")

# DXY and VIX display labels
TICKER_LABELS: dict[str, str] = {
    "SPY": "SPDR S&P 500 ETF",
    "NVDA": "NVIDIA Corp",
    "TSLA": "Tesla Inc",
    "BTC-USD": "Bitcoin USD",
    "ETH-USD": "Ethereum USD",
    "SOL-USD": "Solana USD",
    "DX-Y.NYB": "US Dollar Index (DXY)",
    "^VIX": "CBOE Volatility Index",
}


def _fetch_tickers_sync(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """
    Synchronous yfinance fetch for a batch of symbols.
    Returns {symbol: info_dict}.
    """
    import yfinance as yf  # imported here to keep module load fast

    results: dict[str, dict[str, Any]] = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                ticker = tickers.tickers.get(sym)
                if ticker is None:
                    continue
                info = ticker.fast_info
                # fast_info returns a FastInfo object; access as attributes
                results[sym] = {
                    "price": getattr(info, "last_price", None),
                    "open": getattr(info, "open", None),
                    "high": getattr(info, "day_high", None),
                    "low": getattr(info, "day_low", None),
                    "volume": getattr(info, "three_month_average_volume", None),
                    "market_cap": getattr(info, "market_cap", None),
                    "week_52_high": getattr(info, "fifty_two_week_high", None),
                    "week_52_low": getattr(info, "fifty_two_week_low", None),
                    "previous_close": getattr(info, "previous_close", None),
                }
            except Exception as exc:
                logger.warning(f"[macro] yfinance inner error for {sym}: {exc}")
    except Exception as exc:
        logger.error(f"[macro] yfinance batch fetch failed: {exc}")

    return results


def _build_ticker_data(sym: str, raw: dict[str, Any]) -> TickerData:
    """Convert a raw yfinance fast_info dict into a TickerData model."""
    price = raw.get("price")
    prev_close = raw.get("previous_close")

    change_abs: Optional[float] = None
    change_pct: Optional[float] = None
    if price is not None and prev_close is not None and prev_close != 0:
        change_abs = round(price - prev_close, 4)
        change_pct = round((price - prev_close) / prev_close * 100, 4)

    return TickerData(
        symbol=sym,
        name=TICKER_LABELS.get(sym, sym),
        price=round(price, 4) if price is not None else None,
        change_pct=change_pct,
        change_abs=change_abs,
        open=raw.get("open"),
        high=raw.get("high"),
        low=raw.get("low"),
        volume=raw.get("volume"),
        market_cap=raw.get("market_cap"),
        week_52_high=raw.get("week_52_high"),
        week_52_low=raw.get("week_52_low"),
        updated_at=datetime.now(timezone.utc),
    )


def _infer_spy_trend(spy: Optional[TickerData]) -> MarketTrend:
    if spy is None or spy.change_pct is None:
        return MarketTrend.NEUTRAL
    if spy.change_pct > 1.0:
        return MarketTrend.BULLISH
    elif spy.change_pct < -1.0:
        return MarketTrend.BEARISH
    return MarketTrend.NEUTRAL


def _infer_risk_sentiment(
    vix: Optional[TickerData],
    spy: Optional[TickerData],
) -> str:
    """Derive 'risk-on' / 'risk-off' / 'neutral' from VIX + SPY."""
    vix_val = vix.price if vix and vix.price else None
    spy_chg = spy.change_pct if spy and spy.change_pct else None

    if vix_val is not None and vix_val > 30:
        return "risk-off"
    elif vix_val is not None and vix_val < 15 and (spy_chg or 0) > 0:
        return "risk-on"
    return "neutral"


async def collect_macro() -> MacroState:
    """
    Main entry point — returns a fully populated MacroState.
    Offloads synchronous yfinance calls to a thread pool.
    """
    settings = get_settings()

    all_symbols = settings.stock_tickers + settings.macro_tickers + settings.crypto_tickers
    loop = asyncio.get_event_loop()

    raw_data = await loop.run_in_executor(
        _thread_pool,
        _fetch_tickers_sync,
        all_symbols,
    )

    stocks: dict[str, TickerData] = {}
    macro_indicators: dict[str, TickerData] = {}
    crypto_yf: dict[str, TickerData] = {}

    for sym in settings.stock_tickers:
        if sym in raw_data:
            stocks[sym] = _build_ticker_data(sym, raw_data[sym])

    for sym in settings.macro_tickers:
        if sym in raw_data:
            macro_indicators[sym] = _build_ticker_data(sym, raw_data[sym])

    for sym in settings.crypto_tickers:
        if sym in raw_data:
            crypto_yf[sym] = _build_ticker_data(sym, raw_data[sym])

    spy = stocks.get("SPY")
    vix = macro_indicators.get("^VIX")
    spy_trend = _infer_spy_trend(spy)
    risk_sentiment = _infer_risk_sentiment(vix, spy)

    # Determine if US market is open (rough heuristic: volume > 0)
    market_open = bool(spy and spy.volume and spy.volume > 0)

    logger.info(
        f"[macro] Fetched {len(stocks)} stocks, {len(macro_indicators)} macro, "
        f"{len(crypto_yf)} crypto-yf | SPY trend: {spy_trend.value} | "
        f"risk: {risk_sentiment}"
    )

    return MacroState(
        stocks=stocks,
        macro=macro_indicators,
        crypto_yf=crypto_yf,
        market_open=market_open,
        spy_trend=spy_trend,
        risk_sentiment=risk_sentiment,
    )
