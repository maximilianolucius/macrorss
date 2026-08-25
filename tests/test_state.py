from datetime import UTC, datetime

from macrorss.models import SourceState
from macrorss.state import LocalStateStore


def test_state_roundtrip(tmp_path):
    store = LocalStateStore(tmp_path / "state.json")
    state = SourceState(
        source_id="fed",
        etag='"abc"',
        last_modified="Tue, 25 Aug 2026 10:00:00 GMT",
        last_success_at=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        consecutive_errors=2,
        last_status=200,
    )
    store.save({"fed": state})
    loaded = store.load()["fed"]
    assert loaded.etag == '"abc"'
    assert loaded.consecutive_errors == 2
    assert loaded.last_success_at == state.last_success_at


def test_concurrent_state_saves_remain_valid_json(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = LocalStateStore(tmp_path / "state.json")
    states = {f"s{i}": SourceState(source_id=f"s{i}", last_status=200) for i in range(20)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.save(states), range(50)))
    loaded = store.load()
    assert set(loaded) == set(states)
