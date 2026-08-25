"""Parser adapter registry."""

from __future__ import annotations

from typing import Protocol

from macrorss.models import RawItem, SourceConfig


class SourceParser(Protocol):
    def parse(self, source: SourceConfig, body: bytes, first_seen_mono: float) -> list[RawItem]: ...


def parser_for_source(source: SourceConfig) -> SourceParser:
    if source.parser == "feed":
        from macrorss.sources.feed import FeedSourceParser

        return FeedSourceParser()
    if source.parser == "treasury_press":
        from macrorss.sources.html import TreasuryPressParser

        return TreasuryPressParser()
    if source.parser == "generic_json":
        from macrorss.sources.json_source import GenericJsonParser

        return GenericJsonParser()
    raise ValueError(f"unknown parser {source.parser!r} for source {source.id}")
