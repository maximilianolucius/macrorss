"""Async HTTP fetcher with connection reuse, conditional requests and body caps."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from macrorss.models import SourceConfig, SourceState


@dataclass(frozen=True, slots=True)
class FetchResult:
    status_code: int
    body: bytes
    etag: str | None
    last_modified: str | None
    request_started_mono: float
    response_received_mono: float

    @property
    def changed(self) -> bool:
        return self.status_code == 200


class FetchError(RuntimeError):
    pass


class NetworkFetchError(FetchError):
    pass


class BodyTooLargeError(FetchError):
    pass


class HTTPStatusFetchError(FetchError):
    def __init__(self, source_id: str, status_code: int, snippet: str, retry_after: float | None = None) -> None:
        super().__init__(f"{source_id}: HTTP {status_code}: {snippet}")
        self.source_id = source_id
        self.status_code = status_code
        self.retry_after = retry_after


class HttpFetcher:
    def __init__(self, *, max_connections: int = 32, max_keepalive: int = 16) -> None:
        limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_keepalive)
        self.client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            limits=limits,
            headers={
                "Accept": "application/rss+xml, application/atom+xml, application/json, text/html;q=0.9, */*;q=0.5"
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(self, source: SourceConfig, state: SourceState) -> FetchResult:
        if not source.url:
            raise FetchError(f"source {source.id} has no URL")
        headers = {"User-Agent": source.user_agent}
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
        started = time.monotonic()
        try:
            async with self.client.stream(
                "GET", source.url, headers=headers, timeout=source.timeout_seconds
            ) as response:
                status = response.status_code
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                if status == 304:
                    received = time.monotonic()
                    return FetchResult(status, b"", etag, last_modified, started, received)
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared = int(content_length)
                    except ValueError:
                        declared = 0
                    if declared > source.max_body_bytes:
                        raise BodyTooLargeError(
                            f"{source.id}: Content-Length {declared} exceeds cap {source.max_body_bytes}"
                        )
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > source.max_body_bytes:
                        raise BodyTooLargeError(
                            f"{source.id}: response exceeds cap {source.max_body_bytes} bytes"
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
                received = time.monotonic()
                if status != 200:
                    snippet = body[:160].decode("utf-8", "replace").replace("\n", " ")
                    raise HTTPStatusFetchError(source.id, status, snippet, retry_after)
                return FetchResult(status, body, etag, last_modified, started, received)
        except (BodyTooLargeError, HTTPStatusFetchError):
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError) as exc:
            raise NetworkFetchError(f"{source.id}: {exc.__class__.__name__}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"{source.id}: {exc.__class__.__name__}: {exc}") from exc


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
