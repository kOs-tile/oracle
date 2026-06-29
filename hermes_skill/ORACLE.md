---
name: ORACLE
version: "1.0.0"
description: >
  Real-time world state engine for Hermes agents. Provides structured,
  live context from crypto markets, macro indicators, Ethereum on-chain
  data, and news headlines — aggregated into a single context bundle.
author: Onur Kavi
license: MIT

# ── Authentication ─────────────────────────────────────────────────────────
auth:
  type: env
  variables:
    - name: ORACLE_API_URL
      description: Base URL of your running ORACLE service
      example: "http://localhost:8000"
      required: true

# ── Tool definitions ───────────────────────────────────────────────────────
tools:
  - name: get_world_state
    description: >
      Fetch the complete real-time world state from ORACLE. Returns structured
      JSON with crypto prices, macro data, news headlines, and on-chain metrics.
    endpoint: GET ${ORACLE_API_URL}/state
    returns: WorldState JSON object

  - name: get_world_context
    description: >
      Fetch the world state as a formatted, prompt-ready context string.
      Use this when you want to inject world context directly into your reasoning.
    endpoint: GET ${ORACLE_API_URL}/state/prompt
    returns: Plain text context string

  - name: get_world_summary
    description: >
      Fetch a compact summary of the most critical market signals.
      Faster and lighter than get_world_state — use for quick checks.
    endpoint: GET ${ORACLE_API_URL}/state/summary
    returns: Compact JSON summary

  - name: get_crypto_state
    description: >
      Fetch only the cryptocurrency domain: top 20 coin prices, Fear & Greed
      index, market cap, BTC dominance, top gainers/losers.
    endpoint: GET ${ORACLE_API_URL}/state/crypto
    returns: CryptoState JSON object

  - name: get_macro_state
    description: >
      Fetch macro/equity data: SPY, NVDA, TSLA, BTC-USD, ETH-USD, SOL-USD,
      DXY (Dollar Index), VIX (Volatility Index).
    endpoint: GET ${ORACLE_API_URL}/state/macro
    returns: MacroState JSON object

  - name: get_news_state
    description: >
      Fetch the latest news headlines from CryptoPanic, NewsAPI, and RSS feeds
      with sentiment classification (positive/negative/neutral) and trending topics.
    endpoint: GET ${ORACLE_API_URL}/state/news
    returns: NewsState JSON object

  - name: get_onchain_state
    description: >
      Fetch Ethereum on-chain metrics: gas prices (slow/standard/fast Gwei),
      network congestion level, latest block, and mempool size estimate.
    endpoint: GET ${ORACLE_API_URL}/state/onchain
    returns: OnChainState JSON object

  - name: get_health
    description: >
      Check the health of the ORACLE service and all its data sources.
      Returns per-source status, latency, and uptime percentages.
    endpoint: GET ${ORACLE_API_URL}/health
    returns: Health status JSON

  - name: trigger_refresh
    description: >
      Force an immediate data refresh for a specific source.
      Valid sources: crypto, macro, news, onchain
    endpoint: POST ${ORACLE_API_URL}/state/refresh/{source}
    parameters:
      source: string (crypto | macro | news | onchain)
    returns: Refresh confirmation JSON

---

# ORACLE Skill — Hermes Integration Guide

## Overview

ORACLE gives Hermes agents **real-time awareness of the outside world**.
Without ORACLE, Hermes has no knowledge of current market prices, breaking
news, network conditions, or macro sentiment. With ORACLE, every agent
response can be grounded in live, structured reality.

## When to Call ORACLE

Hermes should **automatically call ORACLE** before responding to any task
involving:

| Task Type | Recommended Tool |
|-----------|-----------------|
| Market analysis, trading decisions | `get_world_state` or `get_crypto_state` |
| Portfolio review, allocation advice | `get_world_state` |
| News summarisation, event detection | `get_news_state` |
| DeFi interactions, gas cost estimates | `get_onchain_state` |
| Macro commentary, risk sentiment | `get_macro_state` |
| Quick situational awareness | `get_world_summary` |
| Injecting context into long prompts | `get_world_context` |

**Rule of thumb**: If the task requires knowledge of anything that changes
faster than your training data, call ORACLE first.

