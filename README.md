# ORACLE

> **Status — Legacy research prototype.** ORACLE explores agent world-state aggregation and prompt-ready context. Current KAVI work is moving these ideas toward explicit provenance (`REAL`, `CACHED`, `STALE`, `SIMULATED`, `UNAVAILABLE`) rather than treating fallback data as equivalent to live evidence.


**Real-Time World State Engine for Hermes AI Agents**

> *Your AI knows everything up to its training cutoff — and nothing after.*

---

## The Blind Agent Problem

Every Hermes agent you deploy is, by default, **blind to the present moment**.

It knows the history of Bitcoin. It doesn't know today's price.  
It knows what the VIX measures. It doesn't know what it's reading right now.  
It can reason about DeFi protocols. It can't tell you if gas is 12 or 120 gwei.

This is the **Blind Agent Problem** — and it silently corrupts every market analysis, trading recommendation, and news summary your agents produce. They confidently answer questions about a world that no longer exists.

**ORACLE solves this.** It's a standalone FastAPI service that continuously monitors multiple data streams and exposes a single `/state` endpoint returning a rich, structured snapshot of the world *right now* — ready for direct injection into Hermes agent context.

One `GET /state/prompt` call gives your agent everything it needs to reason about current market conditions, breaking news, on-chain activity, and macro sentiment — in a single formatted context block.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         HERMES AGENT                            │
│                                                                 │
│   "What should I know before I analyze this portfolio?"         │
│         │                                                       │
│         ▼  GET /state/prompt                                    │
│   ┌─────────────┐                                               │
│   │  ORACLE     │◄──── context injected into system prompt     │
│   │  Skill      │                                               │
│   └─────────────┘                                               │
└───────────────────────┬─────────────────────────────────────────┘
                        │  HTTP
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORACLE FastAPI Service                        │
│                                                                 │
│  GET /state          ──► Full WorldState JSON                   │
│  GET /state/{domain} ──► crypto | macro | news | onchain        │
│  GET /state/prompt   ──► Hermes-ready context string            │
│  GET /state/summary  ──► Compact signal summary                 │
│  GET /health         ──► Source health + latencies              │
│  WS  /stream         ──► Real-time push updates                 │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   REFRESH ENGINE                         │  │
│  │  (APScheduler — independent interval per source)         │  │
│  │                                                          │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │  │
│  │  │  crypto  │  │  macro   │  │  news    │  │onchain │  │  │
│  │  │  30sec   │  │  15min   │  │  5min    │  │ 60sec  │  │  │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘  │  │
│  └───────┼─────────────┼─────────────┼─────────────┼───────┘  │
│          ▼             ▼             ▼             ▼           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                  REDIS CACHE                            │   │
│  │     oracle:crypto  oracle:macro  oracle:news  oracle:.. │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │           │            │            │
         ▼           ▼            ▼            ▼
   CoinGecko     yfinance     CryptoPanic  Etherscan
   alt.me API    (thread      NewsAPI      Gas Oracle
   (Fear/Greed)   pool)       RSS Feeds    Block API
```

---

## Data Sources

| Domain | Source | Data | Refresh Rate |
|--------|--------|------|-------------|
| **Crypto** | [CoinGecko v3](https://www.coingecko.com/en/api) | Top 20 coins: price, 24h/7d change, market cap, volume, rank | 30 seconds |
| **Crypto** | [alternative.me](https://alternative.me/crypto/fear-and-greed-index/) | Fear & Greed Index (0–100) with previous day comparison | 30 seconds |
| **Macro** | [yfinance](https://pypi.org/project/yfinance/) | SPY, NVDA, TSLA, BTC-USD, ETH-USD, SOL-USD + % change | 15 minutes |
| **Macro** | yfinance | DXY (Dollar Index), VIX (Volatility Index) | 15 minutes |
| **News** | [CryptoPanic](https://cryptopanic.com/developers/api/) | Hot crypto headlines with community sentiment voting | 5 minutes |
| **News** | [NewsAPI](https://newsapi.org/) | Top general tech/finance/crypto headlines | 5 minutes |
| **News** | RSS (CoinDesk, CoinTelegraph, Decrypt) | Fallback when API keys absent | 5 minutes |
| **On-Chain** | [Etherscan](https://etherscan.io/apis) | ETH gas: slow/standard/fast Gwei, base fee | 60 seconds |
| **On-Chain** | Etherscan | Latest block number, mempool size estimate | 60 seconds |

---

## Quick Start

### One-command Docker start

```bash
git clone https://github.com/kOs-tile/oracle
cd oracle
cp .env.example .env
# Optionally add your API keys to .env
docker-compose up
```

ORACLE is live at **http://localhost:8000**  
Interactive docs at **http://localhost:8000/docs**

### Local development

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Run ORACLE
uvicorn oracle.api.main:app --reload --port 8000

# In another terminal — run the demo (no API keys needed)
python scripts/demo.py
```

---

## Hermes Integration

Copy the skill file and point it at your ORACLE instance:

