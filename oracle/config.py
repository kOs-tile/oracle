"""
ORACLE Configuration — Pydantic Settings with environment variable support.
All settings can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OracleSettings(BaseSettings):
    """Central configuration for ORACLE service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service ───────────────────────────────────────────────────────────────
    service_host: str = Field(default="0.0.0.0", description="FastAPI bind host")
    service_port: int = Field(default=8000, description="FastAPI bind port")
    log_level: str = Field(default="INFO", description="Loguru log level")
    environment: str = Field(default="development", description="deployment env")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    redis_max_connections: int = Field(default=20)
    default_ttl: int = Field(default=300, description="Default cache TTL in seconds")

    # ── External API Keys ─────────────────────────────────────────────────────
    coingecko_api_key: str = Field(
        default="",
        description="CoinGecko API key (optional — free tier works without)",
    )
    coingecko_base_url: str = Field(
        default="https://api.coingecko.com/api/v3",
        description="CoinGecko API base URL",
    )

    cryptopanic_api_key: str = Field(
        default="",
        description="CryptoPanic API key (get free at cryptopanic.com)",
    )

    newsapi_key: str = Field(
        default="",
        description="NewsAPI key (get free at newsapi.org)",
    )

    etherscan_api_key: str = Field(
        default="",
        description="Etherscan API key (get free at etherscan.io)",
    )

    # ── Refresh Intervals (seconds) ───────────────────────────────────────────
    refresh_interval_crypto: int = Field(
        default=30,
        description="Crypto prices + Fear & Greed refresh interval",
    )
    refresh_interval_macro: int = Field(
        default=900,
        description="Macro indicators (yfinance) refresh interval",
    )
    refresh_interval_news: int = Field(
        default=300,
        description="News headlines refresh interval",
    )
    refresh_interval_onchain: int = Field(
        default=60,
        description="On-chain gas prices refresh interval",
    )

    # ── WebSocket ─────────────────────────────────────────────────────────────
    ws_push_interval: int = Field(
        default=10,
        description="WebSocket /stream push interval in seconds",
    )

    # ── Tracked Tickers ───────────────────────────────────────────────────────
    crypto_top_n: int = Field(default=20, description="Top N coins to track")
    stock_tickers: list[str] = Field(
        default=["SPY", "NVDA", "TSLA"],
        description="Stock tickers to monitor",
    )
    macro_tickers: list[str] = Field(
        default=["DX-Y.NYB", "^VIX"],
        description="Macro tickers: DXY, VIX",
    )
    crypto_tickers: list[str] = Field(
        default=["BTC-USD", "ETH-USD", "SOL-USD"],
        description="Crypto tickers via yfinance for cross-reference",
    )

    # ── Health thresholds ─────────────────────────────────────────────────────
    max_consecutive_failures: int = Field(
        default=5,
        description="Mark source degraded after N consecutive failures",
    )
    stale_threshold_multiplier: float = Field(
        default=3.0,
        description="Mark source stale if age > interval * this multiplier",
    )

    @field_validator("log_level")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        return v.upper()

    @field_validator("environment")
    @classmethod
    def normalise_environment(cls, v: str) -> str:
        return v.lower()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def coingecko_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.coingecko_api_key:
            headers["x-cg-demo-api-key"] = self.coingecko_api_key
        return headers


@lru_cache(maxsize=1)
def get_settings() -> OracleSettings:
    """Return a cached singleton of OracleSettings."""
    return OracleSettings()
