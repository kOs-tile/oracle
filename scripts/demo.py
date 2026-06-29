#!/usr/bin/env python3
"""
ORACLE Demo Script
==================
Runs a beautiful Rich-formatted world state snapshot using fully simulated
data — no API keys, no running service, no Redis required.

Usage:
    python scripts/demo.py
    python scripts/demo.py --live        # connect to running ORACLE instance
    python scripts/demo.py --watch       # refresh every 5 seconds
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from datetime import datetime, timezone
from typing import Optional

# ── Rich imports ──────────────────────────────────────────────────────────────
try:
    from rich import box
    from rich.columns import Columns
    from rich.console import Console
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Install rich for the full demo: pip install rich")

# ── ORACLE imports ────────────────────────────────────────────────────────────
sys.path.insert(0, str(__file__).replace("/scripts/demo.py", ""))

from oracle.models import (
    CoinData,
    CryptoState,
    FearGreedCategory,
    FearGreedData,
    GasPrices,
    MacroState,
    MarketTrend,
    NewsItem,
    NewsState,
    OnChainState,
    Sentiment,
    SourceHealth,
    SourceStatus,
    TickerData,
    WorldState,
)
from oracle.api.formatter import format_world_state_prompt, format_world_state_summary

console = Console() if HAS_RICH else None

# ── Simulated data generators ─────────────────────────────────────────────────

COIN_TEMPLATES = [
    ("bitcoin", "BTC", "Bitcoin", 67_000, 54.2),
    ("ethereum", "ETH", "Ethereum", 3_450, 17.1),
    ("solana", "SOL", "Solana", 178, 3.8),
    ("binancecoin", "BNB", "BNB", 412, 3.9),
    ("ripple", "XRP", "XRP", 0.62, 4.2),
    ("dogecoin", "DOGE", "Dogecoin", 0.18, 1.1),
    ("cardano", "ADA", "Cardano", 0.48, 2.3),
    ("avalanche-2", "AVAX", "Avalanche", 38, 1.5),
    ("chainlink", "LINK", "Chainlink", 18, 0.9),
    ("polkadot", "DOT", "Polkadot", 8.2, 0.7),
    ("uniswap", "UNI", "Uniswap", 11.4, 0.4),
    ("litecoin", "LTC", "Litecoin", 95, 0.6),
    ("shiba-inu", "SHIB", "Shiba Inu", 0.0000265, 0.3),
    ("cosmos", "ATOM", "Cosmos", 8.9, 0.5),
    ("near", "NEAR", "NEAR Protocol", 7.1, 0.4),
    ("filecoin", "FIL", "Filecoin", 6.2, 0.3),
    ("aptos", "APT", "Aptos", 9.8, 0.3),
    ("arbitrum", "ARB", "Arbitrum", 1.24, 0.3),
    ("optimism", "OP", "Optimism", 2.87, 0.25),
    ("stacks", "STX", "Stacks", 2.12, 0.2),
]


def _jitter(base: float, pct_range: float = 3.0) -> float:
    """Add realistic random noise to a base price."""
    return base * (1 + random.uniform(-pct_range, pct_range) / 100)


def make_crypto_state() -> CryptoState:
    coins = []
    total_cap = 0.0
    for rank, (cid, sym, name, base_price, base_cap_b) in enumerate(COIN_TEMPLATES, 1):
        price = _jitter(base_price)
        cap = _jitter(base_cap_b * 1e9)
        total_cap += cap
        change_24h = random.gauss(1.2, 4.5)  # slight upward bias
        change_7d = random.gauss(3.1, 8.0)
        coins.append(CoinData(
            id=cid,
            symbol=sym,
            name=name,
            price_usd=round(price, 6 if price < 0.001 else 2),
            change_24h_pct=round(change_24h, 2),
            change_7d_pct=round(change_7d, 2),
            market_cap_usd=cap,
            volume_24h_usd=cap * random.uniform(0.03, 0.12),
            rank=rank,
            ath_usd=base_price * random.uniform(1.05, 2.8),
            ath_change_pct=random.uniform(-60, -5),
        ))

    fg_val = random.randint(55, 78)  # demo leans greedy
    btc_cap = coins[0].market_cap_usd or 1
    btc_dom = round(btc_cap / total_cap * 100, 2)

    sorted_coins = sorted(coins, key=lambda c: c.change_24h_pct or 0, reverse=True)
    gainers = [c.symbol for c in sorted_coins[:3]]
    losers = [c.symbol for c in sorted_coins[-3:]]

    return CryptoState(
        coins=coins,
        fear_greed=FearGreedData(
            value=fg_val,
            category=FearGreedCategory.GREED if fg_val > 60 else FearGreedCategory.NEUTRAL,
            previous_value=fg_val - random.randint(-5, 5),
            previous_category=FearGreedCategory.NEUTRAL,
        ),
        total_market_cap_usd=total_cap,
        total_volume_24h_usd=total_cap * 0.05,
        btc_dominance_pct=btc_dom,
        market_trend=MarketTrend.BULLISH,
        top_gainers=gainers,
        top_losers=losers,
    )


def make_macro_state() -> MacroState:
    def td(sym: str, price: float, chg: Optional[float] = None, name: str = "") -> TickerData:
        p = _jitter(price, 0.5)
        c = chg if chg is not None else random.gauss(0.3, 0.8)
        return TickerData(
            symbol=sym,
            name=name or sym,
            price=round(p, 2),
            change_pct=round(c, 2),
            change_abs=round(p * c / 100, 2),
            volume=random.randint(40_000_000, 120_000_000),
        )

    return MacroState(
        stocks={
            "SPY": td("SPY", 487.3, 0.82, "SPDR S&P 500 ETF"),
            "NVDA": td("NVDA", 875.4, 1.24, "NVIDIA Corp"),
            "TSLA": td("TSLA", 248.7, -0.43, "Tesla Inc"),
        },
        macro={
            "^VIX": td("^VIX", 14.2, -3.1, "CBOE Volatility Index"),
            "DX-Y.NYB": td("DX-Y.NYB", 103.4, 0.18, "US Dollar Index (DXY)"),
        },
        crypto_yf={
            "BTC-USD": td("BTC-USD", 67_000, 2.34, "Bitcoin USD"),
            "ETH-USD": td("ETH-USD", 3_450, 1.87, "Ethereum USD"),
            "SOL-USD": td("SOL-USD", 178, 4.21, "Solana USD"),
        },
        market_open=True,
        spy_trend=MarketTrend.BULLISH,
        risk_sentiment="risk-on",
    )


def make_news_state() -> NewsState:
    crypto_headlines = [
        ("Bitcoin Surges Past $67K as ETF Inflows Hit Weekly Record", Sentiment.POSITIVE, "CoinDesk"),
        ("Ethereum Validators Set New All-Time High as Staking Yields Rise", Sentiment.POSITIVE, "CoinTelegraph"),
        ("Solana DEX Volume Overtakes Ethereum for Third Consecutive Week", Sentiment.POSITIVE, "Decrypt"),
        ("SEC Chair Signals Possible Approval Framework for Crypto Spot ETFs", Sentiment.POSITIVE, "Bloomberg Crypto"),
        ("BlackRock BTC ETF Surpasses $20B AUM in Record Time", Sentiment.POSITIVE, "Reuters"),
        ("DeFi Total Value Locked Reaches New 2024 High at $180B", Sentiment.POSITIVE, "DeFiPulse"),
        ("Binance Faces New Regulatory Scrutiny in Three EU Countries", Sentiment.NEGATIVE, "FT"),
        ("On-Chain Data Shows Long-Term Holders Reducing Positions Near ATH", Sentiment.NEUTRAL, "Glassnode"),
        ("NVIDIA Reports Record Revenue, Credits AI Chip Demand", Sentiment.POSITIVE, "CNBC"),
        ("Federal Reserve Minutes Hint at Possible Rate Cut in H2 2024", Sentiment.POSITIVE, "WSJ"),
    ]

    items = [
        NewsItem(
            title=title,
            sentiment=sentiment,
            source=source,
            categories=["crypto"],
            published_at=datetime.now(timezone.utc),
        )
        for title, sentiment, source in crypto_headlines
    ]

    pos = sum(1 for h in items if h.sentiment == Sentiment.POSITIVE)
    neg = sum(1 for h in items if h.sentiment == Sentiment.NEGATIVE)
    neu = len(items) - pos - neg

    return NewsState(
        crypto_headlines=items[:7],
        general_headlines=items[7:],
        trending_topics=["Bitcoin", "ETF", "Ethereum", "NVIDIA", "FederalReserve",
                         "Solana", "DeFi", "BTC", "AI", "SEC"],
        dominant_sentiment=Sentiment.POSITIVE,
        positive_count=pos,
        negative_count=neg,
        neutral_count=neu,
    )


def make_onchain_state() -> OnChainState:
    fast_gwei = random.uniform(18, 35)
    return OnChainState(
        gas=GasPrices(
            slow=round(fast_gwei * 0.55, 1),
            standard=round(fast_gwei * 0.75, 1),
            fast=round(fast_gwei, 1),
            base_fee=round(fast_gwei * 0.6, 2),
            suggest_base_fee=round(fast_gwei * 0.62, 2),
        ),
        network_congestion="moderate",
        last_block=19_500_000 + random.randint(0, 500),
        mempool_size_estimate=random.randint(80_000, 150_000),
    )


def make_world_state() -> WorldState:
    crypto = make_crypto_state()
    macro = make_macro_state()
    news = make_news_state()
    onchain = make_onchain_state()

    health = {
        name: SourceHealth(
            source=name,
            status=SourceStatus.OK,
            consecutive_failures=0,
            total_fetches=random.randint(50, 500),
            total_errors=random.randint(0, 3),
            avg_latency_ms=random.uniform(120, 800),
        )
        for name in ("crypto", "macro", "news", "onchain")
    }

    world = WorldState(
        crypto=crypto,
        macro=macro,
        news=news,
        onchain=onchain,
        source_health=health,
    )
    world.compute_summary()
    return world


# ── Rich rendering ────────────────────────────────────────────────────────────

def render_rich(world: WorldState) -> None:
    if not HAS_RICH:
        print(format_world_state_prompt(world))
        return

    c = Console(width=120)
    ts = world.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── Header ─────────────────────────────────────────────────────────────
    c.print()
    c.print(Panel(
        f"[bold cyan]ORACLE[/] — Real-Time World State Engine\n"
        f"[dim]{ts}[/]  |  "
        f"[bold]Mood:[/] [yellow]{world.overall_market_mood.upper()}[/]  |  "
        f"[bold]Freshness:[/] [green]{world.data_freshness_pct:.0f}%[/]",
        box=box.DOUBLE_EDGE,
        style="bold",
        border_style="cyan",
    ))

    # ── Key Signals ────────────────────────────────────────────────────────
    if world.key_signals:
        signals_text = "\n".join(f"  → {s}" for s in world.key_signals)
        c.print(Panel(
            f"[bold]KEY SIGNALS[/]\n{signals_text}",
            border_style="yellow",
        ))

    # ── Crypto table ───────────────────────────────────────────────────────
    if world.crypto:
        crypto = world.crypto
        tbl = Table(
            title=f"CRYPTO MARKETS — Top {len(crypto.coins[:10])} by Cap",
            box=box.SIMPLE_HEAD,
            border_style="bright_blue",
            show_header=True,
            header_style="bold bright_blue",
        )
        tbl.add_column("#", style="dim", width=4, justify="right")
        tbl.add_column("Coin", width=14)
        tbl.add_column("Price (USD)", justify="right", width=16)
        tbl.add_column("24h Δ", justify="right", width=10)
        tbl.add_column("7d Δ", justify="right", width=10)
        tbl.add_column("Market Cap", justify="right", width=14)

        for coin in crypto.coins[:10]:
            chg24 = coin.change_24h_pct or 0
            chg7 = coin.change_7d_pct or 0
            chg24_str = f"[green]+{chg24:.2f}%[/]" if chg24 >= 0 else f"[red]{chg24:.2f}%[/]"
            chg7_str = f"[green]+{chg7:.2f}%[/]" if chg7 >= 0 else f"[red]{chg7:.2f}%[/]"
            price = coin.price_usd
            if price >= 1000:
                price_str = f"${price:,.2f}"
            elif price >= 1:
                price_str = f"${price:.4f}"
            else:
                price_str = f"${price:.8f}"

            cap = coin.market_cap_usd or 0
            cap_str = (
                f"${cap/1e12:.2f}T" if cap >= 1e12
                else f"${cap/1e9:.2f}B" if cap >= 1e9
                else f"${cap/1e6:.2f}M"
            )

            tbl.add_row(
                str(coin.rank or "─"),
                f"[bold]{coin.symbol.upper()}[/] {coin.name[:8]}",
                price_str,
                chg24_str,
                chg7_str,
                cap_str,
            )

        if crypto.fear_greed:
            fg = crypto.fear_greed
            fg_color = "green" if fg.value > 60 else "red" if fg.value < 40 else "yellow"
            c.print(Panel(
                tbl,
                subtitle=(
                    f"Fear & Greed: [{fg_color}]{fg.value}/100 — {fg.category.value}[/]  |  "
                    f"BTC Dom: {crypto.btc_dominance_pct:.1f}%  |  "
                    f"Trend: {crypto.market_trend.value.upper()}  |  "
                    f"Gainers: {', '.join(crypto.top_gainers)}  |  "
                    f"Losers: {', '.join(crypto.top_losers)}"
                ),
                border_style="bright_blue",
            ))
        else:
            c.print(tbl)

    # ── Macro table ────────────────────────────────────────────────────────
    if world.macro:
        macro = world.macro
        tbl2 = Table(
            title="MACRO & EQUITIES",
            box=box.SIMPLE_HEAD,
            border_style="bright_magenta",
            header_style="bold bright_magenta",
        )
        tbl2.add_column("Ticker", width=14)
        tbl2.add_column("Name", width=28)
        tbl2.add_column("Price", justify="right", width=14)
        tbl2.add_column("Change", justify="right", width=10)

        all_tickers = {**macro.stocks, **macro.macro, **macro.crypto_yf}
        for sym, td in all_tickers.items():
            chg = td.change_pct or 0
            chg_str = f"[green]+{chg:.2f}%[/]" if chg >= 0 else f"[red]{chg:.2f}%[/]"
            c.print  # noop
            tbl2.add_row(
                f"[bold]{sym}[/]",
                td.name or sym,
                f"${td.price:,.2f}" if td.price else "N/A",
                chg_str,
            )

        c.print(Panel(
            tbl2,
            subtitle=(
                f"Risk: {macro.risk_sentiment.upper()}  |  "
                f"SPY Trend: {macro.spy_trend.value.upper()}  |  "
                f"Market: {'OPEN' if macro.market_open else 'CLOSED'}"
            ),
            border_style="bright_magenta",
        ))

    # ── News section ───────────────────────────────────────────────────────
    if world.news:
        news = world.news
        news_lines = []
        for i, item in enumerate((news.crypto_headlines + news.general_headlines)[:8], 1):
            icon = "📈" if item.sentiment == Sentiment.POSITIVE else "📉" if item.sentiment == Sentiment.NEGATIVE else "➡️"
            src = f"[dim][{item.source}][/]" if item.source else ""
            title = item.title[:80] + ("..." if len(item.title) > 80 else "")
            news_lines.append(f"  {i:>2}. {icon}  {title} {src}")

        trending_str = "  Trending: " + " · ".join(f"[cyan]#{t}[/]" for t in news.trending_topics[:6])

        total = news.positive_count + news.negative_count + news.neutral_count
        if total > 0:
            pos_pct = int(news.positive_count / total * 100)
            neg_pct = int(news.negative_count / total * 100)
            sentiment_str = (
                f"  Sentiment: [green]+{news.positive_count}[/] pos / "
                f"[red]-{news.negative_count}[/] neg / {news.neutral_count} neu "
                f"([green]{pos_pct}%[/] positive, [red]{neg_pct}%[/] negative)"
            )
        else:
            sentiment_str = ""

        c.print(Panel(
            "\n".join([sentiment_str, trending_str, ""] + news_lines),
            title="[bold]NEWS & SENTIMENT[/]",
            border_style="bright_green",
        ))

    # ── On-chain + Health side by side ────────────────────────────────────
    panels = []

    if world.onchain:
        oc = world.onchain
        congestion_colors = {"low": "green", "moderate": "yellow", "high": "orange1", "congested": "red"}
        cc = congestion_colors.get(oc.network_congestion, "white")
        gas_str = ""
        if oc.gas:
            g = oc.gas
            gas_str = (
                f"  Slow     : [dim]{g.slow:.1f} gwei[/]\n"
                f"  Standard : [yellow]{g.standard:.1f} gwei[/]\n"
                f"  Fast     : [bold]{g.fast:.1f} gwei[/]\n"
            )
            if g.base_fee:
                gas_str += f"  Base Fee : {g.base_fee:.2f} gwei\n"
        block_str = f"  Block    : [dim]#{oc.last_block:,}[/]\n" if oc.last_block else ""
        mempool_str = f"  Mempool  : ~{oc.mempool_size_estimate:,} pending\n" if oc.mempool_size_estimate else ""

        panels.append(Panel(
            f"  Congestion: [{cc}]{oc.network_congestion.upper()}[/]\n\n"
            f"  GAS PRICES (Gwei)\n"
            + gas_str + block_str + mempool_str,
            title="[bold]ETHEREUM ON-CHAIN[/]",
            border_style="bright_cyan",
        ))

    # Health
    health_lines = []
    status_icons = {SourceStatus.OK: "[green]✓[/]", SourceStatus.DEGRADED: "[yellow]⚠[/]",
                    SourceStatus.ERROR: "[red]✗[/]", SourceStatus.PENDING: "[dim]?[/]", SourceStatus.STALE: "[orange1]~[/]"}
    for name, h in world.source_health.items():
        icon = status_icons.get(h.status, "?")
        lat = f"{h.avg_latency_ms:.0f}ms" if h.avg_latency_ms else "─"
        up = f"{h.uptime_pct:.1f}%"
        health_lines.append(f"  {icon} [bold]{name:<10}[/] {lat:>8}  uptime {up}")

    panels.append(Panel(
        "\n".join(health_lines) + f"\n\n  [dim]Overall freshness: {world.data_freshness_pct:.0f}%[/]",
        title="[bold]SOURCE HEALTH[/]",
        border_style="bright_white",
    ))

    c.print(Columns(panels))
    c.print()


# ── Live mode (connect to running ORACLE) ─────────────────────────────────────

async def fetch_live_state(url: str) -> Optional[WorldState]:
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/state", timeout=10.0)
            resp.raise_for_status()
            return WorldState.model_validate(resp.json())
    except Exception as exc:
        if HAS_RICH:
            console.print(f"[red]Failed to connect to ORACLE at {url}: {exc}[/]")
        else:
            print(f"Failed to connect to ORACLE at {url}: {exc}")
        return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ORACLE Demo — Real-Time World State Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/demo.py                 # Simulated snapshot
  python scripts/demo.py --live          # Connect to localhost:8000
  python scripts/demo.py --live --url http://my-oracle:8000
  python scripts/demo.py --watch         # Refresh every 5 seconds
  python scripts/demo.py --json          # Raw JSON output
        """,
    )
    parser.add_argument("--live", action="store_true", help="Connect to running ORACLE instance")
    parser.add_argument("--url", default="http://localhost:8000", help="ORACLE API URL")
    parser.add_argument("--watch", action="store_true", help="Refresh every N seconds")
    parser.add_argument("--interval", type=int, default=5, help="Watch interval seconds")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    async def _run() -> None:
        if args.live:
            world = await fetch_live_state(args.url)
            if world is None:
                print("Falling back to simulated data...")
                world = make_world_state()
        else:
            world = make_world_state()

        if args.json:
            import json
            print(json.dumps(world.model_dump(mode="json"), indent=2))
            return

        if args.watch and HAS_RICH:
            from rich.live import Live
            try:
                while True:
                    if args.live:
                        world = await fetch_live_state(args.url) or make_world_state()
                    else:
                        world = make_world_state()
                    console.clear()
                    render_rich(world)
                    console.print(f"[dim]Auto-refreshing every {args.interval}s — Ctrl+C to quit[/]")
                    await asyncio.sleep(args.interval)
            except KeyboardInterrupt:
                console.print("\n[yellow]Demo stopped.[/]")
        else:
            render_rich(world)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
