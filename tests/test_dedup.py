from macrorss.dedup import BoundedSeenSet, Deduplicator


def test_bounded_seen_set_evicts_oldest():
    seen = BoundedSeenSet(2)
    assert seen.add("a") is True
    assert seen.add("b") is True
    assert seen.add("a") is False
    assert seen.add("c") is True
    assert "a" in seen
    assert "b" not in seen


def test_alert_mark_is_separate_from_event_seen():
    dedup = Deduplicator()
    assert dedup.is_new_event("x")
    assert not dedup.already_alerted("x")
    dedup.mark_alerted("x")
    assert dedup.already_alerted("x")