## Example Invocations

### 1. Pre-flight context injection

```python
# Hermes agent preamble — called before any market-related task
import httpx

async def get_oracle_context() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ORACLE_API_URL}/state/prompt")
        return resp.text  # inject into system prompt

context = await get_oracle_context()
system_prompt = f"""You are a crypto market analyst.

Current real-time world state:
{context}

Based on this live data, answer the user's question."""
```

### 2. Structured JSON for decision logic

```python
import httpx

async def should_buy_btc() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ORACLE_API_URL}/state/summary")
        summary = resp.json()

    btc_change = summary["btc"]["change_24h_pct"]
    fear_greed = summary["fear_greed"]["value"]
    mood = summary["mood"]

    return {
        "btc_24h": btc_change,
        "fear_greed": fear_greed,
        "market_mood": mood,
        "signal": "buy" if fear_greed < 30 and btc_change > -5 else "wait",
    }
```

### 3. Gas-aware DeFi transaction

```python
import httpx

async def estimate_swap_cost() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ORACLE_API_URL}/state/onchain")
        onchain = resp.json()

    gas = onchain["gas"]
    congestion = onchain["network_congestion"]

    if congestion in ("high", "congested"):
        return f"⚠️ High gas: {gas['fast']} gwei fast. Consider waiting."
    return f"✓ Normal gas: {gas['standard']} gwei standard."
```

### 4. WebSocket real-time feed

```python
import asyncio
import websockets
import json

async def stream_world_state():
    uri = f"ws://localhost:8000/stream"
    async with websockets.connect(uri) as ws:
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "summary":
                summary = data["data"]
                print(f"BTC: ${summary['btc']['price']:,.0f} | "
                      f"F&G: {summary['fear_greed']['value']} | "
                      f"Mood: {summary['mood']}")

asyncio.run(stream_world_state())
```

## Output Format

### WorldState (GET /state)

```json
{
  "schema_version": "1.0",
  "generated_at": "2024-01-15T14:32:00Z",
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
    "coins": [...],
    "fear_greed": {"value": 72, "category": "Greed"},
    "btc_dominance_pct": 54.2,
    "market_trend": "bullish",
    "top_gainers": ["SOL", "AVAX", "DOT"],
    "top_losers": ["XRP", "DOGE", "ADA"]
  },
  "macro": {
    "stocks": {"SPY": {"price": 487.3, "change_pct": 0.82}},
    "macro": {"^VIX": {"price": 14.2}, "DX-Y.NYB": {"price": 103.4}},
    "risk_sentiment": "risk-on"
  },
  "news": {
    "crypto_headlines": [...],
    "trending_topics": ["Bitcoin", "ETF", "SEC", "Ethereum", "AI"],
    "dominant_sentiment": "positive"
  },
  "onchain": {
    "gas": {"slow": 12, "standard": 18, "fast": 28},
    "network_congestion": "moderate",
    "last_block": 19500000
  }
}
```

## Refresh Rates

| Domain | Source | Interval |
|--------|--------|----------|
| Crypto prices | CoinGecko API | 30 seconds |
| Fear & Greed | alternative.me | 30 seconds |
| Macro/Equities | yfinance | 15 minutes |
| News | CryptoPanic + NewsAPI + RSS | 5 minutes |
| Gas prices | Etherscan API | 60 seconds |

## Error Handling

ORACLE returns graceful partial data when sources fail. Always check
`source_health` in the response — if a source shows `status: "error"`,
the corresponding domain data may be stale. You can trigger a manual
refresh via `POST /state/refresh/{source}`.

## Environment Setup

```bash
# Required
ORACLE_API_URL=http://localhost:8000

# Optional — ORACLE works without these (with reduced data)
COINGECKO_API_KEY=your_key    # Free tier works without
CRYPTOPANIC_API_KEY=your_key  # Free at cryptopanic.com
NEWSAPI_KEY=your_key          # Free at newsapi.org
ETHERSCAN_API_KEY=your_key    # Free at etherscan.io
```

## Quick Start

```bash
git clone https://github.com/onurkavi/oracle
cd oracle
cp .env.example .env
docker-compose up
```

ORACLE is live at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.
