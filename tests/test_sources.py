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
