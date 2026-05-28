# Research: World simulation for multi-agent escape rooms

*A design memo \u2014 2026-05-28.* Goal: stop LLM-driven agents from drifting,
hallucinating entities, and looping on the same action, **without** killing
their creative problem-solving.

---

## 1. The actual failure we are seeing

Phase 4 + the anti-drift stack stopped *delta* hallucination (GM granting
effects with no preconditions). It did **not** stop *action-space*
hallucination on the Player side. Latest 24-tick run:

```
t17\u201324  USE rope_coil_and_folding_knife_on_ceiling_hook on hal_keyring
```

Mira invented a target ID by concatenating three real entity names. None of
our guards catch this because:

- The completed-actions ledger keys on `(verb, target, on)` \u2014 the bogus
  composite name never matches.
- `find_triggered_puzzle` needs the canonical `USE rope_grapple on hal_keyring`.
  The Player never proposes that pair, so the validator never fires.
- The system_hint loop detector triggers but Mira just re-phrases the
  composite slightly differently each retry.

The agent has a **free-form action space over an unbounded vocabulary**.
Every existing guard is *downstream* of action generation. The right fix
is to constrain the action space *upstream*.

---

## 2. What the field does

There are five well-trodden families. None of them in isolation is right
for us; the recommendation in \u00a73 is a hybrid.

### 2.1 Constrained / affordance-grounded action menus (TextWorld, Jericho, LIGHT)

The classic interactive-fiction RL benchmarks all use a **per-turn menu of
legal actions** computed deterministically from the world state.

- **TextWorld** (Microsoft Research, 2018): every step the engine emits the
  full admissible action list; the agent picks one. Hallucinated objects
  are *impossible* by construction.
- **Jericho** (2020) wraps Z-machine games (Zork, etc.) the same way:
  parser-level action validation.
- **LIGHT** (Facebook, 2019) does it in a fantasy chat setting:
  `valid_actions` are computed from object affordances declared in the
  world graph.

Tradeoff: this destroys "say anything" prose freedom on the *action*
channel \u2014 but the *narrative* and *reasoning* channels remain free. In
practice, all modern text-game agents (e.g. CALM, DRRN) use this pattern.

### 2.2 Plan \u2192 Code \u2192 Verify (Voyager, Code-as-Policies, LLM+P)

The LLM is treated as a *planner / coder*, not as a runtime decision-maker.

- **Voyager** (NVIDIA, 2023): in Minecraft, the LLM writes a *skill*
  (JavaScript function) and tests it; verified skills are added to a
  library. Future turns reuse them. Hallucination collapses because
  skills run in the actual game engine; they either work or they don't.
- **Code-as-Policies** (Google, 2022): LLM emits Python that calls a
  closed API of primitives; execution traps the violations.
- **LLM+P** (Liu et al., 2023): LLM translates the goal to PDDL; a
  classical planner (Fast Downward) returns a guaranteed-valid plan; the
  LLM narrates execution.

Tradeoff: requires a well-defined primitive set up-front. For our 4 Act-1
puzzles we *already* have it \u2014 the new `puzzle.*` documents in
`game.jsonl` are essentially STRIPS operators.

### 2.3 Cognitive loops over the action LLM (ReAct, Reflexion, Inner Monologue, RAP)

These wrap the LLM in a metacognitive loop:

- **ReAct** (Yao et al., 2022): interleave Thought \u2192 Action \u2192 Observation.
  We do this already.
- **Reflexion** (Shinn et al., 2023): after a failure, the agent writes a
  *verbal self-critique* and that critique is prepended to the next prompt.
  This is closer to what we need than our current `system_hint`.
- **Inner Monologue** (Huang et al., 2022): inject environment feedback
  (success/failure, scene description) inline so the agent sees the
  consequences of its actions in language.
- **RAP / Tree-of-Thoughts**: search over future action sequences using
  the LLM as both policy and world-model.

Tradeoff: helps recovery but does *not* prevent the first hallucination.
Useful as a second layer, not a first defense.

### 2.4 Simulated society / persistent memory (Generative Agents)

- **Park et al. 2023** ("Smallville"): 25 agents, reflective memory
  stream with importance scoring, retrieval by recency+importance+
  relevance, daily plans.

We already implement the smaller version of this (episodic memory,
reflection, state digest). Worth borrowing the **importance score** so the
ledger doesn't get overwhelmed by trivia in longer runs.

### 2.5 Game-master-as-engine (Inform 7, Mu* MUDs, Dungeon-AI)

Old-school IF wisdom: the *engine* is the rules; the *LLM* is only ever a
narrator. The action loop is fully deterministic; the LLM is a UX layer.
This is exactly the inversion of our current architecture and the most
robust solution \u2014 but it costs creative latitude on the puzzle layer.

---

## 3. Recommendation: \u201cMenu + Skills + Narrator\u201d hybrid

A staged adoption that keeps narrative quality while making
hallucination structurally impossible.

### Stage 1 \u2014 Affordance menu (TextWorld pattern)

Add an **affordance engine** (`server/world/affordances.py`) that, given a
world snapshot, enumerates the set of legal actions:

```python
def legal_actions(world: dict, clues: ClueStore) -> list[Action]:
    out = []
    # EXAMINE: every object_state entry + every inventory + every NPC + every discovered_item
    # TAKE: every object whose corpus doc has takeable=true in the current location
    # COMBINE: every (a, b) pair where a recipe doc has trigger.verb=COMBINE
    # USE: every (item, target) pair from puzzle.trigger when item is in inventory
    # MOVE_TO: every neighbour of current_location
    # WAIT: always
    return out
```

The Player prompt then includes:

