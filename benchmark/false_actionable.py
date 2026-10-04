"""Deterministic false-actionable benchmark for ORACLE evidence policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from oracle.models import (
    CryptoState,
    DataProvenance,
    MacroState,
    NewsState,
    OnChainState,
    SourceHealth,
    SourceStatus,
    WorldState,
)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class EvidenceCase:
    label: str
    domain: str
    state: object | None
    health: SourceHealth | None
    expected_provenance: DataProvenance
    expected_actionable: bool


def _health(
    source: str,
    status: SourceStatus,
    *,
    has_last_success: bool = True,
) -> SourceHealth:
    return SourceHealth(
        source=source,
        status=status,
        last_success=NOW - timedelta(minutes=5) if has_last_success else None,
        last_failure=NOW - timedelta(minutes=1)
        if status == SourceStatus.ERROR
        else None,
    )


def _state(domain: str, provenance: DataProvenance | None = None):
    observed = NOW - timedelta(seconds=30)
    if domain == "crypto":
        return CryptoState(updated_at=observed)
    if domain == "macro":
        return MacroState(updated_at=observed)
    if domain == "news":
        return NewsState(updated_at=observed)
    if domain == "onchain":
        p = provenance or DataProvenance.UNAVAILABLE
        return OnChainState(
            updated_at=observed,
            provenance={
                "gas": p,
                "last_block": p,
                "mempool_size_estimate": p,
            },
        )
    raise ValueError(f"unknown domain: {domain}")


def build_cases() -> list[EvidenceCase]:
    return [
        EvidenceCase(
            "crypto_ok",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.OK),
            DataProvenance.REAL,
            True,
        ),
        EvidenceCase(
            "crypto_degraded_cache",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.DEGRADED),
            DataProvenance.CACHED,
            True,
        ),
        EvidenceCase(
            "crypto_stale",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.STALE),
            DataProvenance.STALE,
            False,
        ),
        EvidenceCase(
            "crypto_error_with_history",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.ERROR, has_last_success=True),
            DataProvenance.STALE,
            False,
        ),
        EvidenceCase(
            "crypto_error_without_history",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.ERROR, has_last_success=False),
            DataProvenance.UNAVAILABLE,
            False,
        ),
        EvidenceCase(
            "crypto_pending_with_cache",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.PENDING, has_last_success=True),
            DataProvenance.CACHED,
            True,
        ),
        EvidenceCase(
            "crypto_pending_without_cache",
            "crypto",
            _state("crypto"),
            _health("crypto", SourceStatus.PENDING, has_last_success=False),
            DataProvenance.UNAVAILABLE,
            False,
        ),
        EvidenceCase(
            "crypto_missing_state",
            "crypto",
            None,
            _health("crypto", SourceStatus.OK),
            DataProvenance.UNAVAILABLE,
            False,
        ),
        EvidenceCase(
            "macro_ok",
            "macro",
            _state("macro"),
            _health("macro", SourceStatus.OK),
            DataProvenance.REAL,
            True,
        ),
        EvidenceCase(
            "macro_stale",
            "macro",
            _state("macro"),
            _health("macro", SourceStatus.STALE),
            DataProvenance.STALE,
            False,
        ),
        EvidenceCase(
            "news_degraded_cache",
            "news",
            _state("news"),
            _health("news", SourceStatus.DEGRADED),
            DataProvenance.CACHED,
            True,
        ),
        EvidenceCase(
            "news_error_without_history",
            "news",
            _state("news"),
            _health("news", SourceStatus.ERROR, has_last_success=False),
            DataProvenance.UNAVAILABLE,
            False,
        ),
        EvidenceCase(
            "onchain_real",
            "onchain",
            _state("onchain", DataProvenance.REAL),
            _health("onchain", SourceStatus.OK),
            DataProvenance.REAL,
            True,
        ),
        EvidenceCase(
            "onchain_cached",
            "onchain",
            _state("onchain", DataProvenance.CACHED),
            _health("onchain", SourceStatus.DEGRADED),
            DataProvenance.CACHED,
            True,
        ),
        EvidenceCase(
            "onchain_stale",
            "onchain",
            _state("onchain", DataProvenance.STALE),
            _health("onchain", SourceStatus.OK),
            DataProvenance.STALE,
            False,
        ),
        EvidenceCase(
            "onchain_simulated",
            "onchain",
            _state("onchain", DataProvenance.SIMULATED),
            _health("onchain", SourceStatus.OK),
            DataProvenance.SIMULATED,
            False,
        ),
        EvidenceCase(
            "onchain_unavailable",
            "onchain",
            _state("onchain", DataProvenance.UNAVAILABLE),
            _health("onchain", SourceStatus.OK),
            DataProvenance.UNAVAILABLE,
            False,
        ),
        EvidenceCase(
            "onchain_missing_state",
            "onchain",
            None,
            _health("onchain", SourceStatus.OK),
            DataProvenance.UNAVAILABLE,
            False,
        ),
    ]


def _world_for(case: EvidenceCase) -> WorldState:
    kwargs = {
        "crypto": None,
        "macro": None,
        "news": None,
        "onchain": None,
        "source_health": {},
    }
    kwargs[case.domain] = case.state
    if case.health is not None:
        kwargs["source_health"] = {case.domain: case.health}
    return WorldState(**kwargs)


def run_benchmark() -> dict:
    rows = []
    correct = 0
    false_actionable = 0
    false_non_actionable = 0
    unsafe_cases = 0
    safe_cases = 0

    for case in build_cases():
        world = _world_for(case)
        world.compute_evidence(now=NOW)
        observed = world.evidence[case.domain]

        provenance_ok = observed.provenance == case.expected_provenance
        actionable_ok = observed.actionable is case.expected_actionable
        passed = provenance_ok and actionable_ok
        correct += int(passed)

        if case.expected_actionable:
            safe_cases += 1
            false_non_actionable += int(not observed.actionable)
        else:
            unsafe_cases += 1
            false_actionable += int(observed.actionable)

        rows.append(
            {
                "label": case.label,
                "domain": case.domain,
                "expected_provenance": case.expected_provenance.value,
                "actual_provenance": observed.provenance.value,
                "expected_actionable": case.expected_actionable,
                "actual_actionable": observed.actionable,
                "confidence": observed.confidence,
                "correct": passed,
            }
        )

    total = len(rows)
    return {
        "cases": total,
        "policy_correct": correct,
        "policy_accuracy": correct / total,
        "unsafe_cases": unsafe_cases,
        "false_actionable": false_actionable,
        "false_actionable_rate": false_actionable / unsafe_cases,
        "safe_cases": safe_cases,
        "false_non_actionable": false_non_actionable,
        "false_non_actionable_rate": false_non_actionable / safe_cases,
        "results": rows,
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
