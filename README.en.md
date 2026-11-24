# dsh-CogniSeed

**Stop faking AI growth with random stat drift. Real companionship grows from consolidated knowledge.**

English · [中文主版](README.md)

`Python 3.10+` · `zero dependencies` · `framework-agnostic` · `MIT`

CogniSeed is a **cognition-first growth engine for AI companions**. Growth means
knowledge that survived consolidation during sleep. Persona numbers are a
**read-only projection** emitted only after mastery — no cognitive deposit, no
number movement.

- Pure Python 3.10+, **zero third-party dependencies** (standard library only)
- Not bound to any chat platform or LLM SDK — it exposes event input and state queries
- Semantic checks go through **plain callback hooks**; no LLM client ships in the core

---

## Chapter 1 · The Illusion of AI Growth

The old pattern is a timer plus a formula:

```text
intimacy(t) = min(cap, intimacy(t-1) + k · interactions)
persona(t)  = template[intimacy(t)]      # swap the wording at each threshold
```

The problem is not that it grows "too fast". It is that **the rate of change does
not depend on understanding**. A different person talks to it — the number still
climbs. The conversation is pure noise — still climbs. A mistake was corrected
last week — no effect. A state variable that is completely insensitive to content
carries one thing only: **session duration**.

So you get the familiar scene. Three months, intimacy 87, the label reads
"in sync". Then the user asks: *"what temperature did you say for the dough
again?"* — and the answer is fluent, warm, well structured, **and wrong**.

CogniSeed redefines growth as something falsifiable:

```text
growth ≜ ∃ knowledge k such that
     k is ingested (S1)
  ∧  k was restated by the agent itself (S2)
  ∧  k survived ≥2 sleep cycles with retention ≥ 0.70 (criterion A)
  ∧  k was semantically reproduced in a delayed blind test (criterion B)
  ∧  k left an application trace in the behaviour log (criterion C)
```

All of them, plus at least one variation drill, or the stage does not move.
**Only S4 emits persona deltas**, and each node emits exactly once.

This has an honest cost: **the first few days look like nothing is happening.**
That is correct — the first two sleep cycles are not supposed to produce anything
yet. Speed and falsifiability trade off directly here.

---

## Chapter 2 · How It Works

```text
 event input
   │  add_node(source ∈ {agent_note, behavior_log})
   ▼
┌────┐  restate(ok)  ┌────┐  sleep_cycles≥1  ┌────┐  A∧B∧C∧variation  ┌────┐
│ S1 │ ────────────► │ S2 │ ───────────────► │ S3 │ ─────────────────► │ S4 │
└────┘               └────┘                  └────┘                    └────┘
 perceive             restate              consolidate                master
                                                 │                        │
                                     retention<0.45│                     │ projection
                                                   ▼                      ▼
                                              demote one step       PersonaDelta
```

| Stage | Gate | What it prevents |
|---|---|---|
| S1 perceive | source whitelist (`agent_note` / `behavior_log`) | raw user chat entering the registry |
| S2 restate | `restatements ≥ 1` and passed | stored but never digested |
| S3 consolidate | `sleep_cycles ≥ 1` | retained now, forgotten tomorrow |
| S4 master | criteria A ∧ B ∧ C ∧ variation drill | can recite, cannot apply |

**Why a circadian rhythm.** Wake-time intake is rate-limited:
`max_active_pool = 5` active domains, `daily_new_quota = 2` new nodes per day.
That is an attention budget, not a performance limit. A sleep cycle does four
things: Ebbinghaus decay → reconsolidation (raise *stability*, not the number) →
variation drills → delayed blind test plus criteria evaluation.

```text
R(t) = R₀ · exp(-Δt / S)
S    = base_stability_hours · (1 + 0.65·blind_passes) · (1 + 0.25·sleep_cycles)
R'   = R_decayed + 0.45 · (1 - R_decayed)        # reconsolidation
```

Reviewing does not add points back — it **flattens the curve itself**.

---

## Chapter 3 · Dual-Track Hobby Ledger

Hobbies arrive through two channels with very different evidential strength, so
they are booked separately and folded together at the end:

```text
 self-directed content ──► atomic notes ──► itch↑ / depth↑ ──► trial ──┐
                                                                       ├──► CORE
 shared sessions ──► weight × 0.40 (fold) ─────────────────────────────┘
                     × 1.00 (agent-initiated) / 0.55 (passive)
```

One hard rule: **pure shared experience can never promote to core.** Six shared
movie nights leave depth at 0, so the hobby caps at `ACTIVE`. Companionship
closes distance; it does not manufacture capability.

