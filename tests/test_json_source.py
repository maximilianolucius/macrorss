import json

from macrorss.models import SourceConfig
from macrorss.sources.json_source import GenericJsonParser


def test_generic_json_adapter():
    source = SourceConfig(
        id="api",
        name="API",
        url="https://example.test/api",
        transport="json",
        parser="generic_json",
        parser_options={"items_path": "data.items", "published_key": "ts"},
    )
    body = json.dumps({"data": {"items": [{"id": "1", "title": "Release", "url": "https://x/1", "ts": "2026-08-25T17:00:00Z"}]}}).encode()
    items = GenericJsonParser().parse(source, body, 0.0)
    assert len(items) == 1
    assert items[0].guid == "1"
    assert items[0].published_at is not None