```bash
cp hermes_skill/ORACLE.md ~/.hermes/skills/ORACLE.md
export ORACLE_API_URL=http://localhost:8000
```

The skill tells Hermes to call ORACLE before any market analysis, trading decision, or news-related task. See [`hermes_skill/ORACLE.md`](hermes_skill/ORACLE.md) for the full skill specification and example invocations.

### Minimal integration example

```python
import httpx

async def get_oracle_context() -> str:
    """Fetch ORACLE world state as a Hermes-ready context string."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/state/prompt")
        return resp.text

# Inject into your Hermes agent system prompt:
context = await get_oracle_context()
system_prompt = f"""You are a crypto market analyst.

{context}

Based on this live data, answer the user's question."""
```

---

## API Reference

### `GET /state`
Returns the full aggregated `WorldState` as structured JSON.

```bash
curl http://localhost:8000/state
```

### `GET /state/{domain}`
Returns data for a specific domain.  
Valid values: `crypto` | `macro` | `news` | `onchain`

```bash
curl http://localhost:8000/state/crypto
curl http://localhost:8000/state/macro
```

### `GET /state/prompt`
Returns the WorldState formatted as a prompt-ready context string for Hermes injection.

```bash
curl http://localhost:8000/state/prompt
```

### `GET /state/summary`
Returns a compact JSON summary of the most critical market signals.

```bash
curl http://localhost:8000/state/summary
```

### `POST /state/refresh/{source}`
Triggers an immediate data refresh for a specific source.

```bash
curl -X POST http://localhost:8000/state/refresh/crypto
```

### `GET /health`
Returns per-source health status, latencies, and uptime percentages.

```bash
curl http://localhost:8000/health
```

### `WS /stream`
WebSocket endpoint that pushes WorldState updates every `WS_PUSH_INTERVAL` seconds.

```python
import asyncio, websockets, json

async def stream():
    async with websockets.connect("ws://localhost:8000/stream") as ws:
        async for msg in ws:
            data = json.loads(msg)
            if data["type"] == "summary":
                print(data["data"]["mood"], data["data"]["btc"])

asyncio.run(stream())
```

---

## Example World State Output

```json
{
  "schema_version": "1.0",
  "generated_at": "2024-01-15T14:32:00.000Z",
  "overall_market_mood": "bullish",
  "data_freshness_pct": 100.0,
  "key_signals": [
    "Fear & Greed: 72/100 (Greed)",
    "BTC ▲2.34% 24h @ $67,234",
    "VIX 14.2 (low volatility)",
    "ETH gas: 28 gwei (fast) — moderate congestion",
    "News sentiment: 58% positive, 22% negative across 20 headlines"
  ],
  "crypto": {
    "coins": [
      {
        "id": "bitcoin",
        "symbol": "BTC",
        "name": "Bitcoin",
        "price_usd": 67234.50,
        "change_24h_pct": 2.34,
        "change_7d_pct": 8.10,
        "market_cap_usd": 1315000000000,
        "volume_24h_usd": 28000000000,
        "rank": 1,
        "ath_usd": 73750.00,
        "ath_change_percentage": -8.82
      },
      {
        "id": "ethereum",
        "symbol": "ETH",
        "name": "Ethereum",
        "price_usd": 3451.20,
        "change_24h_pct": 1.87,
        "change_7d_pct": 5.40,
        "market_cap_usd": 414000000000,
        "rank": 2
      }
    ],
    "fear_greed": {
      "value": 72,
      "category": "Greed",
      "previous_value": 68,
      "previous_category": "Greed",
      "timestamp": "2024-01-15T14:32:00Z"
    },
    "total_market_cap_usd": 2400000000000,
    "total_volume_24h_usd": 120000000000,
    "btc_dominance_pct": 54.79,
    "market_trend": "bullish",
    "top_gainers": ["SOL", "AVAX", "LINK"],
    "top_losers": ["XRP", "DOGE", "ADA"]
  },
  "macro": {
    "stocks": {
      "SPY": {
        "symbol": "SPY",
        "name": "SPDR S&P 500 ETF",
        "price": 487.30,
        "change_pct": 0.82,
        "change_abs": 3.96,
        "volume": 67000000
      },
      "NVDA": {
        "symbol": "NVDA",
        "name": "NVIDIA Corp",
        "price": 875.40,
        "change_pct": 1.24
      },
      "TSLA": {
        "symbol": "TSLA",
        "name": "Tesla Inc",
        "price": 248.70,
        "change_pct": -0.43
      }
    },
    "macro": {
      "^VIX": {
        "symbol": "^VIX",
        "name": "CBOE Volatility Index",
        "price": 14.20,
        "change_pct": -3.10
      },
      "DX-Y.NYB": {
        "symbol": "DX-Y.NYB",
        "name": "US Dollar Index (DXY)",
        "price": 103.40,
        "change_pct": 0.18
      }
    },
    "crypto_yf": {
      "BTC-USD": {"price": 67234.50, "change_pct": 2.34},
      "ETH-USD": {"price": 3451.20, "change_pct": 1.87},
      "SOL-USD": {"price": 178.90, "change_pct": 4.21}
    },
    "market_open": true,
    "spy_trend": "bullish",
    "risk_sentiment": "risk-on"
  },
  "news": {
    "crypto_headlines": [
      {
        "title": "Bitcoin Surges Past $67K as ETF Inflows Hit Weekly Record",
        "url": "https://coindesk.com/...",
        "source": "CoinDesk",
        "published_at": "2024-01-15T13:45:00Z",
        "sentiment": "positive",
        "currencies": ["BTC"]
      },
      {
        "title": "Ethereum Validators Set New All-Time High as Staking Yields Rise",
        "source": "CoinTelegraph",
        "sentiment": "positive",
        "currencies": ["ETH"]
      }
    ],
    "general_headlines": [
      {
        "title": "NVIDIA Reports Record Revenue, Credits AI Chip Demand",
        "source": "Reuters",
        "sentiment": "positive"
      }
    ],
    "trending_topics": ["Bitcoin", "ETF", "Ethereum", "NVIDIA", "FederalReserve", "DeFi"],
    "dominant_sentiment": "positive",
    "positive_count": 12,
    "negative_count": 4,
    "neutral_count": 4
  },
  "onchain": {
    "gas": {
      "slow": 12.0,
      "standard": 18.0,
      "fast": 28.0,
      "base_fee": 11.50,
      "suggest_base_fee": 11.72
    },
    "network_congestion": "moderate",
    "last_block": 19500142,
    "mempool_size_estimate": 125400
  },
  "source_health": {
    "crypto": {
      "source": "crypto",
      "status": "ok",
      "last_success": "2024-01-15T14:31:58Z",
      "consecutive_failures": 0,
      "avg_latency_ms": 342.5,
      "uptime_pct": 99.8
    },
    "macro": {"status": "ok", "avg_latency_ms": 1842.0},
    "news": {"status": "ok", "avg_latency_ms": 512.3},
    "onchain": {"status": "ok", "avg_latency_ms": 198.7}
  }
}
```

