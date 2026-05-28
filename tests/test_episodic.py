from server.memory import Episode, EpisodicMemory


def test_add_and_recent_in_order():
    em = EpisodicMemory()
    em.add(1, "narration", "Mira examines the bunk and finds a loose nail.")
    em.add(2, "delta", "tick:2 alarm_meter:1")
    em.add(3, "hint", "Salty squawks: stop examining hal_keyring.")
    rec = em.recent(2)
    assert [e.tick for e in rec] == [2, 3]


def test_add_ignores_empty_text():
    em = EpisodicMemory()
    em.add(1, "narration", "   ")
    em.add(2, "narration", "")
    assert em.episodes == []


def test_max_episodes_drops_non_reflection_first():
    em = EpisodicMemory(max_episodes=4)
    em.add(1, "reflection", "early scene reflection", score_hint=2.0)
    em.add(2, "narration", "alpha event narration text here")
    em.add(3, "narration", "beta event narration text here")
    em.add(4, "narration", "gamma event narration text here")
    em.add(5, "narration", "delta event narration text here")
    # alpha (oldest non-reflection) should have been dropped, reflection kept.
    kinds = [e.kind for e in em.episodes]
    texts = " ".join(e.text for e in em.episodes)
    assert "reflection" in kinds
    assert "alpha" not in texts
    assert "delta" in texts


def test_query_keyword_overlap_and_recency():
    em = EpisodicMemory()
    em.add(1, "narration", "Hal sleeps slumped at his desk with a keyring on his belt.")
    em.add(2, "narration", "The lantern hangs above the bunk and casts long shadows.")
    em.add(10, "narration", "Hal stirs and reaches for his keyring once more.")
    results = em.query("keyring hal", k=2, current_tick=10)
    assert results, "expected at least one hit"
    # The most recent hal/keyring narration should rank first.
    assert results[0].tick == 10


def test_query_falls_back_to_recent_when_no_tokens():
    em = EpisodicMemory()
    em.add(1, "narration", "alpha alpha alpha alpha")
    em.add(2, "narration", "beta beta beta beta")
    # Query has only short tokens (<=3 chars) so token set is empty.
    res = em.query("a b c", k=1, current_tick=5)
    assert len(res) == 1
    assert res[0].tick == 2


def test_compact_preserves_reflections_and_appends_summary():
    em = EpisodicMemory()
    em.add(1, "reflection", "earlier reflection", score_hint=2.0)
    em.add(2, "narration", "old narration about brig escape attempt")
    em.add(3, "narration", "another older narration about hal keyring")
    em.add(5, "narration", "recent narration after compaction boundary")
    dropped = em.compact(
        before_tick=5,
        replacement=Episode(tick=5, kind="reflection", text="compressed summary"),
    )
    assert dropped == 2
    assert any(e.kind == "reflection" and e.text == "earlier reflection" for e in em.episodes)
    assert any(e.kind == "reflection" and e.text == "compressed summary" for e in em.episodes)
    assert any(e.tick == 5 and e.kind == "narration" for e in em.episodes)
    # Older narrations dropped.
    assert not any(e.kind == "narration" and e.tick < 5 for e in em.episodes)
