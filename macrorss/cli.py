"""Command-line interface for MacroRSS operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from macrorss import __version__
from macrorss.config import DatabaseConfig, RuntimeConfig, load_sources
from macrorss.daemon import run_daemon
from macrorss.dispatcher import Dispatcher, JsonlFileSink, StdoutJsonSink, WebhookSink, ZeroMQSink
from macrorss.fetcher import HttpFetcher
from macrorss.models import NormalizedEvent, SourceState
from macrorss.sources import parser_for_source
from macrorss.spool import SegmentedSpool
from macrorss.store import MySQLStore, StoreUnavailable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macrorss",
        description="Low-latency resilient macro event sensor for Gold (XAUUSD) and Forex.",
    )
    parser.add_argument("--version", action="version", version=f"macrorss {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="run the collector daemon")
    sub.add_parser("check-config", help="validate feeds and event calendar configuration")
    sub.add_parser("check-db", help="connect to MySQL and validate schema/durability settings")
    sub.add_parser("status", help="show last daemon metrics/status snapshot")
    sub.add_parser("sources", help="list configured sources")
    sub.add_parser("spool-status", help="show local durable spool status")
    sub.add_parser("replay-spool", help="flush all ready spool segments to MySQL now")

    tail = sub.add_parser("tail", help="print recent locally emitted events")
    tail.add_argument("--tag", default=None, help="filter by event tag, e.g. gold or fx")
    tail.add_argument("-n", "--lines", type=int, default=50)

    probe = sub.add_parser("probe", help="fetch and parse one configured source once")
    probe.add_argument("source_id")

    emit = sub.add_parser("emit-test", help="emit a synthetic event through configured hot-path sinks")
    emit.add_argument("--webhook", default=None)
    emit.add_argument("--zmq-bind", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "run":
            asyncio.run(run_daemon())
            return 0
        if args.command == "check-config":
            return _check_config()
        if args.command == "check-db":
            return asyncio.run(_check_db())
        if args.command == "status":
            return _status()
        if args.command == "sources":
            return _sources()
        if args.command == "spool-status":
            return _spool_status()
        if args.command == "replay-spool":
            return asyncio.run(_replay_spool())
        if args.command == "tail":
            return _tail(args.tag, args.lines)
        if args.command == "probe":
            return asyncio.run(_probe(args.source_id))
        if args.command == "emit-test":
            return asyncio.run(_emit_test(args.webhook, args.zmq_bind))
    except (ValueError, StoreUnavailable, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    # argparse.error() raises SystemExit; nothing after it is reachable.
    parser.error(f"unknown command: {args.command}")


def _check_config() -> int:
    runtime = RuntimeConfig.from_env()
    sources = load_sources(runtime.config_path)
    from macrorss.scheduler import EventCalendar

    calendar = EventCalendar.from_yaml(runtime.events_path)
    enabled = sum(source.enabled for source in sources)
    source_ids = {source.id for source in sources}
    unknown_event_sources = sorted(
        {source_id for event in calendar.events for source_id in event.source_ids if source_id not in source_ids}
    )
    if unknown_event_sources:
        raise ValueError(f"events reference unknown source ids: {', '.join(unknown_event_sources)}")
    transports: dict[str, int] = {}
    for source in sources:
        transports[source.transport] = transports.get(source.transport, 0) + 1
    print(
        json.dumps(
            {
                "ok": True,
                "sources": len(sources),
                "enabled": enabled,
                "disabled": len(sources) - enabled,
                "transports": transports,
                "scheduled_events": len(calendar.events),
                "calendar_coverage_end": (
                    calendar.events[-1].at.isoformat().replace("+00:00", "Z") if calendar.events else None
                ),
                "calendar_refresh_due": (
                    not calendar.events or calendar.events[-1].at < datetime.now(UTC) + timedelta(days=30)
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


async def _check_db() -> int:
    config = DatabaseConfig.from_env(require_password=True)
    store = MySQLStore(config)
    try:
        details = await store.check_schema()
    finally:
        await store.close()
    result = {
        "ok": True,
        "host": config.host,
        "port": config.port,
        "database": config.name,
        **details,
    }
    if details.get("innodb_flush_log_at_trx_commit") != 1:
        result["warning"] = "innodb_flush_log_at_trx_commit != 1; local spool remains primary crash guarantee"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _status() -> int:
    runtime = RuntimeConfig.from_env()
    if not runtime.metrics_path.exists():
        print(json.dumps({"running_snapshot": False, "message": "no metrics snapshot yet"}, indent=2))
        return 1
    print(runtime.metrics_path.read_text(encoding="utf-8"), end="")
    return 0


def _sources() -> int:
    runtime = RuntimeConfig.from_env()
    sources = load_sources(runtime.config_path)
    rows = [
        {
            "id": source.id,
            "enabled": source.enabled,
            "transport": source.transport,
            "parser": source.parser,
            "priority": source.priority,
            "rank_gold": source.rank_gold,
            "rank_fx": source.rank_fx,
            "base_poll_s": source.poll.base_seconds,
            "url": source.url,
        }
        for source in sources
    ]
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def _make_spool(runtime: RuntimeConfig) -> SegmentedSpool:
    return SegmentedSpool(
        runtime.spool_dir,
        segment_bytes=runtime.spool_segment_bytes,
        max_age_seconds=runtime.spool_segment_max_age_seconds,
        fsync_every=runtime.spool_fsync_every,
        archive_hours=runtime.spool_archive_hours,
    )


def _spool_status() -> int:
    runtime = RuntimeConfig.from_env()
    spool = _make_spool(runtime)
    print(json.dumps(spool.status(), indent=2, sort_keys=True))
    return 0


async def _replay_spool() -> int:
    runtime = RuntimeConfig.from_env()
    spool = _make_spool(runtime)
    spool.close()
    store = MySQLStore(DatabaseConfig.from_env(require_password=True))
    total = 0
    segments = 0
    try:
        for path in spool.ready_segments():
            records = spool.read_segment(path)
            await store.persist_records(records)
            spool.archive(path)
            total += len(records)
            segments += 1
    finally:
        await store.close()
    print(json.dumps({"ok": True, "segments": segments, "records": total}))
    return 0


def _tail(tag: str | None, lines: int) -> int:
    runtime = RuntimeConfig.from_env()
    path = runtime.event_log_path
    if not path.exists():
        return 0
    selected: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if tag:
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if tag not in event.get("tags", []):
                continue
        selected.append(raw_line)
    for line in selected[-max(0, lines) :]:
        print(line)
    return 0


async def _probe(source_id: str) -> int:
    runtime = RuntimeConfig.from_env()
    sources = {source.id: source for source in load_sources(runtime.config_path)}
    try:
        source = sources[source_id]
    except KeyError as exc:
        raise ValueError(f"unknown source: {source_id}") from exc
    if not source.url:
        raise ValueError(f"source {source_id} has no URL")
    fetcher = HttpFetcher()
    try:
        result = await fetcher.fetch(source, SourceState(source_id=source.id))
        items = parser_for_source(source).parse(source, result.body, result.response_received_mono) if result.changed else []
    finally:
        await fetcher.close()
    print(
        json.dumps(
            {
                "source": source.id,
                "status": result.status_code,
                "etag": result.etag,
                "last_modified": result.last_modified,
                "items": len(items),
                "sample": [item.to_json() for item in items[:3]],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


async def _emit_test(webhook: str | None, zmq_bind: str | None) -> int:
    runtime = RuntimeConfig.from_env()
    sinks: list[Any] = [StdoutJsonSink(), JsonlFileSink(runtime.event_log_path)]
    if webhook or runtime.webhook_url:
        sinks.append(WebhookSink(webhook or str(runtime.webhook_url)))
    if zmq_bind or runtime.zmq_bind:
        sinks.append(ZeroMQSink(zmq_bind or str(runtime.zmq_bind)))
    dispatcher = Dispatcher(sinks)
    await dispatcher.start()
    now = datetime.now(UTC)
    event = NormalizedEvent(
        event_fingerprint="0" * 64,
        canonical_url="https://example.invalid/macrorss-test",
        canonical_title="MacroRSS synthetic test event",
        institution="MacroRSS",
        event_type="test",
        published_at=now,
        first_seen_at=now,
        first_source_id="synthetic",
        tags=("gold", "fx", "test"),
        rank_gold=1,
        rank_fx=1,
    )
    if not dispatcher.emit_nowait(event):
        raise RuntimeError("dispatcher queue unexpectedly full")
    await dispatcher.queue.join()
    await dispatcher.close()
    print(json.dumps({"ok": True, "event_fingerprint": event.event_fingerprint}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
