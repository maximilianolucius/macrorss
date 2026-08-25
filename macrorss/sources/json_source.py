"""Generic JSON list adapter for official JSON/API sources."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from macrorss.models import RawItem, SourceConfig, utcnow


class GenericJsonParser:
    def parse(self, source: SourceConfig, body: bytes, first_seen_mono: float) -> list[RawItem]:
        del first_seen_mono
        payload = json.loads(body)
        options = source.parser_options
        items_path = str(options.get("items_path", ""))
        items = _walk(payload, items_path) if items_path else payload
        if not isinstance(items, list):
            raise ValueError(f"source {source.id}: JSON items_path did not resolve to a list")
        title_key = str(options.get("title_key", "title"))
        url_key = str(options.get("url_key", "url"))
        guid_key = str(options.get("guid_key", "id"))
        published_key = str(options.get("published_key", "published_at"))
        first_seen = utcnow()
        result: list[RawItem] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get(title_key, "")).strip()
            if not title:
                continue
            url = _optional_str(item.get(url_key))
            guid = _optional_str(item.get(guid_key)) or url
            published_text = _optional_str(item.get(published_key))
            identity = guid or url or f"{title}\x1f{published_text or ''}"
            result.append(
                RawItem(
                    source_id=source.id,
                    guid=guid,
                    guid_hash=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    url=url,
                    title=title,
                    raw_published_at=published_text,
                    published_at=_iso_datetime(published_text),
                    first_seen_at=first_seen,
                    payload={"json": item},
                )
            )
        return result


def _walk(value: Any, path: str) -> Any:
    current = value
    for part in (piece for piece in path.split(".") if piece):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
