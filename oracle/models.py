"""
ORACLE Pydantic v2 data models.

All domain models are strict, well-typed, and JSON-serialisable.
The top-level WorldState aggregates every domain into a single payload
that can be injected directly into Hermes agent prompts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_serializer


# ── Helpers ───────────────────────────────────────────────────────────────────


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────


class SourceStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    STALE = "stale"
    ERROR = "error"
    PENDING = "pending"


class DataProvenance(str, Enum):
    """Truth status for an individual observation supplied to an agent."""

    REAL = "real"
    CACHED = "cached"
    STALE = "stale"
    SIMULATED = "simulated"
    UNAVAILABLE = "unavailable"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class FearGreedCategory(str, Enum):
    EXTREME_FEAR = "Extreme Fear"
    FEAR = "Fear"
    NEUTRAL = "Neutral"
    GREED = "Greed"
    EXTREME_GREED = "Extreme Greed"


class MarketTrend(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    VOLATILE = "volatile"


# ── Source Health ─────────────────────────────────────────────────────────────


class SourceHealth(BaseModel):
    """Tracks operational health of an individual data-source collector."""

    source: str
    status: SourceStatus = SourceStatus.PENDING
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    total_fetches: int = 0
    total_errors: int = 0
    avg_latency_ms: Optional[float] = None
    last_error_message: Optional[str] = None

    @field_serializer("last_success", "last_failure")
    def serialise_dt(self, dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None

    @property
    def uptime_pct(self) -> float:
        if self.total_fetches == 0:
            return 0.0
        return round((1 - self.total_errors / self.total_fetches) * 100, 2)


# ── Crypto Domain ─────────────────────────────────────────────────────────────


class CoinData(BaseModel):
    """Price + metadata for a single cryptocurrency."""

    id: str = Field(description="CoinGecko coin ID, e.g. 'bitcoin'")
    symbol: str = Field(description="Ticker symbol, e.g. 'btc'")
    name: str
    price_usd: float
    change_24h_pct: Optional[float] = None
    change_7d_pct: Optional[float] = None
    market_cap_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    rank: Optional[int] = None
    ath_usd: Optional[float] = None
    ath_change_pct: Optional[float] = None


class FearGreedData(BaseModel):
    """Crypto Fear & Greed Index snapshot."""

    value: int = Field(ge=0, le=100)
    category: FearGreedCategory
    previous_value: Optional[int] = None
    previous_category: Optional[FearGreedCategory] = None
    timestamp: datetime = Field(default_factory=utc_now)

    @field_serializer("timestamp")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()


class CryptoState(BaseModel):
    """Full crypto domain snapshot."""

    coins: list[CoinData] = Field(default_factory=list)
    fear_greed: Optional[FearGreedData] = None
    total_market_cap_usd: Optional[float] = None
    total_volume_24h_usd: Optional[float] = None
    btc_dominance_pct: Optional[float] = None
    market_trend: MarketTrend = MarketTrend.NEUTRAL
    top_gainers: list[str] = Field(default_factory=list, description="Coin symbols")
    top_losers: list[str] = Field(default_factory=list, description="Coin symbols")
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("updated_at")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()

    def get_coin(self, symbol: str) -> Optional[CoinData]:
        symbol = symbol.lower()
        return next((c for c in self.coins if c.symbol.lower() == symbol), None)


# ── Macro Domain ──────────────────────────────────────────────────────────────


class TickerData(BaseModel):
    """Single equity / ETF / index snapshot."""

    symbol: str
    name: Optional[str] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    change_abs: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("updated_at")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()


class MacroState(BaseModel):
    """Macro-economic and equity market snapshot."""

    stocks: dict[str, TickerData] = Field(default_factory=dict)
    macro: dict[str, TickerData] = Field(
        default_factory=dict,
        description="DXY, VIX etc.",
    )
    crypto_yf: dict[str, TickerData] = Field(
        default_factory=dict,
        description="BTC, ETH, SOL via yfinance",
    )
    market_open: bool = False
    spy_trend: MarketTrend = MarketTrend.NEUTRAL
    risk_sentiment: str = Field(
        default="neutral",
        description="'risk-on', 'risk-off', 'neutral'",
    )
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("updated_at")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()


# ── News Domain ───────────────────────────────────────────────────────────────


class NewsItem(BaseModel):
    """Single news article or headline."""

    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None
    sentiment: Sentiment = Sentiment.NEUTRAL
    categories: list[str] = Field(default_factory=list)
    currencies: list[str] = Field(
        default_factory=list,
        description="Related crypto symbols",
    )
    summary: Optional[str] = None
    kind: str = Field(default="news", description="'news' or 'media'")

    @field_serializer("published_at")
    def serialise_dt(self, dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt else None


class NewsState(BaseModel):
    """Aggregated news headlines snapshot."""

    crypto_headlines: list[NewsItem] = Field(default_factory=list)
    general_headlines: list[NewsItem] = Field(default_factory=list)
    trending_topics: list[str] = Field(default_factory=list)
    dominant_sentiment: Sentiment = Sentiment.NEUTRAL
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("updated_at")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()


# ── On-Chain Domain ───────────────────────────────────────────────────────────


class GasPrices(BaseModel):
    """Ethereum gas prices in Gwei."""

    slow: float = Field(description="Safe/low priority gas price (Gwei)")
    standard: float = Field(description="Standard gas price (Gwei)")
    fast: float = Field(description="Fast gas price (Gwei)")
    base_fee: Optional[float] = None
    suggest_base_fee: Optional[float] = None


class OnChainState(BaseModel):
    """Ethereum on-chain metrics snapshot."""

    gas: Optional[GasPrices] = None
    eth_price_usd: Optional[float] = None
    mempool_size_estimate: Optional[int] = Field(
        default=None,
        description="Estimated pending transactions",
    )
    network_congestion: str = Field(
        default="unknown",
        description="'low', 'moderate', 'high', 'congested'",
    )
    last_block: Optional[int] = None
    provenance: dict[str, DataProvenance] = Field(
        default_factory=lambda: {
            "gas": DataProvenance.UNAVAILABLE,
            "last_block": DataProvenance.UNAVAILABLE,
            "mempool_size_estimate": DataProvenance.UNAVAILABLE,
        },
        description="Per-field truth status. Agent consumers must not treat simulated values as observations.",
    )
    provenance_note: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_serializer("updated_at")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()

    def congestion_label(self) -> str:
        if self.gas is None:
            return "unknown"
        fast = self.gas.fast
        if fast < 20:
            return "low"
        elif fast < 50:
            return "moderate"
        elif fast < 100:
            return "high"
        return "congested"


# ── Aggregated World State ────────────────────────────────────────────────────


class WorldState(BaseModel):
    """
    Top-level aggregated world state returned by GET /state.

    This is the primary payload injected into Hermes agent context.
    """

    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=utc_now)

    crypto: Optional[CryptoState] = None
    macro: Optional[MacroState] = None
    news: Optional[NewsState] = None
    onchain: Optional[OnChainState] = None

    source_health: dict[str, SourceHealth] = Field(default_factory=dict)

    # ── Derived summary fields ─────────────────────────────────────────────
    overall_market_mood: str = Field(
        default="unknown",
        description="Human-readable mood: 'euphoric', 'bullish', 'neutral', 'bearish', 'panic'",
    )
    key_signals: list[str] = Field(
        default_factory=list,
        description="Top 5 actionable signals for Hermes",
    )
    data_freshness_pct: float = Field(
        default=0.0,
        description="Percentage of sources that are fresh (status=ok)",
    )

    @field_serializer("generated_at")
    def serialise_dt(self, dt: datetime) -> str:
        return dt.isoformat()

    def compute_summary(self) -> None:
        """Derive overall_market_mood and key_signals from domain data."""
        signals: list[str] = []

        # Fear & Greed mood
        if self.crypto and self.crypto.fear_greed:
            fg = self.crypto.fear_greed
            cat = fg.category.value
            signals.append(f"Fear & Greed: {fg.value}/100 ({cat})")
            if fg.value <= 20:
                self.overall_market_mood = "panic"
            elif fg.value <= 40:
                self.overall_market_mood = "bearish"
            elif fg.value <= 60:
                self.overall_market_mood = "neutral"
            elif fg.value <= 80:
                self.overall_market_mood = "bullish"
            else:
                self.overall_market_mood = "euphoric"

        # BTC signal
        if self.crypto:
            btc = self.crypto.get_coin("btc")
            if btc and btc.change_24h_pct is not None:
                direction = "▲" if btc.change_24h_pct >= 0 else "▼"
                signals.append(
                    f"BTC {direction}{abs(btc.change_24h_pct):.2f}% 24h "
                    f"@ ${btc.price_usd:,.0f}"
                )

        # VIX signal
        if self.macro and "^VIX" in self.macro.macro:
            vix = self.macro.macro["^VIX"]
            if vix.price:
                label = "elevated" if vix.price > 20 else "low"
                signals.append(f"VIX {vix.price:.1f} ({label} volatility)")

        # Gas signal
        if self.onchain and self.onchain.gas:
            signals.append(
                f"ETH gas: {self.onchain.gas.fast:.0f} gwei (fast) — "
                f"{self.onchain.network_congestion} congestion"
            )

        # News sentiment signal
        if self.news:
            total = (
                self.news.positive_count
                + self.news.negative_count
                + self.news.neutral_count
            )
            if total > 0:
                pos_pct = round(self.news.positive_count / total * 100)
                neg_pct = round(self.news.negative_count / total * 100)
                signals.append(
                    f"News sentiment: {pos_pct}% positive, {neg_pct}% negative "
                    f"across {total} headlines"
                )

        self.key_signals = signals[:5]

        # Data freshness
        health_values = list(self.source_health.values())
        if health_values:
            ok_count = sum(1 for h in health_values if h.status == SourceStatus.OK)
            self.data_freshness_pct = round(ok_count / len(health_values) * 100, 1)
