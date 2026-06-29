"""
Tests for ORACLE data collectors.
Mocks all external HTTP calls — no real API keys or network required.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from oracle.models import (
    CryptoState,
    FearGreedCategory,
    MacroState,
    MarketTrend,
    NewsState,
    OnChainState,
    Sentiment,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_mock_response(data: Any, status_code: int = 200) -> MagicMock:
    """Create a mock httpx response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.text = json.dumps(data)
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        from httpx import HTTPStatusError, Request, Response
        mock.raise_for_status.side_effect = HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock,
        )
    return mock


COINGECKO_SAMPLE = [
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "current_price": 67000.0,
        "price_change_percentage_24h": 2.34,
        "price_change_percentage_7d_in_currency": 8.1,
        "market_cap": 1_315_000_000_000,
        "total_volume": 28_000_000_000,
        "market_cap_rank": 1,
        "ath": 73_000.0,
        "ath_change_percentage": -8.2,
    },
    {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "current_price": 3450.0,
        "price_change_percentage_24h": 1.87,
        "price_change_percentage_7d_in_currency": 5.4,
        "market_cap": 414_000_000_000,
        "total_volume": 12_000_000_000,
        "market_cap_rank": 2,
        "ath": 4878.0,
        "ath_change_percentage": -29.3,
    },
]

FEAR_GREED_SAMPLE = {
    "data": [
        {"value": "72", "value_classification": "Greed", "timestamp": "1705320000"},
        {"value": "68", "value_classification": "Greed", "timestamp": "1705233600"},
    ]
}

CRYPTOPANIC_SAMPLE = {
    "results": [
        {
            "title": "Bitcoin Surges Past $67K",
            "url": "https://example.com/1",
            "source": {"title": "CoinDesk"},
            "published_at": "2024-01-15T14:32:00Z",
            "currencies": [{"code": "BTC"}],
            "votes": {"positive": 45, "negative": 5},
            "kind": "news",
        },
        {
            "title": "Ethereum Hack Drains $10M from DeFi Protocol",
            "url": "https://example.com/2",
            "source": {"title": "Decrypt"},
            "published_at": "2024-01-15T13:00:00Z",
            "currencies": [{"code": "ETH"}],
            "votes": {"positive": 2, "negative": 30},
            "kind": "news",
        },
    ]
}

ETHERSCAN_GAS_SAMPLE = {
    "status": "1",
    "message": "OK",
    "result": {
        "SafeGasPrice": "12",
        "ProposeGasPrice": "18",
        "FastGasPrice": "28",
        "suggestBaseFee": "11.5",
    },
}

ETHERSCAN_BLOCK_SAMPLE = {
    "result": "0x129E5E8",  # 19 529 192 in decimal
}


# ── Crypto collector tests ────────────────────────────────────────────────────


