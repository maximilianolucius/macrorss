import os
from datetime import UTC, datetime

import pytest

from macrorss.config import DatabaseConfig
from macrorss.models import NormalizedEvent, ObservationRecord, RawItem, SourceState
from macrorss.store import MySQLStore

pytestmark = pytest.mark.skipif(not os.getenv("MACRORSS_TEST_MYSQL"), reason="requires MySQL integration service")


def sample_record():
    now = datetime(2026, 8, 25, 17, 0, tzinfo=UTC)
    raw = RawItem(
        source_id="fed-monetary",
        guid="https://example.test/fomc",
        guid_hash="11" * 32,
        url="https://example.test/fomc",
        title="Federal Reserve issues FOMC statement",
        raw_published_at=now.isoformat(),
        published_at=now,
        first_seen_at=now,
        payload={"fixture": True},
    )
    event = NormalizedEvent(
        event_fingerprint="22" * 32,
        canonical_url=raw.url,
        canonical_title=raw.title,
        institution="Federal Reserve",
        event_type="fomc",
        published_at=now,
        first_seen_at=now,
        first_source_id=raw.source_id,
        tags=("gold", "fx"),
        rank_gold=1,
        rank_fx=1,
    )
    return ObservationRecord(raw=raw, event=event, emitted=True)


@pytest.mark.asyncio
async def test_mysql_schema_and_replay_idempotence():
    store = MySQLStore(DatabaseConfig.from_env(require_password=True))
    try:
        details = await store.check_schema()
        assert "events" in details["tables"]
        record = sample_record()
        assert await store.persist_records([record]) == 1
        assert await store.persist_records([record]) == 1
        assert store.pool is not None
        async with store.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*) FROM raw_items WHERE source_id='fed-monetary'")
                assert (await cursor.fetchone())[0] == 1
                await cursor.execute("SELECT COUNT(*) FROM events WHERE event_fingerprint=UNHEX(%s)", (record.event.event_fingerprint,))
                assert (await cursor.fetchone())[0] == 1
                await cursor.execute("SELECT COUNT(*) FROM event_observations")
                assert (await cursor.fetchone())[0] == 1
        state = SourceState(source_id="fed-monetary", etag='"abc"', last_status=200)
        await store.upsert_feed_state(state)
        await store.upsert_feed_state(state)
    finally:
        await store.close()
