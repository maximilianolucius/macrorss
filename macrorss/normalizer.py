"""Fast deterministic event normalization and cross-source fingerprinting."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from macrorss.models import NormalizedEvent, RawItem, SourceConfig

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"mod", "source", "campaign", "ref", "referrer"}


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.hostname.lower() if parts.hostname else ""
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host
    if port and not ((parts.scheme == "https" and port == 443) or (parts.scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    query.sort()
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", text).strip()


def _title_key(title: str) -> str:
    text = normalize_title(title).casefold()
    text = re.sub(r"[^\w\s%$.-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def infer_institution(source: SourceConfig) -> str:
    source_id = source.id.casefold()
    table = (
        ("fed", "Federal Reserve"),
        ("bls", "BLS"),
        ("bea", "BEA"),
        ("treasury", "U.S. Treasury"),
        ("presidential", "White House"),
        ("ecb", "ECB"),
        ("boj", "BoJ"),
        ("boe", "BoE"),
        ("snb", "SNB"),
        ("boc", "BoC"),
        ("bis", "BIS"),
        ("cftc", "CFTC"),
        ("sec", "SEC"),
        ("rba", "RBA"),
        ("imf", "IMF"),
        ("wgc", "World Gold Council"),
        ("cme", "CME"),
        ("lbma", "LBMA"),
        ("mof", "Japan MOF"),
    )
    for prefix, institution in table:
        if source_id.startswith(prefix):
            return institution
    return source.name.split("—", 1)[0].strip()


def infer_event_type(title: str) -> str:
    key = _title_key(title)
    rules = (
        ("fomc", ("fomc", "federal funds rate", "monetary policy statement")),
        ("cpi", ("consumer price index", "cpi")),
        ("nfp", ("employment situation", "nonfarm", "payroll")),
        ("ppi", ("producer price index", "ppi")),
        ("pce", ("personal income and outlays", "pce")),
        ("gdp", ("gross domestic product", "gdp")),
        ("jolts", ("job openings", "jolts")),
        ("rate_decision", ("interest rate", "policy rate", "bank rate")),
        ("treasury_refunding", ("quarterly refunding", "refunding statement")),
        ("treasury_buyback", ("buyback", "liquidity support")),
        ("auction", ("auction",)),
        ("sanctions", ("sanction", "ofac")),
        ("speech", ("speech", "remarks", "address by")),
        ("press_release", ("press release",)),
    )
    for event_type, needles in rules:
        if any(needle in key for needle in needles):
            return event_type
    return "macro_news"


def event_fingerprint(
    *,
    institution: str,
    canonical_url: str | None,
    title: str,
    event_type: str,
    published_at_iso: str | None,
) -> str:
    # With an official publication timestamp, semantic identity allows redundant official
    # channels with different URLs to converge. The minute bucket separates recurring monthly
    # releases that intentionally reuse the same title.
    if published_at_iso:
        minute = published_at_iso[:16]
        material = f"semantic\x1f{institution.casefold()}\x1f{event_type}\x1f{_title_key(title)}\x1f{minute}"
    elif canonical_url:
        material = f"url\x1f{institution.casefold()}\x1f{canonical_url}"
    else:
        material = f"title\x1f{institution.casefold()}\x1f{event_type}\x1f{_title_key(title)}"
    return hashlib.sha256(material.encode("utf-8", "surrogatepass")).hexdigest()


def normalize_event(source: SourceConfig, raw: RawItem) -> NormalizedEvent:
    canonical_url = canonicalize_url(raw.url)
    canonical_title = normalize_title(raw.title)
    institution = infer_institution(source)
    event_type = infer_event_type(canonical_title)
    published_iso = raw.published_at.isoformat() if raw.published_at else None
    fingerprint = event_fingerprint(
        institution=institution,
        canonical_url=canonical_url,
        title=canonical_title,
        event_type=event_type,
        published_at_iso=published_iso,
    )
    return NormalizedEvent(
        event_fingerprint=fingerprint,
        canonical_url=canonical_url,
        canonical_title=canonical_title,
        institution=institution,
        event_type=event_type,
        published_at=raw.published_at,
        first_seen_at=raw.first_seen_at,
        first_source_id=raw.source_id,
        tags=source.tags,
        rank_gold=source.rank_gold,
        rank_fx=source.rank_fx,
    )
