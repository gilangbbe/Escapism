"""Tests for the periodic reflection compressor."""
from __future__ import annotations

import json
from dataclasses import dataclass

from server.agents.reflection import Reflector
from server.memory.episodic import EpisodicMemory


@dataclass
class _FakeLLM:
    response: str

    def chat(self, messages, *, json_mode: bool = False) -> str:
        return self.response


def _events():
    return [
        {"tick": 1, "actor": "gm", "kind": "gm_narration",
         "payload": {"text": "Mira slips a loose nail from the bunk."}},
        {"tick": 2, "actor": "gm", "kind": "gm_narration",
         "payload": {"text": "Hal stirs in his sleep; the alarm climbs by one."}},
    ]


def _world():
    return {"tick": 5, "current_location": "brig", "objectives": {"escape_brig": "active"},
            "known_facts": ["Vane drugged the rum."], "inventory": ["nail"]}


def test_reflect_parses_summary_and_facts_and_compacts():
    em = EpisodicMemory()
    em.add(1, "narration", "Mira slips a loose nail from the bunk.")
    em.add(2, "narration", "Hal stirs in his sleep; the alarm climbs by one.")
    response = json.dumps({
        "summary": "You have a nail and Hal is restless.",
        "new_facts": ["Hal sleeps lightly.", "A loose nail can pick the cell lock."],
    })
    r = Reflector(llm=_FakeLLM(response=response), episodic=em)
    result = r.reflect(tick=5, world=_world(), recent_events=_events())
    assert result["summary"].startswith("You have a nail")
    # 1 digest + 2 LLM facts.
    assert len(result["new_facts"]) == 3
    assert result["new_facts"][0].startswith("State digest @ t5")
    # Episodic memory now contains a reflection episode.
    assert any(e.kind == "reflection" and "nail" in e.text for e in em.episodes)
    # Older narrations compacted away (tick < 4 dropped, compact uses before_tick=tick-1=4).
    assert not any(e.kind == "narration" and e.tick < 4 for e in em.episodes)


def test_reflect_caps_new_facts_at_three():
    em = EpisodicMemory()
    em.add(1, "narration", "x" * 30)
    response = json.dumps({
        "summary": "ok",
        "new_facts": ["a", "b", "c", "d", "e"],
    })
    r = Reflector(llm=_FakeLLM(response=response), episodic=em)
    result = r.reflect(tick=5, world=_world(), recent_events=_events())
    # 1 digest + up to 3 LLM facts = 4 cap when digest present.
    assert len(result["new_facts"]) == 4
    assert result["new_facts"][0].startswith("State digest @ t5")


def test_reflect_returns_empty_on_garbage():
    em = EpisodicMemory()
    r = Reflector(llm=_FakeLLM(response="not json at all"), episodic=em)
    result = r.reflect(tick=5, world=_world(), recent_events=_events())
    # Even when the LLM emits garbage, the deterministic state digest is
    # still surfaced so long runs cannot forget state.
    assert result.get("summary") == ""
    assert len(result.get("new_facts", [])) == 1
    assert result["new_facts"][0].startswith("State digest @ t5")


def test_reflect_returns_empty_on_llm_failure():
    em = EpisodicMemory()

    class _Boom:
        def chat(self, *_a, **_k):
            raise RuntimeError("boom")

    r = Reflector(llm=_Boom(), episodic=em)
    assert r.reflect(tick=5, world=_world(), recent_events=_events()) == {}


def test_state_digest_is_prepended_to_new_facts():
    em = EpisodicMemory()
    em.add(1, "narration", "alpha alpha alpha alpha")
    response = json.dumps({"summary": "ok", "new_facts": ["fact a", "fact b"]})
    world = {
        "tick": 5, "current_location": "brig",
        "alarm_meter": 3, "alarm_max": 10,
        "inventory": ["nail", "vial"],
        "object_state": {"herbs": "brewed", "lantern": "focused"},
        "npc_state": {"hal": "asleep_drunk"},
        "objectives": {"escape_brig": "active"},
        "known_facts": [],
    }
    r = Reflector(llm=_FakeLLM(response=response), episodic=em)
    result = r.reflect(tick=5, world=world, recent_events=_events())
    # The first fact must be the deterministic state digest.
    assert result["new_facts"][0].startswith("State digest @ t5")
    digest = result["new_facts"][0]
    assert "alarm=3/10" in digest
    assert "nail" in digest and "vial" in digest
    assert "herbs:brewed" in digest
    assert "hal:asleep_drunk" in digest
    # LLM facts still present, capped (4 with the digest).
    assert "fact a" in result["new_facts"]
    assert "fact b" in result["new_facts"]
    assert len(result["new_facts"]) <= 4


def test_state_digest_not_duplicated_when_already_known():
    em = EpisodicMemory()
    world = {
        "tick": 5, "current_location": "brig",
        "alarm_meter": 0, "alarm_max": 10,
        "inventory": [], "object_state": {}, "npc_state": {},
        "objectives": {},
    }
    # Compute the expected digest text by running reflect once.
    response = json.dumps({"summary": "ok", "new_facts": []})
    r = Reflector(llm=_FakeLLM(response=response), episodic=em)
    first = r.reflect(tick=5, world=world, recent_events=_events())
    digest = first["new_facts"][0]
    # Now feed it back as an existing known_fact and re-run.
    world2 = {**world, "known_facts": [digest]}
    second = r.reflect(tick=5, world=world2, recent_events=_events())
    # Digest should NOT be re-prepended because it's already known.
    assert all(not f.startswith("State digest @ t5") for f in second.get("new_facts", []))