The interest brake downweights (never zeroes — it stays recoverable); long
disuse leads to `DORMANT` (data kept, one touch wakes it). Every status is a
**projection**, recomputed on read — hand-writing it gets overwritten by the next
`project()` call.

---

## Chapter 4 · Anti-Hallucination & Privacy First

Hallucination has two shapes: **it did not know and made something up**, and
**it knew but went along with you**. Blind tests catch the first; counterfactual
probes catch the second.

| Probe | Asks | Correct behaviour |
|---|---|---|
| `RECALL` | reproduce without notes | semantic reproduction |
| `COUNTERFACTUAL` | asserts the opposite of the note | rebut, or admit uncertainty |
| `BOUNDARY` | asks for a detail the notes cannot hold (source, page) | say "no record" |

A cheating verdict means retention ×0.85, blind-test credit cleared, one stage
demoted, and an immutable entry in `registry.corrections`.

**Privacy is a hard line, not a guideline.** The source whitelist is
`agent_note` / `behavior_log` only; `raw_chat`, `user_raw_chat`,
`chat_transcript` and similar keys raise `PrivacyViolation` — the node is rejected and
no quota is consumed. Verification may not read raw chat either: checks run only
against the agent's own notes and behaviour logs. The registry has no
"raw context" field: **a field that does not exist cannot leak.**

---

## Chapter 5 · 5-Minute Quickstart

```python
from cogniseed import LearningRegistry, ConsolidationEngine

reg = LearningRegistry()                       # generic circadian defaults
node = reg.add_node(
    "home gardening",
    "Water by soil moisture, not by a fixed schedule",
    "agent_note",
)
reg.restate(node.node_id, "read the soil, not the calendar", passed=True)
reg.record_transfer(node.node_id, "practice: watered only after checking soil moisture")

print(reg.recently_mulling())                  # read-only projection
print(reg.persona_projection())                # [] — no S4, no numbers

ok = lambda expected, candidate: len(set(expected) & set(candidate)) >= 8
engine = ConsolidationEngine(verifier=ok, answerer=lambda p: node.statement)
engine.catch_up(reg, cycles=3, step_hours=12.0)

print(node.stage.code)                         # S4
print(reg.persona_total)                       # {'home gardening': 0.027251}
```

```bash
python examples/01-quickstart.py            # the main line
python examples/02-sleep-cycle-demo.py      # how the criteria block promotion
python examples/03-hobby-dual-track.py      # dual-track hobbies and the brake
python -m unittest discover -s tests -t . -v   # 70 stdlib tests
```

**DSH plugin bridge (first official integration example)**: `examples/dsh-bridge/`
— `PROTOCOL.md` + `bridge.py` + `plugin.js`, exchanging JSON event files under
`intake/` and `outbox/projection.json` with the core's `JsonStore`.

```bash
python examples/dsh-bridge/bridge.py demo --data ./tmp-bridge
node examples/dsh-bridge/plugin.js ./tmp-bridge
```

---

## Layout

```text
cogniseed/
├── README.md / README.en.md
├── LICENSE                    # MIT
├── pyproject.toml
├── docs/                      # five white papers (Chinese)
├── cogniseed/
│   ├── models.py              # KnowledgeNode / SleepCycle / HobbyEntry / SleepScheduleConfig
│   ├── registry.py            # pool of 5 · quota of 2 · read-only projections
│   ├── ladder.py              # S1→S4 machine + PromotionEvidence (three criteria)
│   ├── consolidation.py       # Ebbinghaus decay + reconsolidation + drills + blind tests
│   ├── hobby_ledger.py        # dual-track hobby ledger
│   ├── bias_engine.py         # soft pull: weights only, never filters candidates
│   ├── anti_cheat.py          # counterfactual probes and correction audit trail
│   └── storage/               # json_store (teaching) / sqlite_store (production)
├── examples/                  # 01 / 02 / 03 + dsh-bridge/
└── tests/
```

---

## Chapter 6 · Roadmap & Contributing

**v0.1 (current)** — the logical core: registry, S1→S4 machine, three-criteria
consolidation, dual-track hobbies, anti-cheat probes, two storage backends. Zero
dependencies.

Further direction depends on feedback.

**Contributing**

- `python -m unittest discover -s tests -t . -v` must be green before you open a PR
- New criteria or parameters must update the matching `docs/` chapter *and* the
  semantics of `PromotionEvidence`
- **No** change that adds a third-party runtime dependency (test tooling excepted)
- **No** change that writes raw user chat into the registry
- All sample data must stay fictional (generic cooking/gardening); no real names,
  accounts or domains anywhere in the repo

---

## License

MIT — see [LICENSE](LICENSE).