```
## Legal actions this tick (you MUST pick exactly one)
1. EXAMINE hal_mug
2. TAKE folding_knife
3. COMBINE rope_coil + folding_knife    \u2192 grapple recipe
4. USE sleeping_draught on hal_mug      \u2192 puzzle.sedate_hal (preconditions met: no)
5. WAIT
...
```

The Player response schema changes from `{verb, target, args}` to
`{choice: <integer>, intent, plan}`. **The composite-name hallucination
becomes impossible** \u2014 there is no slot for it. Free-form prose still
lives in `intent`, `plan`, and `thought`.

This single change would have killed the t17\u201324 loop.

### Stage 2 \u2014 Recipe / combine documents in the corpus

Add `kind: "recipe"` documents (or extend `puzzle`) declaring derived
items:

```jsonl
{"id":"recipe.grapple","kind":"recipe",
 "trigger":{"verb":"COMBINE","ingredients":["rope_coil","folding_knife"]},
 "preconditions":{"inventory_has":["rope_coil","folding_knife"]},
 "effects":{"inventory_remove":["rope_coil","folding_knife"],
            "inventory_add":["rope_grapple"]}}
```

The affordance engine surfaces COMBINE pairs from these. Validator
already in `puzzle_validator.py` extends to cover recipes (\u2248 20 lines).
This explicitly *teaches* the system that `rope_grapple` exists \u2014 today
no corpus doc mentions it.

### Stage 3 \u2014 GM becomes (mostly) a narrator

With Stages 1+2, every action that reaches the GM is already legal and
its effects are already declared. The GM\u2019s remaining responsibilities:

1. Decide stochastic outcomes (e.g. Hal\u2019s `alarm_delta` on retries).
2. Write prose narration consistent with the precomputed delta.
3. Optionally reject \u201cintent-mismatch\u201d cases (player picks legal action
   that nonetheless makes no narrative sense in this scene).

Concretely: the simulation computes the canonical delta from the
selected puzzle/recipe; the GM is asked *only* for `narration` +
`alarm_delta` + `time_advance_min`. The risk of effect-hallucination
drops to near-zero.

### Stage 4 \u2014 Reflexion-style failure memory

Replace the current `system_hint` repeat detector with a Reflexion
buffer: every time an action fails or is short-circuited, the Player\u2019s
*next* prompt gains a `## Lessons from your recent failures` section
generated by the Player LLM itself (one short sentence per recent
failure). This is the only addition that helps *creative* puzzle-solving
\u2014 it lets the agent learn within a single run.

### Stage 5 (optional, longer-term) \u2014 Skill library

Following Voyager: after the Player successfully chains a puzzle, persist
the action sequence as a *named skill* in `data/skills.jsonl`. On
subsequent attempts the affordance engine surfaces the skill as a single
action (`EXECUTE_SKILL escape_brig`). For a single-run PoC this is
overkill; for multi-run replayability (Phase 5) it is essential.

---

## 4. Multi-agent considerations (Phase 5 foresight)

When a second Player agent wakes, the menu approach generalises cleanly:

- The affordance engine emits *per-agent* menus (item visibility,
  location, line-of-sight if you add it later).
- Co-op puzzles get a `requires_simultaneous: [agent_id_1, agent_id_2]`
  field on the puzzle doc; the GM only fires the effect when both agents\u2019
  actions on the same tick satisfy the joint trigger.
- Shared affordance computation prevents the two LLMs from each
  hallucinating different versions of the same scene.

Generative Agents handles the social plane with a shared dialogue
buffer; we already have one (the event log).

---

## 5. What I recommend implementing first

Smallest change with the largest impact: **Stage 1 + Stage 2 only.**
Concretely:

1. New module `server/world/affordances.py` (`legal_actions(world, clues)`).
2. New `kind: "recipe"` docs in `data/game.jsonl` for the three derived
   Act-1 items (`tainted_draught`, `rope_grapple`, etc. \u2014 audit the
   canonical solution and declare each).
3. Update `PLAYER_ACTION_SCHEMA` to a `{choice: int, intent, plan}` form
   (keep the verb-shape as a fallback for backward compat in tests).
4. Player prompt: replace ad-hoc rules section with the legal-actions
   menu.
5. Simulation: validate the chosen index, look up the action, run it
   through the (mostly unchanged) GM flow.
6. Tests: affordance enumerator for a known world state; recipe
   validator; menu-choice player.

Estimated impact: the t17\u201324 hallucination loop becomes structurally
impossible; the canonical 13-tick path remains the optimal solution and
shouldn\u2019t get longer; mock smoke continues to work because the mock
player already proposes valid actions.

---

## 6. References

- C\u00f4t\u00e9 et al., *TextWorld: A Learning Environment for Text-Based
  Games*, 2018.
- Hausknecht et al., *Interactive Fiction Games: A Colossal Adventure*
  (Jericho), AAAI 2020.
- Urbanek et al., *LIGHT: Learning in Interactive Games with Humans and
  Text*, EMNLP 2019.
- Yao et al., *ReAct: Synergizing Reasoning and Acting in Language
  Models*, 2022.
- Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement
  Learning*, 2023.
- Huang et al., *Inner Monologue: Embodied Reasoning through Planning
  with Language Models*, 2022.
- Park et al., *Generative Agents: Interactive Simulacra of Human
  Behavior*, UIST 2023.
- Wang et al., *Voyager: An Open-Ended Embodied Agent with Large
  Language Models*, 2023.
- Liang et al., *Code as Policies: Language Model Programs for Embodied
  Control*, 2022.
- Liu et al., *LLM+P: Empowering Large Language Models with Optimal
  Planning Proficiency*, 2023.
- Yao et al., *Keep CALM and Explore: Language Models for Action
  Generation in Text-based Games*, EMNLP 2020.
