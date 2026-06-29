"""
ORACLE Service Entrypoint
=========================
Run with:
    uvicorn oracle.api.main:app --host 0.0.0.0 --port 8000 --reload
Or via Docker:
    docker-compose up
"""

from __future__ import annotations

import sys

from loguru import logger

from oracle.api.routes import app
from oracle.config import get_settings

__all__ = ["app"]

# ── Loguru configuration ──────────────────────────────────────────────────────

settings = get_settings()

logger.remove()
logger.add(
    sys.stderr,
    level=settings.log_level,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    ),
    colorize=True,
)

if settings.is_production:
    logger.add(
        "logs/oracle.log",
        level="INFO",
        rotation="100 MB",
        retention="30 days",
        compression="gz",
        serialize=True,  # JSON log format for production
    )

logger.info(f"ORACLE v1.0.0 starting — env={settings.environment}")
