from datetime import datetime, timedelta, timezone

from oracle.models import SourceStatus
from oracle.workers.refresh_engine import RefreshEngine


def test_old_success_is_marked_stale():
    engine = RefreshEngine()
    health = engine._health["crypto"]
    health.status = SourceStatus.OK
    now = datetime.now(timezone.utc)
    health.last_success = now - timedelta(
        seconds=engine._stale_after_seconds("crypto") + 1
    )

    engine._refresh_staleness(now)

    assert health.status == SourceStatus.STALE


def test_recent_success_remains_ok():
    engine = RefreshEngine()
    health = engine._health["news"]
    health.status = SourceStatus.OK
    now = datetime.now(timezone.utc)
    health.last_success = now - timedelta(
        seconds=engine._stale_after_seconds("news") / 2
    )

    engine._refresh_staleness(now)

    assert health.status == SourceStatus.OK


def test_error_status_is_not_downgraded_to_stale():
    engine = RefreshEngine()
    health = engine._health["onchain"]
    health.status = SourceStatus.ERROR
    health.consecutive_failures = 10
    now = datetime.now(timezone.utc)
    health.last_success = now - timedelta(days=1)

    engine._refresh_staleness(now)

    assert health.status == SourceStatus.ERROR


def test_stale_health_becomes_non_actionable_world_evidence():
    from oracle.models import CryptoState, SourceHealth, WorldState

    world = WorldState(
        crypto=CryptoState(),
        source_health={
            "crypto": SourceHealth(
                source="crypto",
                status=SourceStatus.STALE,
                last_success=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        },
    )
    world.compute_summary()

    assert world.evidence["crypto"].provenance.value == "stale"
    assert world.evidence["crypto"].actionable is False
    assert world.evidence["crypto"].confidence < 0.5
