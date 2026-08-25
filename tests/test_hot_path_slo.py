import statistics
import time
from datetime import UTC, datetime, timedelta

import pytest

from macrorss.dedup import Deduplicator
from macrorss.dispatcher import Dispatcher
from macrorss.models import RawItem, SourceConfig
from macrorss.normalizer import normalize_event


@pytest.mark.asyncio
async def test_local_hot_path_p99_below_500ms():
    source = SourceConfig(
        id="fed-monetary",
        name="Federal Reserve",
        url="https://example.test/feed",
        tags=("gold", "fx"),
        rank_gold=1,
        rank_fx=1,
    )
    dispatcher = Dispatcher([], queue_size=4096)
    dedup = Deduplicator()
    samples = []
    base = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
    for i in range(1000):
        now = base + timedelta(minutes=i)
        raw = RawItem(
            source_id=source.id,
            guid=f"g-{i}",
            guid_hash=f"{i:064x}",
            url=f"https://example.test/release/{i}",
            title=f"Federal Reserve issues FOMC statement {i}",
            raw_published_at=now.isoformat(),
            published_at=now,
            first_seen_at=now,
        )
        started = time.perf_counter()
        assert dedup.is_new_document(raw.source_id, raw.guid_hash)
        event = normalize_event(source, raw)
        assert dedup.is_new_event(event.event_fingerprint)
        assert dispatcher.emit_nowait(event)
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    p99 = ordered[int(0.99 * len(ordered)) - 1]
    assert p99 < 500.0
    # Avoid an unused-import false positive under strict linters and give a useful sanity bound.
    assert statistics.median(samples) < p99
