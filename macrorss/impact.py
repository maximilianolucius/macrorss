"""Fast deterministic routing filter for the alert hot path."""

from __future__ import annotations

import os

from macrorss.models import NormalizedEvent

_HIGH_IMPACT_TYPES = {
    "fomc",
    "cpi",
    "nfp",
    "ppi",
    "pce",
    "gdp",
    "rate_decision",
    "treasury_refunding",
    "treasury_buyback",
    "sanctions",
}


class ImpactFilter:
    def __init__(
        self,
        max_rank_gold: int = 5,
        max_rank_fx: int = 5,
        emit_all: bool = False,
        markets: frozenset[str] = frozenset({"gold", "fx"}),
        event_types: frozenset[str] | None = None,
    ) -> None:
        self.max_rank_gold = max_rank_gold
        self.max_rank_fx = max_rank_fx
        self.emit_all = emit_all
        self.markets = markets
        self.event_types = event_types

    @classmethod
    def from_env(cls) -> "ImpactFilter":
        markets = frozenset(
            value.strip().lower()
            for value in os.getenv("MACRORSS_ALERT_MARKETS", "gold,fx").split(",")
            if value.strip()
        )
        types_raw = os.getenv("MACRORSS_ALERT_EVENT_TYPES", "").strip()
        event_types = (
            frozenset(value.strip() for value in types_raw.split(",") if value.strip())
            if types_raw
            else None
        )
        return cls(
            max_rank_gold=int(os.getenv("MACRORSS_MAX_RANK_GOLD", "5")),
            max_rank_fx=int(os.getenv("MACRORSS_MAX_RANK_FX", "5")),
            emit_all=os.getenv("MACRORSS_EMIT_ALL", "0").lower() in {"1", "true", "yes"},
            markets=markets,
            event_types=event_types,
        )

    def allows(self, event: NormalizedEvent) -> bool:
        if self.event_types is not None and event.event_type not in self.event_types:
            return False
        if self.emit_all:
            return True
        event_markets = set(event.tags) & {"gold", "fx"}
        if self.markets and event_markets and not event_markets.intersection(self.markets):
            return False
        if event.event_type in _HIGH_IMPACT_TYPES:
            return bool(event_markets.intersection(self.markets)) if event_markets else True
        if "gold" in self.markets and event.rank_gold is not None and event.rank_gold <= self.max_rank_gold:
            return True
        return "fx" in self.markets and event.rank_fx is not None and event.rank_fx <= self.max_rank_fx
