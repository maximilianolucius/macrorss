from datetime import UTC, datetime

from macrorss.models import RawItem, SourceConfig
from macrorss.normalizer import canonicalize_url, normalize_event


def raw(source_id, url, title):
    now = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
    return RawItem(
        source_id=source_id,
        guid=url,
        guid_hash="a" * 64,
        url=url,
        title=title,
        raw_published_at=now.isoformat(),
        published_at=now,
        first_seen_at=now,
    )


def test_canonical_url_strips_tracking():
    assert canonicalize_url("https://www.example.com/a/?utm_source=x&b=2") == "https://example.com/a?b=2"


def test_fed_cross_source_same_url_same_event():
    url = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"
    one = SourceConfig(id="fed-monetary", name="Fed", url="https://x", tags=("gold",), rank_gold=1)
    two = SourceConfig(id="fed-press-all", name="Fed", url="https://y", tags=("fx",), rank_fx=1)
    event_one = normalize_event(one, raw(one.id, url, "Federal Reserve issues FOMC statement"))
    event_two = normalize_event(two, raw(two.id, url + "?utm_source=rss", "Federal Reserve issues FOMC statement"))
    assert event_one.event_fingerprint == event_two.event_fingerprint
    assert event_one.event_type == "fomc"
