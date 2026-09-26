"""
ORACLE Context Formatter
========================
Transforms a WorldState snapshot into a rich, prompt-ready context string
optimised for injection into Hermes agent system prompts.

The output is deliberately terse and information-dense — every line is
a signal, not filler. The formatter also produces a JSON-ready summary
dict for programmatic consumption.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from oracle.models import (
    CryptoState,
    DataProvenance,
    MacroState,
    NewsState,
    OnChainState,
    Sentiment,
    SourceStatus,
    WorldState,
)

_DIVIDER = "─" * 60
_THIN = "·" * 60


def _fmt_change(pct: Optional[float]) -> str:
    """Format a percentage change with arrow and colour hint."""
    if pct is None:
        return "N/A"
    arrow = "▲" if pct >= 0 else "▼"
    return f"{arrow}{abs(pct):.2f}%"


def _fmt_price(price: Optional[float], decimals: int = 2) -> str:
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"${price:,.{decimals}f}"
    elif price >= 1:
        return f"${price:.{decimals}f}"
    return f"${price:.6f}"


def _fmt_large(value: Optional[float]) -> str:
    """Format large numbers as $1.23T / $456.7B / $12.3M."""
    if value is None:
        return "N/A"
    if value >= 1e12:
        return f"${value/1e12:.2f}T"
    elif value >= 1e9:
        return f"${value/1e9:.2f}B"
    elif value >= 1e6:
        return f"${value/1e6:.2f}M"
    return f"${value:,.0f}"


def _sentiment_icon(s: Sentiment) -> str:
    icons = {Sentiment.POSITIVE: "📈", Sentiment.NEGATIVE: "📉", Sentiment.NEUTRAL: "➡️"}
    return icons.get(s, "➡️")


def format_crypto_section(crypto: Optional[CryptoState]) -> str:
    if not crypto:
        return "CRYPTO: [unavailable]\n"

    lines = [f"{'CRYPTO MARKETS':^60}", _DIVIDER]

    # Fear & Greed
    if crypto.fear_greed:
        fg = crypto.fear_greed
        prev = f" (prev: {fg.previous_value})" if fg.previous_value else ""
        lines.append(
            f"  Fear & Greed Index : {fg.value}/100 — {fg.category.value}{prev}"
        )

    # Market metrics
    lines.append(f"  Market Cap         : {_fmt_large(crypto.total_market_cap_usd)}")
    lines.append(f"  24h Volume         : {_fmt_large(crypto.total_volume_24h_usd)}")
    lines.append(f"  BTC Dominance      : {crypto.btc_dominance_pct:.1f}%" if crypto.btc_dominance_pct else "  BTC Dominance      : N/A")
    lines.append(f"  Market Trend       : {crypto.market_trend.value.upper()}")

    # Top 10 coins table
    lines.append("")
    lines.append(f"  {'#':<3} {'Symbol':<8} {'Price':>14} {'24h':>9} {'7d':>9} {'Mkt Cap':>12}")
    lines.append(f"  {'─'*3} {'─'*8} {'─'*14} {'─'*9} {'─'*9} {'─'*12}")

    for coin in crypto.coins[:10]:
        rank = f"{coin.rank}" if coin.rank else "─"
        lines.append(
            f"  {rank:<3} {coin.symbol.upper():<8} "
            f"{_fmt_price(coin.price_usd):>14} "
            f"{_fmt_change(coin.change_24h_pct):>9} "
            f"{_fmt_change(coin.change_7d_pct):>9} "
            f"{_fmt_large(coin.market_cap_usd):>12}"
        )

    if crypto.top_gainers:
        lines.append(f"\n  Top Gainers : {', '.join(crypto.top_gainers)}")
    if crypto.top_losers:
        lines.append(f"  Top Losers  : {', '.join(crypto.top_losers)}")

    return "\n".join(lines) + "\n"


def format_macro_section(macro: Optional[MacroState]) -> str:
    if not macro:
        return "MACRO: [unavailable]\n"

    lines = [f"{'MACRO & EQUITIES':^60}", _DIVIDER]
    lines.append(f"  Market Open        : {'YES' if macro.market_open else 'NO'}")
    lines.append(f"  Risk Sentiment     : {macro.risk_sentiment.upper()}")
    lines.append(f"  SPY Trend          : {macro.spy_trend.value.upper()}")
    lines.append("")

    all_tickers = {**macro.stocks, **macro.macro, **macro.crypto_yf}
    for sym, td in all_tickers.items():
        change_str = _fmt_change(td.change_pct)
        price_str = _fmt_price(td.price) if td.price else "N/A"
        name_short = (td.name or sym)[:28]
        lines.append(f"  {sym:<12} {price_str:>12} {change_str:>9}  {name_short}")

    return "\n".join(lines) + "\n"


def format_news_section(news: Optional[NewsState]) -> str:
    if not news:
        return "NEWS: [unavailable]\n"

    lines = [f"{'NEWS & SENTIMENT':^60}", _DIVIDER]

    total = news.positive_count + news.negative_count + news.neutral_count
    if total > 0:
        pos_pct = int(news.positive_count / total * 100)
        neg_pct = int(news.negative_count / total * 100)
        lines.append(
            f"  Headline Sentiment : +{news.positive_count} pos / "
            f"-{news.negative_count} neg / ~{news.neutral_count} neu "
            f"({pos_pct}% ↑ / {neg_pct}% ↓)"
        )
        lines.append(f"  Dominant Mood      : {news.dominant_sentiment.value.upper()}")

    if news.trending_topics:
        lines.append(f"  Trending           : {', '.join(news.trending_topics[:6])}")

    lines.append("")
    all_headlines = (news.crypto_headlines + news.general_headlines)[:10]
    for i, item in enumerate(all_headlines, 1):
        icon = _sentiment_icon(item.sentiment)
        src = f"[{item.source}]" if item.source else ""
        title = item.title[:70] + ("..." if len(item.title) > 70 else "")
        lines.append(f"  {i:>2}. {icon} {title} {src}")

    return "\n".join(lines) + "\n"


def format_onchain_section(onchain: Optional[OnChainState]) -> str:
    if not onchain:
        return "ON-CHAIN: [unavailable]\n"

    lines = [f"{'ETHEREUM ON-CHAIN':^60}", _DIVIDER]
    lines.append(f"  Network Congestion : {onchain.network_congestion.upper()}")

    def provenance_label(field: str) -> str:
        state = onchain.provenance.get(field, DataProvenance.UNAVAILABLE)
        return f"[{state.value.upper()}]"

    if onchain.gas:
        g = onchain.gas
        lines.append(f"  Gas (Gwei) {provenance_label('gas')}:")
        lines.append(f"    Slow             : {g.slow:.1f}")
        lines.append(f"    Standard         : {g.standard:.1f}")
        lines.append(f"    Fast             : {g.fast:.1f}")
        if g.base_fee:
            lines.append(f"    Base Fee         : {g.base_fee:.2f}")

    if onchain.last_block:
        lines.append(
            f"  Latest Block       : #{onchain.last_block:,} "
            f"{provenance_label('last_block')}"
        )
    if onchain.mempool_size_estimate:
        lines.append(
            f"  Mempool (est.)     : {onchain.mempool_size_estimate:,} pending txs "
            f"{provenance_label('mempool_size_estimate')}"
        )
    if onchain.provenance_note:
        lines.append(f"  Provenance note    : {onchain.provenance_note}")

    return "\n".join(lines) + "\n"



def format_evidence_section(world: WorldState) -> str:
    """Render the machine-readable evidence ledger in a human-scannable form."""
    lines = [f"{'EVIDENCE LEDGER':^60}", _DIVIDER]
    for name in ("crypto", "macro", "news", "onchain"):
        record = world.evidence.get(name)
        if record is None:
            lines.append(f"  ? {name:<12} UNAVAILABLE")
            continue
        age = (
            f"{record.age_seconds:.0f}s old"
            if record.age_seconds is not None
            else "age unknown"
        )
        action = "ACTIONABLE" if record.actionable else "DO NOT ACT"
        lines.append(
            f"  {name:<12} {record.provenance.value.upper():<11} "
            f"conf={record.confidence:.2f}  {age:<12}  {action}"
        )
        if record.note:
            lines.append(f"    note: {record.note}")
    lines.append(f"\n  Trusted domains: {world.trusted_data_pct:.0f}%")
    return "\n".join(lines) + "\n"


def format_health_section(world: WorldState) -> str:
    lines = [f"{'DATA SOURCE HEALTH':^60}", _DIVIDER]
    status_icons = {
        SourceStatus.OK: "✓",
        SourceStatus.DEGRADED: "⚠",
        SourceStatus.STALE: "~",
        SourceStatus.ERROR: "✗",
        SourceStatus.PENDING: "?",
    }
    for name, health in world.source_health.items():
        icon = status_icons.get(health.status, "?")
        latency = f"{health.avg_latency_ms:.0f}ms" if health.avg_latency_ms else "─"
        fails = f"fails:{health.consecutive_failures}" if health.consecutive_failures else ""
        lines.append(f"  {icon} {name:<12} {health.status.value:<10} {latency:>8}  {fails}")

    lines.append(f"\n  Freshness: {world.data_freshness_pct:.0f}% sources healthy")
    return "\n".join(lines) + "\n"


def format_world_state_prompt(world: WorldState) -> str:
    """
    Returns a prompt-ready multi-line context string for Hermes injection.

    Format:
    ╔══════════════════════════════════════════════════════╗
    ║        ORACLE WORLD STATE — 2024-01-15 14:32 UTC     ║
    ╚══════════════════════════════════════════════════════╝
    [key signals]
    [crypto section]
    [macro section]
    [news section]
    [onchain section]
    [health]
    """
    ts = world.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    header_title = f"ORACLE WORLD STATE — {ts}"
    border = "═" * (len(header_title) + 4)

    sections = [
        f"╔{border}╗",
        f"║  {header_title}  ║",
        f"╚{border}╝",
        "",
        f"  Mood: {world.overall_market_mood.upper()}  |  "
        f"Freshness: {world.data_freshness_pct:.0f}%  |  "
        f"Trusted data: {world.trusted_data_pct:.0f}%",
        "",
    ]

    if world.key_signals:
        sections.append("  KEY SIGNALS:")
        for sig in world.key_signals:
            sections.append(f"    → {sig}")
        sections.append("")

    sections.append(_DIVIDER)
    sections.append(format_evidence_section(world))
    sections.append(format_crypto_section(world.crypto))
    sections.append(format_macro_section(world.macro))
    sections.append(format_news_section(world.news))
    sections.append(format_onchain_section(world.onchain))
    sections.append(format_health_section(world))

    return "\n".join(sections)



def evidence_ledger_digest(world: WorldState) -> str:
    """Return a canonical digest for the agent-facing evidence ledger."""
    payload = {
        "trusted_data_pct": world.trusted_data_pct,
        "domains": {
            name: record.model_dump(mode="json")
            for name, record in sorted(world.evidence.items())
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def format_world_state_summary(world: WorldState) -> dict:
    """
    Returns a compact JSON-serialisable summary dict for programmatic use
    (e.g. Hermes tool call responses, logging, monitoring).
    """
    btc = world.crypto.get_coin("btc") if world.crypto else None
    spy = world.macro.stocks.get("SPY") if world.macro else None
    vix = world.macro.macro.get("^VIX") if world.macro else None

    return {
        "timestamp": world.generated_at.isoformat(),
        "mood": world.overall_market_mood,
        "freshness_pct": world.data_freshness_pct,
        "trusted_data_pct": world.trusted_data_pct,
        "evidence_digest": evidence_ledger_digest(world),
        "evidence": {
            name: record.model_dump(mode="json")
            for name, record in world.evidence.items()
        },
        "key_signals": world.key_signals,
        "btc": {
            "price": btc.price_usd if btc else None,
            "change_24h_pct": btc.change_24h_pct if btc else None,
        },
        "fear_greed": {
            "value": world.crypto.fear_greed.value if world.crypto and world.crypto.fear_greed else None,
            "category": world.crypto.fear_greed.category.value if world.crypto and world.crypto.fear_greed else None,
        },
        "spy": {
            "price": spy.price if spy else None,
            "change_pct": spy.change_pct if spy else None,
        },
        "vix": vix.price if vix else None,
        "eth_gas_fast": world.onchain.gas.fast if world.onchain and world.onchain.gas else None,
        "onchain_provenance": (
            {k: v.value for k, v in world.onchain.provenance.items()}
            if world.onchain else {}
        ),
        "news_sentiment": world.news.dominant_sentiment.value if world.news else None,
        "top_crypto_headlines": [
            h.title for h in (world.news.crypto_headlines[:3] if world.news else [])
        ],
    }