class TestCryptoCollector:
    @pytest.mark.asyncio
    async def test_fetch_fear_greed_success(self):
        from oracle.collectors.crypto import fetch_fear_greed

        mock_client = AsyncMock()
        mock_client.get.return_value = make_mock_response(FEAR_GREED_SAMPLE)

        result = await fetch_fear_greed(mock_client)

        assert result is not None
        assert result.value == 72
        assert result.category == FearGreedCategory.GREED
        assert result.previous_value == 68

    @pytest.mark.asyncio
    async def test_fetch_fear_greed_api_error(self):
        from oracle.collectors.crypto import fetch_fear_greed

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")

        result = await fetch_fear_greed(mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_coingecko_markets_success(self):
        from oracle.collectors.crypto import fetch_coingecko_markets

        mock_client = AsyncMock()
        mock_client.get.return_value = make_mock_response(COINGECKO_SAMPLE)

        coins = await fetch_coingecko_markets(mock_client, top_n=2)

        assert len(coins) == 2
        assert coins[0].symbol == "btc"
        assert coins[0].price_usd == 67000.0
        assert coins[0].change_24h_pct == 2.34
        assert coins[0].rank == 1

    @pytest.mark.asyncio
    async def test_fetch_coingecko_markets_http_error(self):
        from oracle.collectors.crypto import fetch_coingecko_markets

        mock_client = AsyncMock()
        mock_client.get.return_value = make_mock_response({}, status_code=429)

        coins = await fetch_coingecko_markets(mock_client)
        assert coins == []

    @pytest.mark.asyncio
    async def test_collect_crypto_full(self):
        """Full integration test with mocked HTTP."""
        from oracle.collectors.crypto import collect_crypto

        with patch("oracle.collectors.crypto.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_client

            # First call: markets, second: fear/greed (order depends on gather)
            mock_client.get.side_effect = [
                make_mock_response(COINGECKO_SAMPLE),
                make_mock_response(FEAR_GREED_SAMPLE),
            ]

            # Actually both calls happen; patch gather order is non-deterministic
            # so we patch individual functions instead
            with (
                patch("oracle.collectors.crypto.fetch_coingecko_markets") as mock_markets,
                patch("oracle.collectors.crypto.fetch_fear_greed") as mock_fg,
            ):
                from oracle.models import CoinData, FearGreedData

                mock_markets.return_value = [
                    CoinData(id="bitcoin", symbol="btc", name="Bitcoin", price_usd=67000.0,
                             change_24h_pct=2.34, market_cap_usd=1_300_000_000_000, rank=1)
                ]
                mock_fg.return_value = FearGreedData(value=72, category=FearGreedCategory.GREED)

                state = await collect_crypto()

        assert isinstance(state, CryptoState)
        assert len(state.coins) == 1
        assert state.fear_greed is not None
        assert state.fear_greed.value == 72
        assert state.btc_dominance_pct == 100.0  # only coin

    def test_market_trend_bullish(self):
        from oracle.collectors.crypto import _infer_market_trend
        from oracle.models import CoinData

        coins = [
            CoinData(id=f"coin{i}", symbol=f"c{i}", name=f"Coin {i}",
                     price_usd=100.0, change_24h_pct=5.0)
            for i in range(10)
        ]
        assert _infer_market_trend(coins) == MarketTrend.BULLISH

    def test_market_trend_bearish(self):
        from oracle.collectors.crypto import _infer_market_trend
        from oracle.models import CoinData

        coins = [
            CoinData(id=f"coin{i}", symbol=f"c{i}", name=f"Coin {i}",
                     price_usd=100.0, change_24h_pct=-5.0)
            for i in range(10)
        ]
        assert _infer_market_trend(coins) == MarketTrend.BEARISH

    def test_market_trend_empty(self):
        from oracle.collectors.crypto import _infer_market_trend
        assert _infer_market_trend([]) == MarketTrend.NEUTRAL


# ── News collector tests ──────────────────────────────────────────────────────


class TestNewsCollector:
    def test_classify_sentiment_positive(self):
        from oracle.collectors.news import classify_sentiment
        assert classify_sentiment("Bitcoin surges to all-time high record") == Sentiment.POSITIVE

    def test_classify_sentiment_negative(self):
        from oracle.collectors.news import classify_sentiment
        assert classify_sentiment("Major DeFi hack drains $50M from protocol") == Sentiment.NEGATIVE

    def test_classify_sentiment_neutral(self):
        from oracle.collectors.news import classify_sentiment
        assert classify_sentiment("Ethereum developers discuss upcoming changes") == Sentiment.NEUTRAL

    @pytest.mark.asyncio
    async def test_fetch_cryptopanic_no_key(self):
        from oracle.collectors.news import fetch_cryptopanic

        with patch("oracle.collectors.news.get_settings") as mock_settings:
            mock_settings.return_value.cryptopanic_api_key = ""
            mock_client = AsyncMock()
            result = await fetch_cryptopanic(mock_client)
            assert result == []
            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_cryptopanic_with_key(self):
        from oracle.collectors.news import fetch_cryptopanic

        with patch("oracle.collectors.news.get_settings") as mock_settings:
            mock_settings.return_value.cryptopanic_api_key = "test_key"
            mock_client = AsyncMock()
            mock_client.get.return_value = make_mock_response(CRYPTOPANIC_SAMPLE)

            items = await fetch_cryptopanic(mock_client)

        assert len(items) == 2
        assert items[0].title == "Bitcoin Surges Past $67K"
        assert items[0].sentiment == Sentiment.POSITIVE
        assert items[1].sentiment == Sentiment.NEGATIVE
        assert "BTC" in items[0].currencies

    @pytest.mark.asyncio
    async def test_fetch_rss_fallback(self):
        from oracle.collectors.news import fetch_rss_fallback

        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>CoinDesk</title>
            <item>
              <title>Bitcoin ETF Sees Record Inflows</title>
              <link>https://coindesk.com/1</link>
            </item>
            <item>
              <title>Ethereum Gas Fees Drop to 2024 Low</title>
              <link>https://coindesk.com/2</link>
            </item>
          </channel>
        </rss>"""

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.text = rss_xml
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        items = await fetch_rss_fallback(mock_client, limit=5)
        assert len(items) > 0
        assert any("Bitcoin" in item.title for item in items)

    @pytest.mark.asyncio
    async def test_collect_news_dominant_sentiment(self):
        from oracle.collectors.news import collect_news

        with (
            patch("oracle.collectors.news.fetch_cryptopanic") as mock_cp,
            patch("oracle.collectors.news.fetch_newsapi") as mock_na,
            patch("oracle.collectors.news.fetch_rss_fallback") as mock_rss,
        ):
            from oracle.models import NewsItem

            mock_cp.return_value = [
                NewsItem(title=f"Bullish {i}", sentiment=Sentiment.POSITIVE)
                for i in range(7)
            ]
            mock_na.return_value = [
                NewsItem(title=f"Bearish {i}", sentiment=Sentiment.NEGATIVE)
                for i in range(2)
            ]
            mock_rss.return_value = []

            state = await collect_news()

        assert isinstance(state, NewsState)
        assert state.positive_count == 7
        assert state.negative_count == 2
        assert state.dominant_sentiment == Sentiment.POSITIVE


# ── On-chain collector tests ──────────────────────────────────────────────────


class TestOnChainCollector:
    @pytest.mark.asyncio
    async def test_collect_onchain_no_key(self):
        from oracle.collectors.onchain import collect_onchain

        with patch("oracle.collectors.onchain.get_settings") as mock_settings:
            mock_settings.return_value.etherscan_api_key = ""
            state = await collect_onchain()

        assert isinstance(state, OnChainState)
        assert state.gas is not None
        assert state.gas.slow < state.gas.standard < state.gas.fast

    @pytest.mark.asyncio
    async def test_fetch_gas_oracle_success(self):
        from oracle.collectors.onchain import _fetch_gas_oracle

        mock_client = AsyncMock()
        mock_client.get.return_value = make_mock_response(ETHERSCAN_GAS_SAMPLE)

        gas = await _fetch_gas_oracle(mock_client, "test_key")

        assert gas is not None
        assert gas.slow == 12.0
        assert gas.standard == 18.0
        assert gas.fast == 28.0
        assert gas.base_fee == 11.5

    @pytest.mark.asyncio
    async def test_fetch_gas_oracle_api_error(self):
        from oracle.collectors.onchain import _fetch_gas_oracle

        error_response = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
        mock_client = AsyncMock()
        mock_client.get.return_value = make_mock_response(error_response)

        gas = await _fetch_gas_oracle(mock_client, "test_key")
        assert gas is None

    @pytest.mark.asyncio
    async def test_fetch_latest_block(self):
        from oracle.collectors.onchain import _fetch_latest_block

        mock_client = AsyncMock()
        mock_client.get.return_value = make_mock_response(ETHERSCAN_BLOCK_SAMPLE)

        block = await _fetch_latest_block(mock_client, "test_key")

        assert block is not None
        assert block == int("0x129E5E8", 16)

    def test_congestion_classification(self):
        from oracle.collectors.onchain import _classify_congestion
        assert _classify_congestion(10) == "low"
        assert _classify_congestion(35) == "moderate"
        assert _classify_congestion(75) == "high"
        assert _classify_congestion(150) == "congested"
