import random
from datetime import UTC, datetime

from macrorss.models import PollPolicy, SourceConfig
from macrorss.scheduler import AdaptiveScheduler, EventCalendar, ScheduledEvent


def source():
    return SourceConfig(
        id="bls-latest",
        name="BLS",
        url="https://x",
        poll=PollPolicy(base_seconds=60, pre_window_seconds=5, burst_seconds=1, post_window_seconds=5, jitter_fraction=0),
    )


def test_scheduler_normal_pre_burst_post_normal():
    t0 = datetime(2026, 9, 11, 12, 30, tzinfo=UTC)
    calendar = EventCalendar([ScheduledEvent("cpi", t0, ("bls-latest",))])
    scheduler = AdaptiveScheduler(calendar, rng=random.Random(1))
    src = source()
    assert scheduler.interval(src, datetime(2026, 9, 11, 12, 0, tzinfo=UTC)) == 60
    assert scheduler.interval(src, datetime(2026, 9, 11, 12, 26, tzinfo=UTC)) == 5
    assert scheduler.interval(src, datetime(2026, 9, 11, 12, 29, 40, tzinfo=UTC)) == 1
    assert scheduler.interval(src, datetime(2026, 9, 11, 12, 31, tzinfo=UTC)) == 1
    assert scheduler.interval(src, datetime(2026, 9, 11, 12, 35, tzinfo=UTC)) == 5
    assert scheduler.interval(src, datetime(2026, 9, 11, 13, 1, tzinfo=UTC)) == 60
