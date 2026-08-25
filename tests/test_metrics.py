from macrorss.metrics import Metrics


def test_metrics_percentiles_and_publish(tmp_path):
    metrics = Metrics(tmp_path / "metrics.json")
    for value in [1, 2, 3, 4, 100]:
        metrics.observe("hot_path_ms", value)
    assert metrics.percentile("hot_path_ms", 50) == 3
    assert metrics.percentile("hot_path_ms", 99) == 100
    metrics.publish()
    assert (tmp_path / "metrics.json").exists()
