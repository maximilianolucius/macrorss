"""Small local durable state for conditional GET and source health."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from macrorss.models import SourceState


class LocalStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def load(self) -> dict[str, SourceState]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, SourceState] = {}
        for source_id, item in raw.items():
            if not isinstance(item, dict):
                continue
            result[source_id] = SourceState(
                source_id=source_id,
                etag=_optional_str(item.get("etag")),
                last_modified=_optional_str(item.get("last_modified")),
                last_success_at=_dt(item.get("last_success_at")),
                last_attempt_at=_dt(item.get("last_attempt_at")),
                consecutive_errors=int(item.get("consecutive_errors", 0)),
                last_status=_optional_int(item.get("last_status")),
                circuit_open_until=_dt(item.get("circuit_open_until")),
            )
        return result

    def save(self, states: dict[str, SourceState]) -> None:
        with self._lock:
            payload = {key: value.to_json() for key, value in states.items()}
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            _fsync_dir(self.path.parent)


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
