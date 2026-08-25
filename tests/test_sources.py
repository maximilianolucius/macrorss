from pathlib import Path

from macrorss.models import SourceConfig
from macrorss.sources.feed import FeedSourceParser
from macrorss.sources.html import TreasuryPressParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_feed_parser_stdlib_compatible():
    source = SourceConfig(id="fed-monetary", name="Fed", url="https://example.test/feed")
    items = FeedSourceParser().parse(source, (FIXTURES / "fed_feed.xml").read_bytes(), 0.0)
    assert len(items) == 1
    item = items[0]
    assert item.title == "Federal Reserve issues FOMC statement"
    assert item.guid_hash and len(item.guid_hash) == 64
    assert item.published_at is not None
    assert item.published_at.isoformat().startswith("2026-07-29T18:00:00")


def test_treasury_parser_dedups_listing_links():
    source = SourceConfig(
        id="treasury-press",
        name="Treasury",
        url="https://home.treasury.gov/news/press-releases",
        transport="html",
        parser="treasury_press",
    )
    items = TreasuryPressParser().parse(source, (FIXTURES / "treasury_press.html").read_bytes(), 0.0)
    assert len(items) == 2
    assert items[0].url == "https://home.treasury.gov/news/press-releases/sb0607"
    assert "Buybacks" in items[0].title


def test_treasury_parser_ignores_navigation_and_pagination():
    """Regression: the listing page links to its own categories and to pagination.

    Those URLs are constant, so capturing them produced items that were deduplicated
    away forever after the first fetch while the real releases were never captured.
    """
    source = SourceConfig(
        id="treasury-press",
        name="Treasury",
        url="https://home.treasury.gov/news/press-releases",
        transport="html",
        parser="treasury_press",
    )
    items = TreasuryPressParser().parse(source, (FIXTURES / "treasury_press.html").read_bytes(), 0.0)
    urls = [item.url for item in items]
    assert len(items) == 2
    assert all(url is not None and url.rsplit("/", 1)[-1].startswith("sb") for url in urls)
    for rejected in ("statements-remarks", "readouts", "testimonies", "page="):
        assert not any(rejected in (url or "") for url in urls)


def _bls_source(dedup: str | None) -> SourceConfig:
    options = {"dedup": dedup} if dedup else {}
    return SourceConfig(
        id="bls-latest",
        name="BLS",
        url="https://www.bls.gov/feed/bls_latest.rss",
        parser_options=options,
    )


def _bls_body(cpi: str) -> bytes:
    template = (FIXTURES / "bls_dashboard.xml").read_bytes()
    return template.replace(b"+0.1% in Jul 2026", cpi.encode("utf-8"))


def test_content_dedup_detects_dashboard_feed_updates():
    """Regression: BLS ships ONE item whose link never changes.

    With guid-only identity every release after the first was dropped as a duplicate,
    so CPI and NFP would never have alerted again.
    """
    parser = FeedSourceParser()
    first = parser.parse(_bls_source("content"), _bls_body("+0.1% in Jul 2026"), 0.0)
    second = parser.parse(_bls_source("content"), _bls_body("+0.4% in Aug 2026"), 0.0)
    assert len(first) == len(second) == 1
    assert first[0].guid == second[0].guid, "guid is constant; that is the whole problem"
    assert first[0].guid_hash != second[0].guid_hash


def test_content_dedup_is_stable_when_content_is_unchanged():
    parser = FeedSourceParser()
    body = _bls_body("+0.1% in Jul 2026")
    first = parser.parse(_bls_source("content"), body, 0.0)
    second = parser.parse(_bls_source("content"), body, 0.0)
    assert first[0].guid_hash == second[0].guid_hash


def test_guid_dedup_remains_the_default():
    """Per-release feeds must keep guid identity: an edited headline is not a new event."""
    parser = FeedSourceParser()
    first = parser.parse(_bls_source(None), _bls_body("+0.1% in Jul 2026"), 0.0)
    second = parser.parse(_bls_source(None), _bls_body("+0.4% in Aug 2026"), 0.0)
    assert first[0].guid_hash == second[0].guid_hash
