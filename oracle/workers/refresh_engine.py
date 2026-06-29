"""
ORACLE Refresh Engine
=====================
APScheduler-based background engine that independently schedules each
data-source collector and writes results to Redis.

Source health tracking:
  - last_success / last_failure timestamps
  - consecutive_failures counter
  - avg_latency_ms (exponential moving average)
  - SourceStatus: ok / degraded / stale / error / pending

The engine runs as an asyncio-native scheduler (AsyncIOScheduler) so it
coexists cleanly with FastAPI's event loop.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from oracle.cache.redis_store import get_store
from oracle.collectors.crypto import collect_crypto
from oracle.collectors.macro import collect_macro
from oracle.collectors.news import collect_news
from oracle.collectors.onchain import collect_onchain
from oracle.config import get_settings
from oracle.models import SourceHealth, SourceStatus

# Cache keys — must match what api/routes.py reads
CACHE_KEYS = {
    "crypto": "crypto",
    "macro": "macro",
    "news": "news",
    "onchain": "onchain",
}

# TTL per domain (seconds) — slightly longer than refresh interval
CACHE_TTLS = {
    "crypto": 90,
    "macro": 1800,
    "news": 600,
    "onchain": 180,
}

# EMA alpha for latency smoothing
_EMA_ALPHA = 0.2


class RefreshEngine:
    """
    Manages background refresh workers for all ORACLE data sources.

    Lifecycle:
        engine = RefreshEngine()
        await engine.start()   # begins all workers
        await engine.stop()    # graceful shutdown

    The engine is started by the FastAPI lifespan handler.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._health: dict[str, SourceHealth] = {
            name: SourceHealth(source=name) for name in CACHE_KEYS
        }
        self._settings = get_settings()

    # ── Health accessors ──────────────────────────────────────────────────────

    def get_health(self, source: str) -> Optional[SourceHealth]:
        return self._health.get(source)

    def get_all_health(self) -> dict[str, SourceHealth]:
        return dict(self._health)

    # ── Worker wrapper ────────────────────────────────────────────────────────

    async def _run_collector(
        self,
        source: str,
        collector_fn: Callable[[], Coroutine[Any, Any, Any]],
        ttl: int,
    ) -> None:
        """
        Wraps a collector coroutine with:
          - timing measurement
          - Redis write
          - health status updates
          - error isolation (one source failing never crashes others)
        """
        health = self._health[source]
        health.total_fetches += 1
        t0 = time.monotonic()

        try:
            result = await collector_fn()
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Write to Redis
            store = get_store()
            await store.set(CACHE_KEYS[source], result, ttl=ttl)

            # Update health — success path
            health.status = SourceStatus.OK
            health.last_success = datetime.now(timezone.utc)
            health.consecutive_failures = 0
            if health.avg_latency_ms is None:
                health.avg_latency_ms = elapsed_ms
            else:
                health.avg_latency_ms = (
                    _EMA_ALPHA * elapsed_ms
                    + (1 - _EMA_ALPHA) * health.avg_latency_ms
                )
            health.last_error_message = None

            logger.debug(
                f"[engine] ✓ {source} refreshed in {elapsed_ms:.0f}ms "
                f"(EMA {health.avg_latency_ms:.0f}ms)"
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            health.total_errors += 1
            health.consecutive_failures += 1
            health.last_failure = datetime.now(timezone.utc)
            health.last_error_message = str(exc)[:200]

            max_failures = self._settings.max_consecutive_failures
            if health.consecutive_failures >= max_failures:
                health.status = SourceStatus.ERROR
                logger.error(
                    f"[engine] ✗ {source} failed {health.consecutive_failures}x "
                    f"consecutively: {exc}"
                )
            else:
                health.status = SourceStatus.DEGRADED
                logger.warning(
                    f"[engine] ⚠ {source} failed (attempt "
                    f"{health.consecutive_failures}/{max_failures}): {exc}"
                )

    # ── Scheduler setup ───────────────────────────────────────────────────────

    def _add_job(
        self,
        source: str,
        collector_fn: Callable[[], Coroutine],
        interval_seconds: int,
        ttl: int,
    ) -> None:
        async def _job() -> None:
            await self._run_collector(source, collector_fn, ttl)

        self._scheduler.add_job(
            _job,
            trigger=IntervalTrigger(seconds=interval_seconds),
            id=f"oracle_{source}",
            name=f"ORACLE {source} refresh",
            max_instances=1,          # prevent overlapping runs
            coalesce=True,            # skip missed runs
            replace_existing=True,
            misfire_grace_time=interval_seconds // 2,
        )
        logger.info(
            f"[engine] Registered job '{source}' every {interval_seconds}s "
            f"(TTL={ttl}s)"
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Register all jobs and start the scheduler."""
        s = self._settings

        self._add_job("crypto", collect_crypto, s.refresh_interval_crypto, CACHE_TTLS["crypto"])
        self._add_job("macro", collect_macro, s.refresh_interval_macro, CACHE_TTLS["macro"])
        self._add_job("news", collect_news, s.refresh_interval_news, CACHE_TTLS["news"])
        self._add_job("onchain", collect_onchain, s.refresh_interval_onchain, CACHE_TTLS["onchain"])

        self._scheduler.start()
        logger.info("[engine] RefreshEngine started — all workers active")

        # Run all collectors once immediately on startup (do not await — fire-and-forget)
        await self._initial_populate()

    async def _initial_populate(self) -> None:
        """Run all collectors once at startup to pre-warm the cache."""
        logger.info("[engine] Pre-warming cache with initial data fetch...")

        tasks = [
            self._run_collector("crypto", collect_crypto, CACHE_TTLS["crypto"]),
            self._run_collector("macro", collect_macro, CACHE_TTLS["macro"]),
            self._run_collector("news", collect_news, CACHE_TTLS["news"]),
            self._run_collector("onchain", collect_onchain, CACHE_TTLS["onchain"]),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for source, result in zip(CACHE_KEYS.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"[engine] Initial populate failed for {source}: {result}")

        logger.info("[engine] Cache pre-warm complete")

    async def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("[engine] RefreshEngine stopped")

    async def trigger_refresh(self, source: str) -> bool:
        """Manually trigger an immediate refresh for a specific source."""
        collectors = {
            "crypto": collect_crypto,
            "macro": collect_macro,
            "news": collect_news,
            "onchain": collect_onchain,
        }
        if source not in collectors:
            return False
        await self._run_collector(source, collectors[source], CACHE_TTLS[source])
        return True

    @property
    def is_running(self) -> bool:
        return self._scheduler.running


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine_instance: Optional[RefreshEngine] = None


def get_engine() -> RefreshEngine:
    """Return the singleton RefreshEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RefreshEngine()
    return _engine_instance
