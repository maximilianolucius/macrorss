"""Non-blocking hot-path dispatcher and output sinks."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

import httpx

from macrorss.models import NormalizedEvent


class EventSink(Protocol):
    async def send(self, event: NormalizedEvent) -> None: ...


class StdoutJsonSink:
    async def send(self, event: NormalizedEvent) -> None:
        print(json.dumps({"type": "macro_event", **event.to_json()}, ensure_ascii=False), flush=True)


class JsonlFileSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def send(self, event: NormalizedEvent) -> None:
        line = json.dumps(event.to_json(), ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


class WebhookSink:
    def __init__(self, url: str, *, timeout: float = 3.0) -> None:
        self.url = url
        self.client = httpx.AsyncClient(timeout=timeout)

    async def send(self, event: NormalizedEvent) -> None:
        response = await self.client.post(self.url, json=event.to_json())
        response.raise_for_status()

    async def close(self) -> None:
        await self.client.aclose()


class TelegramSink:
    def __init__(self, bot_token: str, chat_id: str, *, timeout: float = 3.0) -> None:
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.client = httpx.AsyncClient(timeout=timeout)

    async def send(self, event: NormalizedEvent) -> None:
        rank = f"gold={event.rank_gold} fx={event.rank_fx}"
        text = f"[{event.institution}] {event.canonical_title}\n{rank}\n{event.canonical_url or ''}"
        response = await self.client.post(
            self.url,
            json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
        )
        response.raise_for_status()

    async def close(self) -> None:
        await self.client.aclose()


class ZeroMQSink:
    def __init__(self, bind: str) -> None:
        try:
            import zmq
            import zmq.asyncio
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency installed in production
            raise RuntimeError("pyzmq is required for ZeroMQ output") from exc
        self._zmq = zmq
        self.context = zmq.asyncio.Context.instance()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.bind(bind)

    async def send(self, event: NormalizedEvent) -> None:
        await self.socket.send_multipart(
            [b"macrorss.event", json.dumps(event.to_json(), separators=(",", ":")).encode("utf-8")]
        )

    async def close(self) -> None:
        self.socket.close(0)


class Dispatcher:
    """Bounded, non-blocking producer queue.

    ``emit_nowait`` is the hot-path API.  It never waits on network/disk sinks.  When the
    queue is full it fails closed (returns False) and increments a caller-owned metric;
    callers can choose a policy without stalling collectors.
    """

    def __init__(
        self,
        sinks: list[EventSink],
        *,
        queue_size: int = 2048,
        on_error: Callable[[Exception], Awaitable[None] | None] | None = None,
    ) -> None:
        self.sinks = sinks
        self.queue: asyncio.Queue[NormalizedEvent | None] = asyncio.Queue(maxsize=queue_size)
        self.worker: asyncio.Task[None] | None = None
        self.on_error = on_error

    async def start(self) -> None:
        if self.worker is None:
            self.worker = asyncio.create_task(self._run(), name="macrorss-dispatcher")

    def emit_nowait(self, event: NormalizedEvent) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    async def close(self) -> None:
        if self.worker is not None:
            await self.queue.put(None)
            await self.worker
            self.worker = None
        for sink in self.sinks:
            close = getattr(sink, "close", None)
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result):
                    await result

    async def _run(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                if event is None:
                    return
                for sink in self.sinks:
                    try:
                        await sink.send(event)
                    except Exception as exc:  # sinks must not kill collector
                        print(f"macrorss sink error: {exc}", file=sys.stderr, flush=True)
                        if self.on_error is not None:
                            result = self.on_error(exc)
                            if asyncio.iscoroutine(result):
                                await result
            finally:
                self.queue.task_done()
