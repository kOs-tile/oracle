# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Onur Kavi <onur@example.com>"
LABEL description="ORACLE — Real-Time World State Engine for Hermes AI Agents"
LABEL version="1.0.0"

WORKDIR /app

# Security: non-root user
RUN groupadd --gid 1001 oracle && \
    useradd --uid 1001 --gid oracle --no-create-home --shell /bin/false oracle

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=oracle:oracle oracle/ ./oracle/
COPY --chown=oracle:oracle scripts/ ./scripts/

# Create logs directory
RUN mkdir -p /app/logs && chown oracle:oracle /app/logs

USER oracle

EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "oracle.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]
