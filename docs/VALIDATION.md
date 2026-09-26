# Validation plan

ORACLE's product thesis is not "aggregate many APIs." The thesis is that an agent
can consume external state without silently confusing live, cached, stale,
simulated, or unavailable evidence.

## Primary safety metric

**False-actionable rate:** percentage of observations marked `actionable=true`
when the evidence should have been stale, simulated, unavailable, or otherwise
outside policy.

Target for the deterministic benchmark: **0 false-actionable observations**.

## Benchmark corpus v0.1

Build a versioned fixture corpus covering:

- fresh successful observations
- cached data after transient collector failure
- stale data after age threshold
- repeated source failures
- missing source data
- explicitly simulated on-chain demo data
- mixed-provenance on-chain snapshots
- clock/age boundary cases
- collector recovery after degraded/stale state
- conflicting/cross-source observations

## Metrics

- false-actionable rate
- stale-detection recall
- simulated-data rejection recall
- unavailable-data rejection recall
- trusted-data coverage
- evidence classification stability
- age-boundary correctness
- recovery correctness
- API/prompt consistency

## Exit gate

ORACLE may be called an evidence layer only after the benchmark is reproducible
in CI and the false-actionable rate is zero on the labeled corpus.

Live source dogfood comes after the deterministic corpus. Live success rate alone
does not prove evidence correctness.
