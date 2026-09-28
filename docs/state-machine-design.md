# JEV as a state machine: deterministic transitions with model-driven choices

Working notes, 2026-09-28. Starting point: the Radioactive Run referee
(`Resources/Web/index.html`, `runGridGame` and the `rr*` functions) and the
Parallel & agentic patterns suite in the gateway (`scripts/jev_gateway.py`,
`intent-routing`, `composite-scoring`, `confidence-routing`, speculative
fan-out cases).

## 1. What the grid run already proves

The Radioactive Run is not a "model plays a game" demo. It is a state machine
whose transition function is deliberately split in two:

- **The code owns the state.** Position, step count, budget, furthest column,
  visit counts, dead-end and pocket flags, the fog-of-war known map, the
  recent-steps history — all computed and applied in deterministic code
  (`rrApplyMove`, `rrRecordDecision`). The model never mutates state.
- **The model only selects among legal transitions.** `rrLegalMoves` computes
  the action space; the model answers one bounded Choice among those ids
  (`moveRequest`). Free-form generation is off the critical path entirely.

Everything deterministic a state machine needs is already implemented:

| State-machine concept | Grid run implementation |
| --- | --- |
| State | token pos, visits, flags, known map, budget, history |
| Action space | `rrLegalMoves` — code-computed, always legal |
| Transition | `rrApplyMove` — code-applied, model-chosen |
| Guard (trivial) | forced move when `legal.length === 1` ("physics, not strategy") |
| Guard (retry) | invalid answers retried at 1 s / 2 s; provider errors at 3 s / 6 s; 3 attempts cap |
| Termination | exit · budget (4× shortest or +40) · stop · provider change · 3 fails |
| Derived state summaries | memory aids (map → facts → pockets), derived only from observed cells |
| Bounded context | 7,000-char cap, ±15-column window, last 20 steps |
| Replay | seed + width rebuilds the identical board; runs export as JSON |

Measured properties from this workspace: local JEV decisions at 0.62 s mean
(11/11 baselines) vs 2.99 s Ollama chat; full per-choice probability
distributions returned by local and TypeSafe providers; invalid-response and
flag-adherence metrics already recorded per run.

## 2. Where the TypeSafe patterns slot in

The four patterns demoed in the Workbench are exactly the standard state
machine extensions. Mapping, with what is real vs demo today:

| TypeSafe pattern | State-machine role | Status |
| --- | --- | --- |
| Parallel questions | Classify the current state on several typed axes in **one** request (situation, risk, blocked-path) — the endpoint scores all fields against the shared context in parallel, so extra fields are nearly free | real endpoint capability; unused by the grid run today |
| Intent routing | Classify the *situation* first, then let a deterministic route table pick the policy (corridor → straight-ahead rule; junction → explore; loop detected → backtrack policy) | routing demo is Workbench-side; the pattern is what a policy layer needs |
| Confidence routing | **Gate transitions on the distribution, not the argmax.** High top-probability → commit to the model's move; low → deterministic fallback (heuristic move) or escalate to the TypeSafe watermark for a second opinion | demo thresholds exist; the gateway already returns full distributions for local + TypeSafe |
| Composite scoring | Score candidate transitions on weighted criteria (progress, risk, exploration, loop-avoidance) and let **code** pick the argmax — policy lives in weights, not in model taste | demo weights exist; tree distributions make each score a proper weighted value |
| Speculative fan-out | Look-ahead without generation: score each candidate move's *hypothetical* next state as parallel fields, pick the best-scoring branch | demo exists; each branch is one bounded Choice, not a text generation |

## 3. How local models get better outcomes

The lever is not a better prompt. It is moving determinism into the harness:

1. **Policy in the schema, not the prompt.** Each legal move already carries
   its own machine-derived criteria text (`rrMoveCriteria` — visit counts,
   dead-end flags, neighbour facts). This request adaptation is the same one
   that moved CLM from 4/11 to 8/11 and 5/100 to 85/100 on the logic suites.
2. **Distribution-gated transitions.** Local JEV and TypeSafe return full
   choice distributions. A guard turns "the model is sometimes wrong" into
   "the model is only trusted when it is confident, and the confidence is
   calibrated against measured outcomes." Wrong-but-confident transitions are
   directly countable today (flags ignored with flags shown).
3. **Deterministic fallback ladder.** Low confidence → heuristic move
   (least-visited, forward-preferring — the guidance already in the prompt,
   but applied by code instead of asked of the model). The state machine
   never stalls and never hallucinates a move; worst case it degrades to a
   classical agent.
4. **Watermark cross-checks.** TypeSafe answers the identical transition
   request; local-vs-watermark agreement per state type is a calibration
   signal — extend the cross-provider judge methodology (shuffled, replayed,
   majority) to per-transition agreement.
