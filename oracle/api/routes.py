"""
ORACLE FastAPI Routes
=====================
Endpoints:
  GET  /state              — full WorldState JSON
  GET  /state/{domain}     — domain-specific snapshot (crypto|macro|news|onchain)
  GET  /state/prompt       — WorldState as a Hermes-ready context string
  GET  /state/summary      — compact summary dict
  GET  /state/evidence     — machine-readable domain evidence ledger
  POST /state/refresh/{source} — manually trigger a source refresh
  GET  /health             — service + data-source health check
  WS   /stream             — WebSocket push stream (pushes every N seconds)
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger

from oracle.api.formatter import format_world_state_prompt, format_world_state_summary
from oracle.cache.redis_store import get_store
from oracle.config import get_settings
from oracle.models import (
    CryptoState,
    MacroState,
    NewsState,
    OnChainState,
    SourceStatus,
    WorldState,
)
from oracle.workers.refresh_engine import get_engine

# ── Domain registry ───────────────────────────────────────────────────────────

DOMAIN_MODELS = {
    "crypto": CryptoState,
    "macro": MacroState,
    "news": NewsState,
    "onchain": OnChainState,
}


# ── Application factory ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    store = get_store()
    await store.connect()

    engine = get_engine()
    await engine.start()

    logger.info("ORACLE service online ✓")
    yield

    # Shutdown
    await engine.stop()
    await store.disconnect()
    logger.info("ORACLE service shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ORACLE",
        description=(
            "Evidence-aware world-state engine for AI agents. "
            "Aggregates current data while exposing provenance, freshness, "
            "confidence, and actionability as first-class machine-readable fields."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Helper ─────────────────────────────────────────────────────────────

    async def _build_world_state() -> WorldState:
        """Assemble WorldState from Redis cache, attaching source health."""
        store = get_store()
        engine = get_engine()

        crypto = await store.get("crypto", CryptoState)
        macro = await store.get("macro", MacroState)
        news = await store.get("news", NewsState)
        onchain = await store.get("onchain", OnChainState)

        world = WorldState(
            crypto=crypto,
            macro=macro,
            news=news,
            onchain=onchain,
            source_health={
                k: v for k, v in engine.get_all_health().items()
            },
        )
        world.compute_summary()
        return world

    # ── Routes ─────────────────────────────────────────────────────────────

    @app.get(
        "/state",
        summary="Full world state",
        description="Returns the complete aggregated WorldState snapshot.",
        tags=["state"],
    )
    async def get_full_state() -> dict:
        world = await _build_world_state()
        return world.model_dump(mode="json")

    @app.get(
        "/state/prompt",
        response_class=PlainTextResponse,
        summary="Hermes-ready context string",
        description="Returns the WorldState formatted as a prompt-injection context string.",
        tags=["state"],
    )
    async def get_state_prompt() -> str:
        world = await _build_world_state()
        return format_world_state_prompt(world)

    @app.get(
        "/state/summary",
        summary="Compact world state summary",
        description="Returns a compact JSON summary of the most critical signals.",
        tags=["state"],
    )
    async def get_state_summary() -> dict:
        world = await _build_world_state()
        return format_world_state_summary(world)

    @app.get(
        "/state/evidence",
        summary="Evidence ledger",
        description=(
            "Returns per-domain provenance, source status, age, confidence, "
            "and whether the current observation is safe for agent action."
        ),
        tags=["state"],
    )
    async def get_state_evidence() -> dict:
        world = await _build_world_state()
        return {
            "timestamp": world.generated_at.isoformat(),
            "trusted_data_pct": world.trusted_data_pct,
            "domains": {
                name: record.model_dump(mode="json")
                for name, record in world.evidence.items()
            },
        }

    @app.get(
        "/state/{domain}",
        summary="Domain-specific snapshot",
        description="Returns data for a specific domain: crypto | macro | news | onchain",
        tags=["state"],
    )
    async def get_domain_state(domain: str) -> dict:
        if domain not in DOMAIN_MODELS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown domain '{domain}'. Valid: {list(DOMAIN_MODELS.keys())}",
            )
        store = get_store()
        model_class = DOMAIN_MODELS[domain]
        data = await store.get(domain, model_class)
        if data is None:
            raise HTTPException(
                status_code=503,
                detail=f"No data available for '{domain}' yet. Workers may still be initialising.",
            )
        return data.model_dump(mode="json")

    @app.post(
        "/state/refresh/{source}",
        summary="Trigger immediate refresh",
        description="Manually trigger a data refresh for a specific source.",
        tags=["state"],
    )
    async def trigger_refresh(source: str) -> dict:
        if source not in DOMAIN_MODELS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown source '{source}'. Valid: {list(DOMAIN_MODELS.keys())}",
            )
        engine = get_engine()
        success = await engine.trigger_refresh(source)
        return {
            "source": source,
            "refreshed": success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get(
        "/health",
        summary="Service health check",
        description="Returns health status for the service and all data sources.",
        tags=["health"],
    )
    async def health_check() -> dict:
        store = get_store()
        engine = get_engine()
        cache_health = await store.health_check()
        source_health = engine.get_all_health()

        all_ok = all(
            h.status == SourceStatus.OK for h in source_health.values()
        )
        any_error = any(
            h.status == SourceStatus.ERROR for h in source_health.values()
        )

        overall_status = "ok"
        if any_error:
            overall_status = "degraded"
        elif not all_ok:
            overall_status = "partial"

        return {
            "status": overall_status,
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cache": cache_health,
            "sources": {
                name: {
                    "status": h.status.value,
                    "last_success": h.last_success.isoformat() if h.last_success else None,
                    "consecutive_failures": h.consecutive_failures,
                    "avg_latency_ms": h.avg_latency_ms,
                    "uptime_pct": h.uptime_pct,
                }
                for name, h in source_health.items()
            },
            "engine_running": engine.is_running,
        }

    # ── WebSocket Stream ───────────────────────────────────────────────────

    @app.websocket("/stream")
    async def websocket_stream(websocket: WebSocket) -> None:
        """
        WebSocket endpoint that pushes WorldState updates at a configurable interval.

        Message types sent to client:
          {"type": "state", "data": {...}}       — full world state
          {"type": "summary", "data": {...}}     — compact summary
          {"type": "ping"}                       — keepalive
        """
        await websocket.accept()
        settings = get_settings()
        client_addr = websocket.client.host if websocket.client else "unknown"
        logger.info(f"[ws] Client connected: {client_addr}")

        push_interval = settings.ws_push_interval
        tick = 0

        try:
            while True:
                tick += 1
                world = await _build_world_state()

                # Full state every push_interval
                await websocket.send_text(
                    json.dumps({
                        "type": "state",
                        "tick": tick,
                        "data": world.model_dump(mode="json"),
                    })
                )

                # Also send compact summary
                await websocket.send_text(
                    json.dumps({
                        "type": "summary",
                        "tick": tick,
                        "data": format_world_state_summary(world),
                    })
                )

                # Wait for next push, but check for client disconnect
                for _ in range(push_interval):
                    await asyncio.sleep(1)

        except WebSocketDisconnect:
            logger.info(f"[ws] Client disconnected: {client_addr}")
        except Exception as exc:
            logger.error(f"[ws] Stream error for {client_addr}: {exc}")
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    return app


# ── Application instance ──────────────────────────────────────────────────────

app = create_app()
