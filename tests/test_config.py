from pathlib import Path

import pytest

from macrorss.config import load_sources


def test_repo_config_loads():
    sources = load_sources(Path(__file__).parents[1] / "config" / "feeds.yaml")
    assert len(sources) == 24
    assert sum(source.enabled for source in sources) == 18
    treasury = next(source for source in sources if source.id == "treasury-press")
    assert treasury.transport == "html"
    assert treasury.parser == "treasury_press"
    assert treasury.rank_gold == 4


def test_duplicate_source_rejected(tmp_path):
    config = tmp_path / "feeds.yaml"
    config.write_text(
        "version: 1\nfeeds:\n  - {id: a, name: A, url: 'https://x'}\n  - {id: a, name: B, url: 'https://y'}\n"
    )
    with pytest.raises(ValueError, match="duplicate source id"):
        load_sources(config)


def test_enabled_source_requires_url(tmp_path):
    config = tmp_path / "feeds.yaml"
    config.write_text("version: 1\nfeeds:\n  - {id: a, name: A, url: null}\n")
    with pytest.raises(ValueError, match="requires url"):
        load_sources(config)