---

## Project Structure

```
oracle/
├── oracle/
│   ├── __init__.py
│   ├── config.py              # Pydantic Settings — all env vars
│   ├── models.py              # Pydantic v2 domain models
│   ├── collectors/
│   │   ├── crypto.py          # CoinGecko + Fear & Greed
│   │   ├── macro.py           # yfinance (stocks, macro, crypto)
│   │   ├── news.py            # CryptoPanic + NewsAPI + RSS
│   │   └── onchain.py         # Etherscan gas + block data
│   ├── cache/
│   │   └── redis_store.py     # Async Redis client + memory fallback
│   ├── workers/
│   │   └── refresh_engine.py  # APScheduler background workers
│   └── api/
│       ├── main.py            # Uvicorn entrypoint + logging config
│       ├── routes.py          # FastAPI routes + WebSocket
│       └── formatter.py       # WorldState → Hermes prompt string
├── hermes_skill/
│   └── ORACLE.md              # Hermes-compatible skill file
├── scripts/
│   └── demo.py                # Rich-formatted demo (no API keys needed)
├── tests/
│   ├── test_collectors.py     # Collector unit tests (mocked HTTP)
│   ├── test_cache.py          # Redis store tests (mocked + fallback)
│   └── test_routes.py         # API + model + formatter tests
├── docker-compose.yml         # Redis + ORACLE service
├── Dockerfile                 # Multi-stage, non-root build
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Configuration

All settings can be overridden via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `COINGECKO_API_KEY` | *(empty)* | Optional — free tier works without |
| `CRYPTOPANIC_API_KEY` | *(empty)* | Required for crypto news |
| `NEWSAPI_KEY` | *(empty)* | Required for general headlines |
| `ETHERSCAN_API_KEY` | *(empty)* | Required for real gas prices |
| `REFRESH_INTERVAL_CRYPTO` | `30` | Seconds between crypto refreshes |
| `REFRESH_INTERVAL_MACRO` | `900` | Seconds between macro refreshes |
| `REFRESH_INTERVAL_NEWS` | `300` | Seconds between news refreshes |
| `REFRESH_INTERVAL_ONCHAIN` | `60` | Seconds between on-chain refreshes |
| `WS_PUSH_INTERVAL` | `10` | WebSocket push interval (seconds) |
| `CRYPTO_TOP_N` | `20` | Number of top coins to track |
| `LOG_LEVEL` | `INFO` | Loguru log level |
| `ENVIRONMENT` | `development` | `development` or `production` |

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=oracle --cov-report=term-missing
```

---

## Demo (No API Keys Required)

```bash
python scripts/demo.py           # Single snapshot with Rich formatting
python scripts/demo.py --watch   # Auto-refresh every 5 seconds
python scripts/demo.py --json    # Raw JSON output
python scripts/demo.py --live    # Connect to running ORACLE instance
```

---

## License

MIT — built by [Onur Kavi](https://github.com/kOs-tile) as part of his AI portfolio.
