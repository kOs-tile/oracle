"""
ORACLE Redis Store
==================
Async Redis client built on redis-py's async interface.

Responsibilities:
  - Serialise/deserialise Pydantic models to/from Redis JSON strings
  - Track last_updated timestamps per key
  - TTL management per domain
  - Health checking with latency measurement
  - Graceful degradation when Redis is unavailable (in-memory fallback)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel

try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis
    from redis.exceptions import RedisError
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.warning("redis package not available — using in-memory fallback store")

from oracle.config import get_settings

T = TypeVar("T", bound=BaseModel)

# Key namespacing
KEY_PREFIX = "oracle:"
HEALTH_KEY = f"{KEY_PREFIX}health"
META_SUFFIX = ":meta"

# In-memory fallback store (used when Redis is unavailable)
_memory_store: dict[str, str] = {}
_memory_meta: dict[str, dict] = {}


class RedisStore:
    """
    Async Redis store with transparent in-memory fallback.

    Usage:
        store = RedisStore()
        await store.connect()
        await store.set("crypto", crypto_state, ttl=30)
        state = await store.get("crypto", CryptoState)
    """

    def __init__(self) -> None:
        self._client: Optional["Redis"] = None
        self._connected: bool = False
        self._fallback_mode: bool = False

    async def connect(self) -> None:
        """Establish Redis connection; fall back to memory on failure."""
        if not HAS_REDIS:
            self._fallback_mode = True
            logger.warning("[cache] redis-py not installed — using in-memory store")
            return

        settings = get_settings()
        try:
            self._client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=settings.redis_max_connections,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            # Ping to verify connection
            await self._client.ping()
            self._connected = True
            logger.info(f"[cache] Connected to Redis at {settings.redis_url}")
        except Exception as exc:
            logger.warning(
                f"[cache] Redis connection failed ({exc}) — falling back to memory store"
            )
            self._fallback_mode = True
            self._connected = False

    async def disconnect(self) -> None:
        """Close Redis connection gracefully."""
        if self._client and self._connected:
            try:
                await self._client.aclose()
                logger.info("[cache] Redis connection closed")
            except Exception as exc:
                logger.warning(f"[cache] Error closing Redis: {exc}")
        self._connected = False

    # ── Core operations ───────────────────────────────────────────────────────

    async def set(
        self,
        key: str,
        model: BaseModel,
        ttl: Optional[int] = None,
    ) -> bool:
        """Serialise and store a Pydantic model. Returns True on success."""
        full_key = f"{KEY_PREFIX}{key}"
        payload = model.model_dump_json()
        settings = get_settings()
        effective_ttl = ttl or settings.default_ttl

        meta = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "ttl": effective_ttl,
            "key": key,
        }

        if self._fallback_mode:
            _memory_store[full_key] = payload
            _memory_meta[full_key] = meta
            return True

        try:
            pipe = self._client.pipeline()
            pipe.setex(full_key, effective_ttl, payload)
            pipe.setex(
                f"{full_key}{META_SUFFIX}",
                effective_ttl + 60,
                json.dumps(meta),
            )
            await pipe.execute()
            return True
        except Exception as exc:
            logger.error(f"[cache] SET {key} failed: {exc}")
            # Degrade to memory
            _memory_store[full_key] = payload
            _memory_meta[full_key] = meta
            return False

    async def get(
        self,
        key: str,
        model_class: Type[T],
    ) -> Optional[T]:
        """Retrieve and deserialise a stored model. Returns None if missing/expired."""
        full_key = f"{KEY_PREFIX}{key}"

        if self._fallback_mode:
            raw = _memory_store.get(full_key)
        else:
            try:
                raw = await self._client.get(full_key)
            except Exception as exc:
                logger.warning(f"[cache] GET {key} failed: {exc}")
                raw = _memory_store.get(full_key)

        if raw is None:
            return None

        try:
            return model_class.model_validate_json(raw)
        except Exception as exc:
            logger.error(f"[cache] Deserialisation error for {key}: {exc}")
            return None

    async def get_raw(self, key: str) -> Optional[dict]:
        """Get stored data as a raw dict (no Pydantic model needed)."""
        full_key = f"{KEY_PREFIX}{key}"

        if self._fallback_mode:
            raw = _memory_store.get(full_key)
        else:
            try:
                raw = await self._client.get(full_key)
            except Exception as exc:
                logger.warning(f"[cache] GET_RAW {key} failed: {exc}")
                raw = _memory_store.get(full_key)

        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def get_meta(self, key: str) -> Optional[dict]:
        """Retrieve metadata (last_updated, ttl) for a cached key."""
        full_key = f"{KEY_PREFIX}{key}"

        if self._fallback_mode:
            return _memory_meta.get(full_key)

        try:
            raw = await self._client.get(f"{full_key}{META_SUFFIX}")
            return json.loads(raw) if raw else None
        except Exception:
            return _memory_meta.get(full_key)

    async def delete(self, key: str) -> bool:
        """Delete a cached key."""
        full_key = f"{KEY_PREFIX}{key}"
        if self._fallback_mode:
            _memory_store.pop(full_key, None)
            _memory_meta.pop(full_key, None)
            return True
        try:
            await self._client.delete(full_key, f"{full_key}{META_SUFFIX}")
            return True
        except Exception as exc:
            logger.warning(f"[cache] DELETE {key} failed: {exc}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        full_key = f"{KEY_PREFIX}{key}"
        if self._fallback_mode:
            return full_key in _memory_store
        try:
            return bool(await self._client.exists(full_key))
        except Exception:
            return full_key in _memory_store

    async def ttl(self, key: str) -> int:
        """Return remaining TTL in seconds (-2 = not found, -1 = no expiry)."""
        full_key = f"{KEY_PREFIX}{key}"
        if self._fallback_mode:
            return -1
        try:
            return await self._client.ttl(full_key)
        except Exception:
            return -2

    async def keys(self, pattern: str = "*") -> list[str]:
        """Return all matching keys (strips the KEY_PREFIX)."""
        full_pattern = f"{KEY_PREFIX}{pattern}"
        if self._fallback_mode:
            return [
                k[len(KEY_PREFIX):]
                for k in _memory_store.keys()
                if k.startswith(KEY_PREFIX) and not k.endswith(META_SUFFIX)
            ]
        try:
            raw_keys = await self._client.keys(full_pattern)
            return [
                k[len(KEY_PREFIX):]
                for k in raw_keys
                if not k.endswith(META_SUFFIX)
            ]
        except Exception:
            return []

    # ── Health check ──────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """
        Returns a health dict:
        {
            "status": "ok" | "degraded" | "unavailable",
            "mode": "redis" | "memory",
            "latency_ms": float | None,
            "connected": bool,
        }
        """
        if self._fallback_mode:
            return {
                "status": "degraded",
                "mode": "memory",
                "latency_ms": None,
                "connected": False,
                "keys_in_memory": len(_memory_store),
            }

        t0 = time.monotonic()
        try:
            await self._client.ping()
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {
                "status": "ok",
                "mode": "redis",
                "latency_ms": latency_ms,
                "connected": True,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "mode": "redis",
                "latency_ms": None,
                "connected": False,
                "error": str(exc),
            }

    @property
    def is_connected(self) -> bool:
        return self._connected or self._fallback_mode


# ── Singleton ─────────────────────────────────────────────────────────────────

_store_instance: Optional[RedisStore] = None


def get_store() -> RedisStore:
    """Return the singleton RedisStore. Call connect() on app startup."""
    global _store_instance
    if _store_instance is None:
        _store_instance = RedisStore()
    return _store_instance
