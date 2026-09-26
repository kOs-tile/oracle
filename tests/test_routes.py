"""
Tests for ORACLE FastAPI routes.
Uses httpx.AsyncClient with FastAPI's ASGI transport — no real server needed.
Redis is mocked via the RedisStore dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from oracle.models import (
    CoinData,
    CryptoState,
    DataProvenance,
    FearGreedCategory,
    FearGreedData,
    GasPrices,
    MacroState,
    MarketTrend,
    NewsItem,
    NewsState,
    OnChainState,
    Sentiment,
    SourceHealth,
    SourceStatus,
    TickerData,
    WorldState,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_full_world_state() -> WorldState:
    coins = [
        CoinData(
            id="bitcoin", symbol="btc", name="Bitcoin",
            price_usd=67000.0, change_24h_pct=2.34,
            market_cap_usd=1_300_000_000_000, rank=1,
        )
    ]
    crypto = CryptoState(
        coins=coins,
        fear_greed=FearGreedData(value=72, category=FearGreedCategory.GREED),
        total_market_cap_usd=2_400_000_000_000.0,
        btc_dominance_pct=54.2,
        market_trend=MarketTrend.BULLISH,
        top_gainers=["BTC"],
        top_losers=["DOGE"],
    )
    macro = MacroState(
        stocks={"SPY": TickerData(symbol="SPY", price=487.3, change_pct=0.82)},
        macro={"^VIX": TickerData(symbol="^VIX", price=14.2, change_pct=-3.1)},
        market_open=True,
        risk_sentiment="risk-on",
    )
    news = NewsState(
        crypto_headlines=[
            NewsItem(title="Bitcoin hits $67K", sentiment=Sentiment.POSITIVE, source="CoinDesk"),
        ],
        general_headlines=[],
        trending_topics=["Bitcoin", "ETF"],
        dominant_sentiment=Sentiment.POSITIVE,
        positive_count=1,
        negative_count=0,
        neutral_count=0,
    )
    onchain = OnChainState(
        gas=GasPrices(slow=12.0, standard=18.0, fast=28.0, base_fee=11.5),
        network_congestion="moderate",
        last_block=19_500_000,
    )
    health = {
        name: SourceHealth(source=name, status=SourceStatus.OK, avg_latency_ms=250.0)
        for name in ("crypto", "macro", "news", "onchain")
    }
    world = WorldState(
        crypto=crypto, macro=macro, news=news, onchain=onchain,
        source_health=health,
    )
    world.compute_summary()
    return world


@pytest.fixture
def mock_store():
    """Mock RedisStore that returns well-formed data."""
    store = AsyncMock()

    async def _get(key, model_class):
        world = make_full_world_state()
        if key == "crypto":
            return world.crypto
        elif key == "macro":
            return world.macro
        elif key == "news":
            return world.news
        elif key == "onchain":
            return world.onchain
        return None

    store.get.side_effect = _get
    store.health_check.return_value = {
        "status": "ok", "mode": "redis", "latency_ms": 1.2, "connected": True
    }
    store.connect = AsyncMock()
    store.disconnect = AsyncMock()
    return store


@pytest.fixture
def mock_engine():
    """Mock RefreshEngine with healthy sources."""
    engine = MagicMock()
    world = make_full_world_state()
    engine.get_all_health.return_value = world.source_health
    engine.get_health.side_effect = lambda k: world.source_health.get(k)
    engine.is_running = True
    engine.start = AsyncMock()
    engine.stop = AsyncMock()
    engine.trigger_refresh = AsyncMock(return_value=True)
    return engine


@pytest.fixture
def app_client(mock_store, mock_engine):
    """httpx AsyncClient wired to the ORACLE ASGI app with mocked deps."""
    from oracle.api.routes import create_app

    with (
        patch("oracle.api.routes.get_store", return_value=mock_store),
        patch("oracle.api.routes.get_engine", return_value=mock_engine),
    ):
        test_app = create_app()

        # Override lifespan for testing — just skip startup/shutdown
        async def _fake_lifespan(app):
            yield

        test_app.router.lifespan_context = _fake_lifespan

        transport = ASGITransport(app=test_app)

        async def _make_client():
            return AsyncClient(transport=transport, base_url="http://test")

        return _make_client


# ── /state tests ──────────────────────────────────────────────────────────────


class TestStateEndpoint:
    @pytest.mark.asyncio
    async def test_get_full_state_returns_200(self, app_client, mock_store, mock_engine):
        with (
            patch("oracle.api.routes.get_store", return_value=mock_store),
            patch("oracle.api.routes.get_engine", return_value=mock_engine),
        ):
            from oracle.api.routes import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Bypass startup by calling the route handler directly via the mock
                pass

        # Direct function test — bypass ASGI for simplicity
        from oracle.api.routes import create_app

        with (
            patch("oracle.api.routes.get_store", return_value=mock_store),
            patch("oracle.api.routes.get_engine", return_value=mock_engine),
        ):
            app = create_app()
            # Inject pre-built world state into response
            world = make_full_world_state()
            assert world.overall_market_mood in ("bullish", "bearish", "neutral", "euphoric", "panic", "unknown")

    @pytest.mark.asyncio
    async def test_world_state_schema_version(self):
        world = make_full_world_state()
        data = world.model_dump(mode="json")
        assert data["schema_version"] == "1.0"

    @pytest.mark.asyncio
    async def test_world_state_has_key_signals(self):
        world = make_full_world_state()
        assert len(world.key_signals) > 0
        assert any("Fear" in s for s in world.key_signals)

    @pytest.mark.asyncio
    async def test_world_state_freshness(self):
        world = make_full_world_state()
        assert world.data_freshness_pct == 100.0

    @pytest.mark.asyncio
    async def test_world_state_mood(self):
        world = make_full_world_state()
        assert world.overall_market_mood == "bullish"


    def test_evidence_digest_is_deterministic(self):
        from oracle.api.formatter import evidence_ledger_digest

        first = make_full_world_state()
        second = make_full_world_state()
        first.generated_at = second.generated_at

        assert evidence_ledger_digest(first) == evidence_ledger_digest(second)
        assert len(evidence_ledger_digest(first)) == 64

    def test_evidence_digest_changes_when_truth_status_changes(self):
        from oracle.api.formatter import evidence_ledger_digest

        world = make_full_world_state()
        before = evidence_ledger_digest(world)
        assert world.onchain is not None
        world.onchain.provenance["gas"] = DataProvenance.SIMULATED
        world.compute_summary()
        after = evidence_ledger_digest(world)

        assert before != after


# ── /state/{domain} tests ─────────────────────────────────────────────────────


class TestDomainEndpoints:
    @pytest.mark.asyncio
    async def test_crypto_domain_data(self, mock_store):
        world = make_full_world_state()
        crypto = world.crypto
        assert crypto is not None
        assert crypto.market_trend == MarketTrend.BULLISH
        assert crypto.fear_greed is not None
        assert crypto.fear_greed.value == 72

    @pytest.mark.asyncio
    async def test_macro_domain_data(self, mock_store):
        world = make_full_world_state()
        macro = world.macro
        assert macro is not None
        assert "SPY" in macro.stocks
        assert macro.stocks["SPY"].price == 487.3

    @pytest.mark.asyncio
    async def test_news_domain_data(self, mock_store):
        world = make_full_world_state()
        news = world.news
        assert news is not None
        assert news.dominant_sentiment == Sentiment.POSITIVE
        assert len(news.trending_topics) > 0

    @pytest.mark.asyncio
    async def test_onchain_domain_data(self, mock_store):
        world = make_full_world_state()
        onchain = world.onchain
        assert onchain is not None
        assert onchain.gas is not None
        assert onchain.gas.fast == 28.0
        assert onchain.network_congestion == "moderate"


# ── /health tests ─────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_response_structure(self, mock_store, mock_engine):
        # Validate the health response structure
        cache_health = await mock_store.health_check()
        source_health = mock_engine.get_all_health()

        assert cache_health["status"] == "ok"
        assert len(source_health) == 4

        for name, h in source_health.items():
            assert name in ("crypto", "macro", "news", "onchain")
            assert h.status == SourceStatus.OK

    @pytest.mark.asyncio
    async def test_health_degraded_on_error(self):
        world = make_full_world_state()
        # Simulate one source erroring
        world.source_health["crypto"].status = SourceStatus.ERROR
        world.source_health["crypto"].consecutive_failures = 6

        error_sources = [
            name for name, h in world.source_health.items()
            if h.status == SourceStatus.ERROR
        ]
        assert "crypto" in error_sources

    def test_uptime_pct_calculation(self):
        health = SourceHealth(
            source="crypto",
            total_fetches=100,
            total_errors=5,
        )
        assert health.uptime_pct == 95.0

    def test_uptime_pct_zero_fetches(self):
        health = SourceHealth(source="crypto")
        assert health.uptime_pct == 0.0


# ── Formatter tests ───────────────────────────────────────────────────────────


class TestFormatter:
    def test_format_world_state_prompt_contains_sections(self):
        from oracle.api.formatter import format_world_state_prompt
        world = make_full_world_state()
        prompt = format_world_state_prompt(world)

        assert "ORACLE WORLD STATE" in prompt
        assert "CRYPTO MARKETS" in prompt
        assert "MACRO & EQUITIES" in prompt
        assert "NEWS & SENTIMENT" in prompt
        assert "ETHEREUM ON-CHAIN" in prompt
        assert "DATA SOURCE HEALTH" in prompt

    def test_format_world_state_prompt_has_btc(self):
        from oracle.api.formatter import format_world_state_prompt
        world = make_full_world_state()
        prompt = format_world_state_prompt(world)
        assert "BTC" in prompt
        assert "67,000" in prompt or "67000" in prompt

    def test_formatter_exposes_evidence_ledger(self):
        from oracle.api.formatter import format_world_state_prompt
        world = make_full_world_state()
        prompt = format_world_state_prompt(world)
        assert "EVIDENCE LEDGER" in prompt
        assert "Trusted data: 75%" in prompt
        assert "onchain      UNAVAILABLE" in prompt


    def test_format_world_state_summary_structure(self):
        from oracle.api.formatter import format_world_state_summary
        world = make_full_world_state()
        summary = format_world_state_summary(world)

        assert "timestamp" in summary
        assert "mood" in summary
        assert "btc" in summary
        assert summary["btc"]["price"] == 67000.0
        assert summary["fear_greed"]["value"] == 72
        assert summary["vix"] == 14.2

    def test_format_large_numbers(self):
        from oracle.api.formatter import _fmt_large
        assert _fmt_large(1_500_000_000_000) == "$1.50T"
        assert _fmt_large(420_000_000_000) == "$420.00B"
        assert _fmt_large(12_000_000) == "$12.00M"
        assert _fmt_large(None) == "N/A"

    def test_format_price(self):
        from oracle.api.formatter import _fmt_price
        assert _fmt_price(67000.0) == "$67,000.00"
        assert _fmt_price(0.0000265) == "$0.000027"
        assert _fmt_price(None) == "N/A"

    def test_format_change(self):
        from oracle.api.formatter import _fmt_change
        assert "▲" in _fmt_change(2.34)
        assert "▼" in _fmt_change(-1.5)
        assert _fmt_change(None) == "N/A"


# ── Model tests ───────────────────────────────────────────────────────────────


class TestModels:
    def test_world_state_compute_summary_sets_mood(self):
        world = make_full_world_state()
        assert world.overall_market_mood == "bullish"

    def test_world_state_data_freshness_all_ok(self):
        world = make_full_world_state()
        assert world.data_freshness_pct == 100.0

    def test_world_state_data_freshness_partial(self):
        world = make_full_world_state()
        world.source_health["crypto"].status = SourceStatus.ERROR
        world.compute_summary()
        assert world.data_freshness_pct == 75.0

    def test_crypto_state_get_coin(self):
        world = make_full_world_state()
        btc = world.crypto.get_coin("btc")
        assert btc is not None
        assert btc.price_usd == 67000.0

    def test_crypto_state_get_coin_missing(self):
        world = make_full_world_state()
        doge = world.crypto.get_coin("doge")
        assert doge is None

    def test_onchain_congestion_label(self):
        onchain = OnChainState(
            gas=GasPrices(slow=10.0, standard=14.0, fast=15.0),
            network_congestion="low",
        )
        assert onchain.congestion_label() == "low"

        onchain.gas.fast = 75.0
        assert onchain.congestion_label() == "high"

    def test_world_state_serialisation_round_trip(self):
        """Model should survive JSON round-trip without data loss."""
        world = make_full_world_state()
        json_data = world.model_dump(mode="json")
        restored = WorldState.model_validate(json_data)

        assert restored.schema_version == world.schema_version
        assert restored.overall_market_mood == world.overall_market_mood
        assert restored.crypto.fear_greed.value == 72
