"""
ORACLE On-Chain Collector
=========================
Fetches Ethereum on-chain metrics via the Etherscan API:
  - Gas prices: slow / standard / fast (Gwei)
  - Base fee suggestion
  - Mempool size estimate (via pending transaction count)
  - Latest block number

Falls back to simulated data when no ETHERSCAN_API_KEY is provided.
Refresh interval: 60 seconds (configurable via REFRESH_INTERVAL_ONCHAIN).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from loguru import logger

from oracle.config import get_settings
from oracle.models import DataProvenance, GasPrices, OnChainState

ETHERSCAN_BASE = "https://api.etherscan.io/api"

# Simulated fallback data for demo/testing without an API key
SIMULATED_GAS = GasPrices(slow=12.0, standard=18.0, fast=28.0, base_fee=11.5)
SIMULATED_BLOCK = 19_500_000


def _classify_congestion(fast_gwei: float) -> str:
    if fast_gwei < 20:
        return "low"
    elif fast_gwei < 50:
        return "moderate"
    elif fast_gwei < 100:
        return "high"
    return "congested"


async def _fetch_gas_oracle(client: httpx.AsyncClient, api_key: str) -> Optional[GasPrices]:
    """
    Calls Etherscan Gas Oracle endpoint.
    Returns GasPrices or None on failure.
    """
    params = {
        "module": "gastracker",
        "action": "gasoracle",
        "apikey": api_key,
    }
    try:
        resp = await client.get(ETHERSCAN_BASE, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1":
            logger.warning(f"[onchain] Etherscan gas oracle error: {data.get('message')}")
            return None

        result = data["result"]
        return GasPrices(
            slow=float(result["SafeGasPrice"]),
            standard=float(result["ProposeGasPrice"]),
            fast=float(result["FastGasPrice"]),
            base_fee=float(result.get("suggestBaseFee", 0)) or None,
            suggest_base_fee=float(result.get("suggestBaseFee", 0)) or None,
        )
    except Exception as exc:
        logger.warning(f"[onchain] Gas oracle fetch failed: {exc}")
        return None


async def _fetch_latest_block(client: httpx.AsyncClient, api_key: str) -> Optional[int]:
    """Fetch the latest Ethereum block number."""
    params = {
        "module": "proxy",
        "action": "eth_blockNumber",
        "apikey": api_key,
    }
    try:
        resp = await client.get(ETHERSCAN_BASE, params=params, timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
        hex_block = data.get("result", "0x0")
        return int(hex_block, 16)
    except Exception as exc:
        logger.warning(f"[onchain] Block number fetch failed: {exc}")
        return None


async def _fetch_mempool_estimate(client: httpx.AsyncClient, api_key: str) -> Optional[int]:
    """
    Estimate mempool size via Etherscan's pending transaction count proxy.
    This is a rough estimate; a full node would provide exact data.
    """
    params = {
        "module": "proxy",
        "action": "eth_getBlockTransactionCountByNumber",
        "tag": "pending",
        "apikey": api_key,
    }
    try:
        resp = await client.get(ETHERSCAN_BASE, params=params, timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
        hex_count = data.get("result", "0x0")
        if hex_count and hex_count != "0x":
            return int(hex_count, 16)
        return None
    except Exception as exc:
        logger.debug(f"[onchain] Mempool estimate failed: {exc}")
        return None


async def collect_onchain() -> OnChainState:
    """Main entry point — returns a fully populated OnChainState."""
    settings = get_settings()

    if not settings.etherscan_api_key:
        logger.info("[onchain] No Etherscan key — returning explicitly simulated demo data")
        return OnChainState(
            gas=SIMULATED_GAS,
            network_congestion=_classify_congestion(SIMULATED_GAS.fast),
            last_block=SIMULATED_BLOCK,
            mempool_size_estimate=None,
            provenance={
                "gas": DataProvenance.SIMULATED,
                "last_block": DataProvenance.SIMULATED,
                "mempool_size_estimate": DataProvenance.UNAVAILABLE,
            },
            provenance_note="Demo fallback because ETHERSCAN_API_KEY is not configured.",
        )

    async with httpx.AsyncClient() as client:
        gas_task = asyncio.create_task(
            _fetch_gas_oracle(client, settings.etherscan_api_key)
        )
        block_task = asyncio.create_task(
            _fetch_latest_block(client, settings.etherscan_api_key)
        )
        mempool_task = asyncio.create_task(
            _fetch_mempool_estimate(client, settings.etherscan_api_key)
        )
        gas, last_block, mempool = await asyncio.gather(gas_task, block_task, mempool_task)

    # A configured live source that fails must fail closed. Never replace a
    # failed real observation with synthetic data while preserving the same shape.
    provenance = {
        "gas": DataProvenance.REAL if gas is not None else DataProvenance.UNAVAILABLE,
        "last_block": DataProvenance.REAL if last_block is not None else DataProvenance.UNAVAILABLE,
        "mempool_size_estimate": (
            DataProvenance.REAL if mempool is not None else DataProvenance.UNAVAILABLE
        ),
    }
    congestion = _classify_congestion(gas.fast) if gas is not None else "unknown"
    logger.info(
        f"[onchain] gas={gas.fast if gas else None} gwei | congestion={congestion} | "
        f"block={last_block} | mempool≈{mempool} | provenance={provenance}"
    )

    return OnChainState(
        gas=gas,
        network_congestion=congestion,
        last_block=last_block,
        mempool_size_estimate=mempool,
        provenance=provenance,
        provenance_note=(
            "Live Etherscan observations; unavailable fields remain unavailable."
        ),
    )
