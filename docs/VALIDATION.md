# Validation plan

ORACLE's product thesis is not "aggregate many APIs." The thesis is that an agent
can consume external state without silently confusing live, cached, stale,
simulated, or unavailable evidence.

## Primary safety metric

**False-actionable rate:** percentage of observations marked `actionable=true`
when the evidence should have been stale, simulated, unavailable, or otherwise
outside policy.

Target for the deterministic benchmark: **0 false-actionable observations**.

## Executable benchmark corpus v0.1

The current v0.1 corpus contains 18 deterministic evidence-policy cases covering:

- fresh successful observations
- degraded/cached observations
- stale observations
- source errors with and without prior success
- pending sources with and without cached history
- missing domain state
- real on-chain evidence
- cached on-chain evidence
- stale on-chain evidence
- simulated on-chain evidence
- unavailable on-chain evidence

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

## Current regression evidence

The current test suite proves several contract-level properties:

- source health that crosses the age threshold is marked `STALE`;
- stale domain evidence is emitted with `actionable=false`;
- stale evidence carries reduced confidence;
- evidence-ledger fingerprints are deterministic for unchanged truth state;
- changing a domain truth status changes the evidence digest.

The executable v0.1 corpus is also regression-locked in CI. Current checkpoint:

- total cases: **18**
- unsafe / expected non-actionable cases: **11**
- false-actionable outcomes: **0**
- safe / expected actionable cases: **7**
- false-non-actionable outcomes: **0**
- policy outcome accuracy on this corpus: **18/18**

This is deterministic evidence-policy validation. It does not establish live-source factual accuracy, source uptime, or production data quality.

## Exit gate

ORACLE may be called an evidence layer only after the benchmark is reproducible
in CI and the false-actionable rate is zero on the labeled corpus.

Live source dogfood comes after the deterministic corpus. Live success rate alone
does not prove evidence correctness.
