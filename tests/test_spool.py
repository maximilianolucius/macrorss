import json
from datetime import UTC, datetime

from macrorss.models import NormalizedEvent, ObservationRecord, RawItem
from macrorss.spool import SegmentedSpool


def record(index=1, emitted=True):
    now = datetime(2026, 8, 25, 17, 0, tzinfo=UTC)
    raw = RawItem(
        source_id="fed-monetary",
        guid=f"guid-{index}",
        guid_hash=f"{index:064x}",
        url=f"https://example.test/{index}",
        title=f"Event {index}",
        raw_published_at=now.isoformat(),
        published_at=now,
        first_seen_at=now,
        payload={"n": index},
    )
    event = NormalizedEvent(
        event_fingerprint=f"{index + 100:064x}",
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
    return ObservationRecord(raw=raw, event=event, emitted=emitted, latencies={"hot_path_ms": 2.0})


def test_spool_write_seal_read_archive_and_seed(tmp_path):
    spool = SegmentedSpool(tmp_path / "spool", segment_bytes=1024, max_age_seconds=1, fsync_every=1)
    spool.append(record(1))
    ready = spool.seal()
    assert ready is not None and ready.suffix == ".ready"
    records = spool.read_segment(ready)
    assert records[0].raw.guid == "guid-1"
    done = spool.archive(ready)
    assert done.exists()
    docs, events, alerts = spool.seed_keys()
    assert f"fed-monetary:{record(1).raw.guid_hash}" in docs
    assert record(1).event.event_fingerprint in events
    assert record(1).event.event_fingerprint in alerts


def test_recovery_discards_only_partial_final_record(tmp_path):
    root = tmp_path / "spool"
    root.mkdir()
    valid = json.dumps(record(1).to_json()).encode() + b"\n"
    torn = b'{"schema":1,"raw":'
    path = root / "000000000001.open"
    path.write_bytes(valid + torn)
    spool = SegmentedSpool(root, segment_bytes=1024, max_age_seconds=1, fsync_every=1)
    ready = spool.ready_segments()
    assert len(ready) == 1
    records = spool.read_segment(ready[0])
    assert len(records) == 1
    assert records[0].raw.guid == "guid-1"


def test_replay_is_readable_multiple_times(tmp_path):
    spool = SegmentedSpool(tmp_path / "spool", segment_bytes=1024, max_age_seconds=1, fsync_every=1)
    spool.append(record(1))
    ready = spool.seal()
    assert ready is not None
    assert spool.read_segment(ready)[0].event.event_fingerprint == spool.read_segment(ready)[0].event.event_fingerprint


def test_concurrent_spool_appends_are_not_corrupted(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    spool = SegmentedSpool(
        tmp_path / "spool",
        segment_bytes=10 * 1024 * 1024,
        max_age_seconds=60,
        fsync_every=1,
    )
    records = [record(index) for index in range(1, 101)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(spool.append, records))
    ready = spool.seal()
    assert ready is not None
    recovered = spool.read_segment(ready)
    assert len(recovered) == 100
    assert len({item.raw.guid_hash for item in recovered}) == 100
