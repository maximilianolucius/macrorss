import asyncio
import time
from datetime import UTC, datetime

import pytest

from macrorss.dispatcher import Dispatcher
from macrorss.models import NormalizedEvent


class SlowSink:
    def __init__(self):
        self.received = 0

    async def send(self, event):
        await asyncio.sleep(0.05)
        self.received += 1


def event():
    now = datetime.now(UTC)
    return NormalizedEvent(
        event_fingerprint="a" * 64,
        canonical_url="https://example.test/a",
        canonical_title="FOMC statement",
        institution="Federal Reserve",
        event_type="fomc",
        published_at=now,
        first_seen_at=now,
        first_source_id="fed-monetary",
        tags=("gold", "fx"),
        rank_gold=1,
        rank_fx=1,
    )


@pytest.mark.asyncio
async def test_emit_nowait_does_not_wait_for_slow_sink():
    sink = SlowSink()
    dispatcher = Dispatcher([sink], queue_size=8)
    await dispatcher.start()
    started = time.perf_counter()
    assert dispatcher.emit_nowait(event())
    elapsed = time.perf_counter() - started
    assert elapsed < 0.01
    await dispatcher.queue.join()
    assert sink.received == 1
    await dispatcher.close()


@pytest.mark.asyncio
async def test_bounded_queue_reports_drop():
    dispatcher = Dispatcher([], queue_size=1)
    # Worker is intentionally not started, so the first item fills the queue deterministically.
    assert dispatcher.emit_nowait(event())
    assert not dispatcher.emit_nowait(event())
