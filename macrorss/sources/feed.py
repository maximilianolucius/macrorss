"""RSS/Atom parser with feedparser when available and stdlib XML fallback."""

from __future__ import annotations

import calendar
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from macrorss.models import RawItem, SourceConfig, utcnow


def _stable_guid(
    source_id: str,
    guid: str | None,
    link: str | None,
    title: str,
    published: str | None,
    content: str | None = None,
) -> str:
    """Fingerprint for document-level dedup.

    ``content`` must be supplied only for dashboard-style feeds (``dedup: content``),
    where a single item with a constant guid is rewritten in place on every release.
    For those, guid alone is not an identity: it never changes, so every update after
    the first would be discarded as a duplicate.  Feeds that publish one item per
    release must keep guid-only identity, otherwise an edited headline would be
    re-emitted as a new event.
    """
    del source_id  # dedup is keyed on (source_id, guid_hash) by the caller.
    identity = guid or link or "\x1f".join((title, published or ""))
    if content is not None:
        identity = "\x1f".join((identity, hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()))
    return hashlib.sha256(identity.encode("utf-8", "surrogatepass")).hexdigest()


def _content_dedup(source: SourceConfig) -> bool:
    return str(source.parser_options.get("dedup", "guid")).lower() == "content"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _entry_value(entry: Any, key: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    return str(value)


class FeedSourceParser:
    def parse(self, source: SourceConfig, body: bytes, first_seen_mono: float) -> list[RawItem]:
        del first_seen_mono  # wall-clock first_seen is recorded below; monotonic is a pipeline metric.
        try:
            import feedparser  # type: ignore[import-untyped]
        except ModuleNotFoundError:
            return self._parse_stdlib(source, body)

        parsed = feedparser.parse(body)
        result: list[RawItem] = []
        first_seen = utcnow()
        content_dedup = _content_dedup(source)
        for entry in parsed.entries:
            title = _entry_value(entry, "title") or ""
            link = _entry_value(entry, "link")
            guid = _entry_value(entry, "id") or _entry_value(entry, "guid") or link
            raw_published = _entry_value(entry, "published") or _entry_value(entry, "updated")
            published_at = _parse_datetime(raw_published)
            if published_at is None:
                struct = entry.get("published_parsed") or entry.get("updated_parsed")
                if struct:
                    try:
                        published_at = datetime.fromtimestamp(calendar.timegm(struct), tz=UTC)
                    except (TypeError, ValueError, OverflowError):
                        published_at = None
            summary = _entry_value(entry, "summary")
            result.append(
                RawItem(
                    source_id=source.id,
                    guid=guid,
                    guid_hash=_stable_guid(
                        source.id, guid, link, title, raw_published, summary if content_dedup else None
                    ),
                    url=link,
                    title=re.sub(r"\s+", " ", title).strip(),
                    raw_published_at=raw_published,
                    published_at=published_at,
                    first_seen_at=first_seen,
                    payload={"summary": summary},
                )
            )
        return result

    def _parse_stdlib(self, source: SourceConfig, body: bytes) -> list[RawItem]:
        root = ET.fromstring(body)
        first_seen = utcnow()
        result: list[RawItem] = []
        content_dedup = _content_dedup(source)
        for node in root.iter():
            local = node.tag.rsplit("}", 1)[-1].lower()
            if local not in {"item", "entry"}:
                continue
            fields: dict[str, list[ET.Element]] = {}
            for child in list(node):
                fields.setdefault(child.tag.rsplit("}", 1)[-1].lower(), []).append(child)
            title = _first_text(fields, "title") or ""
            guid = _first_text(fields, "guid") or _first_text(fields, "id")
            link = _feed_link(fields)
            raw_published = (
                _first_text(fields, "pubdate")
                or _first_text(fields, "published")
                or _first_text(fields, "updated")
            )
            summary = _first_text(fields, "description") or _first_text(fields, "summary")
            result.append(
                RawItem(
                    source_id=source.id,
                    guid=guid or link,
                    guid_hash=_stable_guid(
                        source.id, guid, link, title, raw_published, summary if content_dedup else None
                    ),
                    url=link,
                    title=re.sub(r"\s+", " ", title).strip(),
                    raw_published_at=raw_published,
                    published_at=_parse_datetime(raw_published),
                    first_seen_at=first_seen,
                    payload={"summary": summary},
                )
            )
        return result


def _first_text(fields: dict[str, list[ET.Element]], key: str) -> str | None:
    nodes = fields.get(key, [])
    if not nodes:
        return None
    text = "".join(nodes[0].itertext()).strip()
    return text or None


def _feed_link(fields: dict[str, list[ET.Element]]) -> str | None:
    nodes = fields.get("link", [])
    for node in nodes:
        href = node.attrib.get("href")
        rel = node.attrib.get("rel", "alternate")
        if href and rel in {"alternate", ""}:
            return href.strip()
        if node.text and node.text.strip():
            return node.text.strip()
    return None