5. **Derived state summaries over raw logs.** The memory-aid ladder (map →
   facts → pockets) is the experiment harness for how much derived state a
   model of a given size can exploit — already recorded per run.

## 4. Shipped: parallel token races in the grid run

The grid run now has a parallel-token selector (1–4). A race starts that many
independent state machines on the same seeded field; each round fires every
running token's decision request **concurrently** (`Promise.all`), so
wall-clock per round is one decision latency regardless of token count. Each
token is recorded as its own run (`race.token`) in the existing comparison
table; one token failing its retry ladder drops out of the race without
killing the others; Stop aborts the whole race.

First live result (TypeSafe `jev-latest` watermark, 2 tokens, 20×40 field,
seed `3428655726`, 2026-09-28): both tokens completed 49 moves (shortest 43,
88% efficiency), 48 decisions each, avg 293 ms/decision, avg confidence 0.97,
0 invalid / 0 retries — **14.8 s wall clock for both streams**, roughly half
the sequential time. The local engine was built with `--decision-seqs 12`, so
the same race applies to local models unchanged (select the local provider in
the menu-bar app).

Honest finding: same seed + same model + deterministic scoring means the
tokens took **identical paths** — a same-model race measures concurrency and
throughput, not path diversity. Path diversity (and the scout/waypoint
evaluation below) needs per-token provider selection, which requires a small
gateway extension: a backend-override parameter on the decision request so
one token can run on the TypeSafe watermark while another runs on local
gemma. That same override is the hook for the predetermined-path evaluation:
T1 maps the course, later tokens follow it.

## 5. Shipped: guided runs (scout → follow)

The grid run now has a **Follow mapped route** toggle. When the field has a
completed run, a new run inherits that run's observations (its known map),
receives the upcoming route segment in its context ("Mapped route from a
previous run: …"), and sees the route's next move marked in its choice
criteria. The referee still computes legality and applies every move; the
model still makes every non-forced choice. Per-run metrics add **route kept**
(share of model decisions that matched the guide's next move). The first
completed run on a field is the scout; later runs — for example a different
model — follow it.

First paired result (20×40 field, seed 3428655726, 2026-09-28). The first
guided implementation layered the route on top of the full exploration context
and ran at the same speed as unguided — decision latency is dominated by
prefill, not by how hard the choice is, so the follower was paying for
exploration state it no longer needed. The fix: while on the mapped route the
follower sends a **slim context** (goal, position, route chain, legal moves —
no map, no memory aids, no history) and falls back to the full context only
when off-route. Slim-context result:

| run | status | moves (shortest 43) | decisions | avg ms | conf | route kept | elapsed |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| gemma guided, slim context (TypeSafe T2 route) | completed | 43 · eff 100% | 43 | **1,552** | **1.000** | **100%** | **67 s** |
| gemma unguided (explores alone) | completed | 43 · eff 100% | 43 | 4,724 | 0.995 | — | 203 s |

Following the mapped route is now **~3× faster end to end** than exploring,
with perfect route adherence and saturated confidence. The lesson generalises:
a guided transition should carry only the state the transition needs — the
deterministic reference replaces exploration state, and the context shrink is
where the speed comes from.

## 6. Proposed next: policy modes in the grid run

Add a per-run **policy** selector beside the existing memory-aid selector, so
the same seeded field compares policies in the existing table:

- **raw** — current behaviour; model picks, code applies (baseline).
- **gated** — model picks; if top probability < τ (default 0.5, adjustable),
  the code applies the deterministic heuristic instead and marks the step.
- **scored** — one parallel Score field per legal move (progress, risk,
  reuse), code picks the weighted argmax; the model evaluates, code decides.

The table already records everything these policies need for comparison:
efficiency vs shortest path, revisits, dead-end/pocket cells, flags ignored
(seen vs unseen), invalid responses, retries, average decision time and
confidence. A fourth, later mode — **fan-out** — would score the hypothetical
next state of each legal move and pick the best branch.

After the grid proves the pattern, the same referee skeleton transfers to the
target domains directly: legal-action computation in code, one typed Choice
per transition, distribution gates, deterministic fallbacks — warehouse
racking, stack sequencing, robotic movement. The state machine is the
product; the model is a pluggable transition adviser.

## 7. What this does not claim

Confidence from tree scoring is a provider signal, not calibrated truth.
The heuristic fallback is only as good as its coded policy. Policy
comparisons are meaningful only on identical seeds (already enforced), and
single runs are anecdotal until repeated across seeds. The TypeSafe
watermark is a comparison signal, not ground truth.
