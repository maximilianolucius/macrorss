"""Configuration loading and validation for MacroRSS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from macrorss.models import PollPolicy, SourceConfig

DEFAULT_CONFIG_PATH = Path("config/feeds.yaml")
DEFAULT_EVENTS_PATH = Path("config/events.yaml")


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    name: str
    minsize: int = 1
    maxsize: int = 5
    connect_timeout: float = 5.0

    @classmethod
    def from_env(cls, *, require_password: bool = True) -> "DatabaseConfig":
        host = os.getenv("MACRORSS_DB_HOST", "172.16.0.41")
        port = int(os.getenv("MACRORSS_DB_PORT", "3306"))
        user = os.getenv("MACRORSS_DB_USER", "macrorss")
        password = os.getenv("MACRORSS_DB_PASSWORD", "")
        name = os.getenv("MACRORSS_DB_NAME", "macrorss")
        minsize = int(os.getenv("MACRORSS_DB_POOL_MIN", "1"))
        maxsize = int(os.getenv("MACRORSS_DB_POOL_MAX", "5"))
        timeout = float(os.getenv("MACRORSS_DB_CONNECT_TIMEOUT", "5"))
        if require_password and not password:
            raise ValueError("MACRORSS_DB_PASSWORD is required")
        if not 1 <= port <= 65535:
            raise ValueError("MACRORSS_DB_PORT must be 1..65535")
        if minsize < 0 or maxsize < 1 or minsize > maxsize:
            raise ValueError("invalid MySQL pool size")
        return cls(host, port, user, password, name, minsize, maxsize, timeout)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    config_path: Path
    events_path: Path
    data_dir: Path
    spool_dir: Path
    state_path: Path
    event_log_path: Path
    metrics_path: Path
    dispatcher_queue_size: int
    spool_segment_bytes: int
    spool_segment_max_age_seconds: float
    spool_archive_hours: float
    spool_fsync_every: int
    flush_interval_seconds: float
    heartbeat_url: str | None
    heartbeat_seconds: float
    ntp_check_seconds: float
    spool_warn_bytes: int
    spool_warn_age_seconds: float
    zmq_bind: str | None
    webhook_url: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        data_dir = Path(os.getenv("MACRORSS_DATA_DIR", "data"))
        spool_dir = Path(os.getenv("MACRORSS_SPOOL_DIR", str(data_dir / "spool")))
        return cls(
            config_path=Path(os.getenv("MACRORSS_CONFIG", str(DEFAULT_CONFIG_PATH))),
            events_path=Path(os.getenv("MACRORSS_EVENTS", str(DEFAULT_EVENTS_PATH))),
            data_dir=data_dir,
            spool_dir=spool_dir,
            state_path=Path(os.getenv("MACRORSS_STATE", str(data_dir / "feed_state.json"))),
            event_log_path=Path(os.getenv("MACRORSS_EVENT_LOG", str(data_dir / "events.jsonl"))),
            metrics_path=Path(os.getenv("MACRORSS_METRICS", str(data_dir / "metrics.json"))),
            dispatcher_queue_size=int(os.getenv("MACRORSS_DISPATCH_QUEUE", "2048")),
            spool_segment_bytes=int(os.getenv("MACRORSS_SPOOL_SEGMENT_BYTES", str(4 * 1024 * 1024))),
            spool_segment_max_age_seconds=float(os.getenv("MACRORSS_SPOOL_SEGMENT_MAX_AGE", "2")),
            spool_archive_hours=float(os.getenv("MACRORSS_SPOOL_ARCHIVE_HOURS", "48")),
            spool_fsync_every=int(os.getenv("MACRORSS_SPOOL_FSYNC_EVERY", "1")),
            flush_interval_seconds=float(os.getenv("MACRORSS_FLUSH_INTERVAL", "1")),
            heartbeat_url=os.getenv("MACRORSS_HEALTHCHECK_URL") or None,
            heartbeat_seconds=float(os.getenv("MACRORSS_HEARTBEAT_SECONDS", "60")),
            ntp_check_seconds=float(os.getenv("MACRORSS_NTP_CHECK_SECONDS", "60")),
            spool_warn_bytes=int(os.getenv("MACRORSS_SPOOL_WARN_BYTES", str(100 * 1024 * 1024))),
            spool_warn_age_seconds=float(os.getenv("MACRORSS_SPOOL_WARN_AGE", "300")),
            zmq_bind=os.getenv("MACRORSS_ZMQ_BIND") or None,
            webhook_url=os.getenv("MACRORSS_WEBHOOK_URL") or None,
            telegram_bot_token=os.getenv("MACRORSS_TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("MACRORSS_TELEGRAM_CHAT_ID") or None,
        )


def _as_mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a mapping")
    return value


def _poll_policy(defaults: dict[str, Any], source: dict[str, Any]) -> PollPolicy:
    base = dict(_as_mapping(defaults.get("poll", {}), "defaults.poll"))
    override = _as_mapping(source.get("poll", {}), f"source {source.get('id')}.poll")
    base.update(override)
    known = {field for field in PollPolicy.__dataclass_fields__}
    unknown = set(base) - known
    if unknown:
        raise ValueError(f"unknown poll keys: {sorted(unknown)}")
    policy = PollPolicy(**base)
    policy.validate()
    return policy


def load_sources(path: str | Path = DEFAULT_CONFIG_PATH) -> list[SourceConfig]:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"config file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {config_path}: {exc}") from exc

    root = _as_mapping(raw, "root")
    defaults = _as_mapping(root.get("defaults", {}), "defaults")
    feeds = root.get("feeds")
    if not isinstance(feeds, list):
        raise ValueError("feeds must be a list")

    seen: set[str] = set()
    sources: list[SourceConfig] = []
    for index, item in enumerate(feeds):
        source = _as_mapping(item, f"feeds[{index}]")
        source_id = str(source.get("id", "")).strip()
        if source_id in seen:
            raise ValueError(f"duplicate source id: {source_id}")
        seen.add(source_id)
        tags_raw = source.get("tags", [])
        if not isinstance(tags_raw, list) or not all(isinstance(tag, str) for tag in tags_raw):
            raise ValueError(f"source {source_id}: tags must be list[str]")
        parser_options = source.get("parser_options", {})
        if not isinstance(parser_options, dict):
            raise ValueError(f"source {source_id}: parser_options must be a mapping")

        transport = str(source.get("transport", defaults.get("transport", "rss"))).lower()
        parser = str(source.get("parser", defaults.get("parser", "feed")))
        src = SourceConfig(
            id=source_id,
            name=str(source.get("name", source_id)),
            url=source.get("url"),
            enabled=bool(source.get("enabled", True)),
            transport=transport,  # type: ignore[arg-type]
            parser=parser,
            tags=tuple(tags_raw),
            rank_gold=_optional_int(source.get("rank_gold"), f"source {source_id}.rank_gold"),
            rank_fx=_optional_int(source.get("rank_fx"), f"source {source_id}.rank_fx"),
            priority=int(source.get("priority", 100)),
            requires_user_agent=bool(source.get("requires_user_agent", False)),
            timeout_seconds=float(source.get("timeout_seconds", defaults.get("timeout_seconds", 15))),
            max_body_bytes=int(source.get("max_body_bytes", defaults.get("max_body_bytes", 5 * 1024 * 1024))),
            user_agent=str(source.get("user_agent", defaults.get("user_agent", "MacroRSS/0.1"))),
            poll=_poll_policy(defaults, source),
            notes=str(source.get("notes", "")),
            parser_options=dict(parser_options),
        )
        src.validate()
        sources.append(src)
    return sources


def _optional_int(value: Any, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{where} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} must be an integer") from exc


def enabled_sources(path: str | Path = DEFAULT_CONFIG_PATH) -> list[SourceConfig]:
    return [source for source in load_sources(path) if source.enabled]
