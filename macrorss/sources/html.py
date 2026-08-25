"""HTML source adapters for official pages without usable RSS."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from macrorss.models import RawItem, SourceConfig, utcnow


class _TreasuryLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_map = dict(attrs)
        href = attrs_map.get("href")
        if href and "/news/press-releases/" in href:
            self._href = href
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            title = " ".join("".join(self._chunks).split())
            if title:
                self.links.append((self._href, title))
            self._href = None
            self._chunks = []


class TreasuryPressParser:
    """Extract press-release links from Treasury's official listing page.

    Publication date is deliberately left unset on the listing adapter.  The first-seen
    timestamp is the latency-critical datum; downstream enrichment can fetch the detail
    page and fill the official publication date without blocking the hot path.
    """

    def parse(self, source: SourceConfig, body: bytes, first_seen_mono: float) -> list[RawItem]:
        del first_seen_mono
        parser = _TreasuryLinkParser()
        parser.feed(body.decode("utf-8", "replace"))
        first_seen = utcnow()
        base_url = source.url or "https://home.treasury.gov/news/press-releases"
        seen: set[str] = set()
        result: list[RawItem] = []
        for href, title in parser.links:
            url = urljoin(base_url, href)
            path = urlparse(url).path.rstrip("/")
            if path in seen:
                continue
            seen.add(path)
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            result.append(
                RawItem(
                    source_id=source.id,
                    guid=url,
                    guid_hash=digest,
                    url=url,
                    title=title,
                    raw_published_at=None,
                    published_at=None,
                    first_seen_at=first_seen,
                    payload={"adapter": "treasury_press", "official": True},
                )
            )
        return result
