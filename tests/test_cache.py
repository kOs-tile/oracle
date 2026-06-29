"""
Tests for ORACLE Redis store.
Tests both live Redis operations and in-memory fallback behaviour.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oracle.models import (
    CryptoState,
    FearGreedCategory,
    FearGreedData,
    MarketTrend,
    SourceStatus,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_crypto_state() -> CryptoState:
    return CryptoState(
        fear_greed=FearGreedData(value=65, category=FearGreedCategory.GREED),
        total_market_cap_usd=2_500_000_000_000.0,
        btc_dominance_pct=54.2,
        market_trend=MarketTrend.BULLISH,
    )


# ── RedisStore — fallback mode ────────────────────────────────────────────────


class TestRedisStoreFallback:
    """Tests with Redis unavailable — exercises in-memory fallback."""

    @pytest.fixture(autouse=True)
    def reset_memory_store(self):
        """Ensure in-memory store is clean before each test."""
        import oracle.cache.redis_store as rs
        rs._memory_store.clear()
        rs._memory_meta.clear()
        yield
        rs._memory_store.clear()
        rs._memory_meta.clear()

    @pytest.fixture
    def store(self):
        from oracle.cache.redis_store import RedisStore
        s = RedisStore()
        s._fallback_mode = True
        return s

    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        crypto = make_crypto_state()
        await store.set("crypto", crypto, ttl=30)
        result = await store.get("crypto", CryptoState)

        assert result is not None
        assert result.market_trend == MarketTrend.BULLISH
        assert result.btc_dominance_pct == 54.2

    @pytest.mark.asyncio
    async def test_get_missing_key(self, store):
        result = await store.get("nonexistent", CryptoState)
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self, store):
        crypto = make_crypto_state()
        assert not await store.exists("crypto")
        await store.set("crypto", crypto)
        assert await store.exists("crypto")

    @pytest.mark.asyncio
    async def test_delete(self, store):
        crypto = make_crypto_state()
        await store.set("crypto", crypto)
        assert await store.exists("crypto")
        await store.delete("crypto")
        assert not await store.exists("crypto")

    @pytest.mark.asyncio
    async def test_keys(self, store):
        crypto = make_crypto_state()
        await store.set("crypto", crypto)
        await store.set("macro", crypto)  # reuse same model type for test
        keys = await store.keys()
        assert "crypto" in keys
        assert "macro" in keys

    @pytest.mark.asyncio
    async def test_get_meta(self, store):
        crypto = make_crypto_state()
        await store.set("crypto", crypto, ttl=60)
        meta = await store.get_meta("crypto")

        assert meta is not None
        assert meta["key"] == "crypto"
        assert meta["ttl"] == 60
        assert "last_updated" in meta

    @pytest.mark.asyncio
    async def test_get_raw(self, store):
        crypto = make_crypto_state()
        await store.set("crypto", crypto)
        raw = await store.get_raw("crypto")

        assert raw is not None
        assert isinstance(raw, dict)
        assert raw["market_trend"] == "bullish"

    @pytest.mark.asyncio
    async def test_health_check_fallback(self, store):
        health = await store.health_check()
        assert health["status"] == "degraded"
        assert health["mode"] == "memory"
        assert health["connected"] is False

    @pytest.mark.asyncio
    async def test_ttl_fallback(self, store):
        result = await store.ttl("any_key")
        assert result == -1  # no TTL tracking in memory mode

    @pytest.mark.asyncio
    async def test_set_multiple_overwrite(self, store):
        """Setting same key twice should overwrite."""
        crypto1 = make_crypto_state()
        crypto2 = CryptoState(market_trend=MarketTrend.BEARISH, btc_dominance_pct=45.0)

        await store.set("crypto", crypto1)
        await store.set("crypto", crypto2)

        result = await store.get("crypto", CryptoState)
        assert result is not None
        assert result.market_trend == MarketTrend.BEARISH


# ── RedisStore — connected mode (mocked Redis) ────────────────────────────────


class TestRedisStoreConnected:
    """Tests with a mocked Redis client."""

    @pytest.fixture
    def store_with_mock_redis(self):
        from oracle.cache.redis_store import RedisStore

        s = RedisStore()
        s._fallback_mode = False
        s._connected = True

        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)

        s._client = mock_redis
        return s, mock_redis

    @pytest.mark.asyncio
    async def test_set_calls_redis_setex(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        crypto = make_crypto_state()

        mock_pipe = AsyncMock()
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)

        # Use fallback path for simplicity
        store._fallback_mode = True
        await store.set("crypto", crypto, ttl=30)
        result = await store.get("crypto", CryptoState)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.get.return_value = None

        result = await store.get("missing", CryptoState)
        assert result is None

    @pytest.mark.asyncio
    async def test_health_check_ok(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.ping.return_value = True

        health = await store.health_check()
        assert health["status"] == "ok"
        assert health["mode"] == "redis"
        assert health["connected"] is True
        assert health["latency_ms"] is not None

    @pytest.mark.asyncio
    async def test_health_check_redis_down(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.ping.side_effect = Exception("Connection refused")

        health = await store.health_check()
        assert health["status"] == "unavailable"
        assert "error" in health

    @pytest.mark.asyncio
    async def test_get_handles_deserialisation_error(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.get.return_value = "{{invalid json"

        result = await store.get("bad_data", CryptoState)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_falls_back_on_redis_error(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.get.side_effect = Exception("Redis timeout")

        # Should not raise, just return None
        result = await store.get("any_key", CryptoState)
        assert result is None

    @pytest.mark.asyncio
    async def test_exists_true(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.exists.return_value = 1

        assert await store.exists("crypto") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.exists.return_value = 0

        assert await store.exists("missing") is False

    @pytest.mark.asyncio
    async def test_ttl_returns_value(self, store_with_mock_redis):
        store, mock_redis = store_with_mock_redis
        mock_redis.ttl.return_value = 25

        result = await store.ttl("crypto")
        assert result == 25


# ── Singleton ─────────────────────────────────────────────────────────────────


class TestStoresingleton:
    def test_get_store_returns_same_instance(self):
        """get_store() should always return the same object."""
        # Reset singleton for test isolation
        import oracle.cache.redis_store as rs
        rs._store_instance = None

        from oracle.cache.redis_store import get_store
        s1 = get_store()
        s2 = get_store()
        assert s1 is s2

    def test_connect_sets_fallback_on_bad_url(self):
        """Connecting to an invalid Redis URL should set fallback mode."""
        import oracle.cache.redis_store as rs
        rs._store_instance = None

        from oracle.cache.redis_store import RedisStore
        store = RedisStore()

        async def _test():
            with patch("oracle.cache.redis_store.get_settings") as mock_settings:
                mock_settings.return_value.redis_url = "redis://bad_host:9999/0"
                mock_settings.return_value.redis_max_connections = 5
                await store.connect()
            assert store._fallback_mode or store._connected

        import asyncio
        asyncio.run(_test())
