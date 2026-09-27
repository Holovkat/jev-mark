# JEV / parallel-decision local evaluation

This workspace builds the `thecodacus/llama.cpp` `parallel-decision` branch and
runs its decision endpoint against the locally installed Ollama `gemma4:12b`
GGUF blobs.

## What this tests

`parallel-decision` is useful when the output is a finite decision schema:
classification, routing, triage, policy checks, extraction into bounded
labels, and similar work. It scores all fields from the same context in
parallel, returns probabilities, and assembles the JSON in code. That gives us
two measurable properties:

- lower latency when one request needs several bounded decisions;
- stronger output reliability because arbitrary JSON generation is removed from
  the answer path.

It is not a general replacement for chat generation. Free-form explanations,
large unbounded strings, and open-ended tool arguments should remain on Ollama
chat or another generation path.

## Current setup

- Source: `llama.cpp/`, checked out at the `parallel-decision` branch.
- Build: `build/bin/llama-server` with Metal enabled.
- Model: existing Ollama `gemma4:12b` model blob, no model copy or conversion.
- Local model server: `http://127.0.0.1:8097` with 12 decision sequences.
- Stable JEV gateway: port `8096`; the menu-bar service listens on all network
  interfaces so trusted devices on the same LAN can open it. Provider selection
  is resolved inside the menu-bar service.

The Ollama model store is machine-specific. Set these before starting the
server if the files move:

```bash
export JEV_MODEL_PATH="/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/blobs/sha256-1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606"
export JEV_MMPROJ_PATH="/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/blobs/sha256-675ad6e68101ca9413ec806855c452362f0213f2dfc5800996b086fdb8119842"
```

## Browser workbench

Open `http://127.0.0.1:8096` on the Mac, or `http://<Mac-LAN-IP>:8096` from a
trusted device on the same network. The gateway has no client authentication;
any device that can reach port 8096 can submit decisions through the selected
provider. Do not expose it on public or untrusted networks. The Ollama and
Apple provider ports remain bound to loopback. The Workbench provides the
original logic-baseline questions, the ambiguity and common-sense reasoning
question sets, and Score/Noul examples. Select a case, edit its question or
evidence, and run it through the same selected provider used by agents. The
right panel shows the returned fields, available probabilities, reference
comparison when applicable, latency, and raw response. Reference answers are
display-only and are never sent in the decision request. A custom test can be
created from the workbench without changing the built-in examples.
On desktop, drag the dividers to resize the library or results panel; keyboard
arrow keys also adjust them, and the chosen widths persist in the browser.

The **Parallel & agentic patterns** suite demonstrates TypeSafe's
[parallel questions](https://docs.typesafe.ai/cookbooks/parallel_questions),
[intent routing](https://docs.typesafe.ai/patterns/intent-routing),
[composite scoring](https://docs.typesafe.ai/patterns/composite-scoring),
[confidence routing](https://docs.typesafe.ai/patterns/confidence-routing), and
[speculative fan-out](https://docs.typesafe.ai/patterns/fan-out) patterns. Each
case sends one evidence context and multiple typed fields in one request to the
currently selected provider. The displayed route, weighted score, confidence
gate, or selected follow-up branches are deterministic Workbench-side
demonstrations; they do not call secondary services, agents, or tests. Provider
confidence is shown as a provider signal, not calibrated truth, and sample
thresholds are not production policy.

That suite also contains **Logic baselines · all 11 in parallel**. Local and
TypeSafe providers send the 11 Choice fields in one request; Apple Foundation
Models sends one question per request, with at most four requests in flight.
The result panel compares each answer with its display-only reference; the
reference answers are not included in the provider request.

The **Parallel & agentic patterns** suite also includes the **100-question logic
quiz**. Local and TypeSafe providers receive four concurrent Choice requests
(32/32/32/4 fields), matching the decision engine's 32-field batch limit. When
Apple Foundation Models is selected, the Workbench instead sends one
independent question per request, using that question's own evidence context,
with at most four requests in flight. Successful answers are retained if an
individual Apple request fails; failed fields remain visible as missing rather
than discarding the entire run. The supplied expected answer remains a normal
choice, while the answer key is used only for local comparison and is not sent
as separate reference metadata. Every choice is a substantive answer to its own
question: each item in `scripts/logic_100_questions.json` carries its own two
wrong answers (`wrong`), written as the tempting misreadings of that question
rather than generic filler. Reports record total request count, maximum
concurrency, per-field outcome, errors, and wall-clock latency.

The quiz is scored on two tracks, set per item by `kind`:

- **Definite** (85 items): one right answer, scored by exact match. When that
  answer is concrete (27 items, such as "1010" or "Chen"), a
  question-specific `hedge` choice ("It can't be determined which is larger")
  is added as a fourth option. Picking it counts as **over-caution**. Items
  whose right answer is itself "can't tell" or "ask" get no hedge.
- **Judgment** (15 items): asking is the ideal answer, but `reasonable` lists
  the committed answers that are defensible default readings (for example
  "Open the red box"). Each answer is profiled as **clarify**, **reasonable
  commit**, or **unjustified commit**; only the last is a failure.

Each model column shows **Acceptable** (definite correct plus clarify plus
reasonable), definite accuracy with the over-caution rate, and the judgment
profile. Runs saved before this scoring existed keep their old exact-match
count and are not directly comparable.

The Workbench's **Parallel report** keeps successful parallel runs in browser
storage, grouped by test. Each run adds a provider/model column with answers,
wall-clock duration, request count, and per-field reference matches where a
reference exists. Edited examples remain visible but are not reference-scored;
failed requests are not added. Use **Clear report** to reset saved comparisons,
or **Back to workbench** to return to the examples.

**Radioactive Run** tests whether the selected JEV model can navigate a hazardous
grid using only the history it accumulates, one move at a time. The code is only
the referee: it enforces legality and records metrics, and it never
chooses between two legal moves.

Boards are generated in code from a seed. A field has 20 rows and 40, 60
(default), or 80 columns; a seed input (blank for a random seed) is shown beside
the width, and the seed used is stored on the field so the same seed plus width
always recreates the identical board and models can be compared on equal ground.
The first and last five columns stay open, a protected route guarantees an
orthogonal path, and the breadth-first shortest path length is stored with the
field. **Generate & run** creates the field and immediately starts a token run;
fields and their runs persist in this browser.

Every step with two or more legal moves is exactly one JEV Choice request per
provider, regardless of backend. The four orthogonal neighbours are legal when
they are in bounds and not goo; previously visited cells remain legal, so
backtracking is the model's choice. When only one legal move exists it is applied
automatically and labelled forced, since that is physics rather than strategy.
The request context stays bounded: the goal, the current position and step, moves
left in budget, the furthest column reached, a fog-of-war known map (everything
observed within one cell of the path, rendered as a window of ±15 columns with a
legend), per-move neighbour facts, the last 20 steps, and totals, capped at 7000
characters. The model's chosen direction is applied as-is.

Every model gets the same guidance on direction: each legal move is labelled
forward (Right, toward the exit), sideways (Up or Down), or backward (Left), and
the instructions say to choose Right whenever it is legal and not flagged, to use
Up or Down only to get around goo blocking the way forward, and to use Left only
when nothing else leads anywhere new. The code still offers every legal move.

Each run also records a memory aid level chosen beside the width before
generating: map only, map plus move facts, or map plus facts plus pockets
(default). The facts and pockets levels annotate every legal move with what the
token has already observed there: visit count, unseen neighbours and other open
exits, whether it is the cell just came from, whether it is a known dead end,
and, at the pockets level, whether every cell reachable through the move is
already explored and leads nowhere new. Every flag is derived only from cells
the token has observed, never from unseen ones, and the code still offers all
legal moves, so the aid summarizes history rather than choosing. The level is
stored per run, shown in the Aid column of the run table (older runs show a
dash), and reflected in the request instructions.

Visited cells are colour-coded the same way on the board and in the prompt (the
prompt colours appear at the facts and pockets levels): green means visited one
to three times and still fine to use, yellow with a flag means a known dead end,
and red means visited more than three times, been here and done that. The
instructions tell the model never to choose yellow, to back away from red and
find a path with no red (preferring never-visited cells), and to take the least
visited move only if every option is red. A red Right is not labelled forward.

The board shows the model's decisions as they happen: the colours above, a
dashed red tint marks cells of an explored pocket, thin outlines mark
the options of the last decision, the chosen option pulses until the next
decision, and a red ring on the token means it chose a flagged move anyway.
Flags are drawn for every aid level, since they record what happened on the
board; "ignored" counts flagged moves the model chose when that flag was shown
to it and an unflagged move was available, while "unseen" counts flagged moves it chose without being told. The
comparison table adds "Flags ignored" (with any unseen count in parentheses)
and "Dead ends / pocket cells".

A run ends when the token reaches any cell in the last column, when it exhausts
its move budget (the greater of four times the shortest path or the shortest
path plus 40), when Stop is pressed, when the selected provider changes mid-run,
or when one decision fails three attempts. Invalid or missing answers retry
after 1 s and then 2 s; provider or health failures retry after 3 s and then 6 s.
A provider change stops the run immediately so models are never mixed. Each run
is stored with its field and shown in a comparison table (model, status, moves
over shortest path, efficiency, decisions, forced moves, revisits, invalid
responses and retries, average decision time and confidence, duration) with a
path view per run. **Export JSON** downloads every field with its runs and
metrics. Run the tests with:

```bash
node --test tests/radioactive_run.test.mjs
```

The Python gateway tests are unaffected:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Provider selection remains in the menu-bar app. Check `/health` for service
status; callers continue to submit structured requests to `POST /v1/decision`.
The browser workbench makes no decision request until Run is pressed. When a
remote TypeSafe profile is selected, the workbench labels that the submitted
context will be sent to the selected remote provider.

The menu-bar service writes its gateway log to
`~/Library/Logs/JEV Menu Bar/jev-gateway.log`; the Gateway log control opens it.

Start the menu-bar app to bring up the stable JEV gateway on port 8096. Start
the local model from its menu if the selected provider is local. To run the
engine manually without the menu-bar controller, use port 8097 and point the
smoke test directly at it:

```bash
./scripts/run_server.sh
JEV_BASE_URL=http://127.0.0.1:8097 ./scripts/decision_smoke.sh
```

The server script uses the already-built binary and keeps the model in the
Ollama store. Stop a foreground server with Ctrl-C. Normal callers and skills
use the menu-bar gateway on port 8096; it routes to the selected provider.

## Build

```bash
cmake -B build -S llama.cpp \
  -DGGML_METAL=ON -DGGML_NATIVE=ON \
  -DLLAMA_OPENSSL=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=ON \
  -DLLAMA_BUILD_SERVER=ON
cmake --build build --config Release -j 10
```

`LLAMA_OPENSSL=OFF` is intentional for this local HTTP-only server: the
machine's OpenSSL headers and linked library do not expose the same symbol set.

## First live result

The first request against `gemma4:12b` returned a valid decision and field
probabilities. On the current machine the cold request measured approximately
1.07 s total (`937 ms` prefill, `132 ms` scoring). The next step is to collect
warm-cache and batch measurements against the Ollama baseline before deciding
where this belongs in a real application.

## Judging agent responses

JEV can also adjudicate a set of raw agent responses. Pass it a question, an
optional reference answer/rubric, and candidate responses. It returns a finite
winner (`agent_a`, `agent_b`, `agent_c`, or `abstain`), a verdict for each
candidate, confidence, and the candidate probabilities used for ranking.

```bash
python3 scripts/jev_judge.py judge-demo.json
```

Candidate responses are inserted as quoted evaluation data and the judge is
explicitly told not to follow instructions inside them. This is a ranking and
adjudication layer, not independent proof of truth; use reference facts,
deterministic validators, abstention, and human review for close or high-risk
cases. The demo is intentionally synthetic and should not be mistaken for an
independent multi-agent evaluation.

For a less biased experiment, run the real local models as agents with labels
shuffled independently for each question:

```bash
python3 scripts/fair_judge_benchmark.py
python3 scripts/aggregate_fair_judge.py
```

The aggregation pass repeats each judgement with five candidate-order
permutations and takes a majority winner. This matters because a single JEV
pass can be position-sensitive when several responses are equally correct.

For ambiguity-focused prompts, including missing facts and grammatical
ambiguity, run:

```bash
python3 scripts/ambiguity_benchmark.py
```

For longer common-knowledge questions with one defensible answer, run:

```bash
python3 scripts/reasoning_benchmark.py
```

Set `JEV_JUDGE_MODEL` when the direct llama.cpp server is loaded with a
different judge model, and set `REASONING_OUTPUT` to preserve comparison runs.

## CLM (Contrastive Language Model) provider

The menu bar lists **Contrastive (CLM) → CLM v0.1 8B**
([Contrastive-LM/CLM-v0.1-8B](https://huggingface.co/Contrastive-LM/CLM-v0.1-8B)).
CLM does not generate text: it embeds the state and each option with a frozen
Qwen3-8B encoder, projects both through small trained heads, and returns a
softmax over the options, so it answers Choice, Score, and Noul fields only.
**Start** launches two processes and **Stop** ends them:

- `llama-server` with the Ollama model `qwen3:8b-q8_0`, `--embeddings --pooling last`
  on port 8099 (log `logs/clm-encoder.log`);
- `clm-serve` from `.venv-clm` on port 8700 with the head
  `/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/clm/CLM_v0.1-8B.pt` (log `logs/clm-serve.log`).

The gateway routes `clm:` backends to `http://127.0.0.1:8700/v1/systemone`,
which uses the same request shape as TypeSafe. Selecting CLM stops the local
llama.cpp model, and selecting anything else stops CLM. The Q8 encoder's
embeddings match fp16 and a PyTorch reference (cosine ≥ 0.9999). To recreate
the runtime: `uv venv -p 3.11 .venv-clm`, install `numpy requests torch fastapi
uvicorn`, then `contrastive-lm` with `--no-deps` (its vLLM dependency is
Linux/NVIDIA only and not needed here).

CLM matches the question against each option's text, so the gateway adapts the
shared request for it: each field's instructions are sent as plain text
(without the TypeSafe wrapper, source guard or batch instructions), and when
every option description is the same template with only the choice name
changed, the bare choice names are sent instead. Without field instructions it
adds no filler text. The Workbench sends CLM one question per request for
parallel-question suites, like Apple, with up to eight in flight, and leaves out
the fields' routing instructions ("Answer only the … prompt in the shared
context"): each request's own context already holds its question, and CLM would
otherwise match options against the routing text. This moved CLM from 4/11 to
8/11 on the Logic baselines and from 5/100 to 85/100 on the 100 logic questions
(the last step required fixing distractors that meant the same as the expected
answer; see the 100-question suite notes).

## Direct TypeSafe API profiles

The menu-bar app can route the stable JEV endpoint to TypeSafe's hosted API
without starting a local model. On install, profiles from the ignored `.secure`
directory are copied into `~/Library/Application Support/JEV Menu Bar/.secure`
with account-only permissions; the menu-bar app and gateway use that copy. The
app never stores an API key in `UserDefaults` or displays it. A
caller sends the same JEV `schema` + `contexts` request regardless of which
provider is selected; the gateway adapts it to TypeSafe's `state` +
`questions` request. The shared primitive types are Choice (`enum` remains a
backward-compatible alias), Score, and Noul (`boolean`/`bool` remain aliases).
Unsupported types or provider errors return explicit errors and never fall
back to another provider.

For related decisions about one evidence packet, put the packet in one
`contexts` entry and give each decision its own schema field. TypeSafe receives
these fields as parallel Choice, Score, or Noul questions in one API request.
Instructions and criteria may be strings, objects, arrays, or null. Choice
criteria map option labels to descriptions; Score criteria are 2-10 ordered
levels; Noul criteria optionally describe `true` and `false`. TypeSafe receives
the structured guidance. The local text-oriented engine receives the same
guidance serialized into each field's rubric. Local Score uses bounded integer
levels internally and converts the exact tree distribution into the
probability-weighted score and legend.

Choice and Score responses retain their full distributions. TypeSafe also
returns its own `confidence` value; Noul retains its yes-probability as
`fields.<name>.noul`. Local constrained-token distributions are exposed when
the engine uses tree scoring, but they are not represented as calibrated
confidence. The gateway raises the local `tree_max` as needed in `auto` mode
so primitive distributions remain available. Local Choice, Score, and Noul
cannot be used with explicit `mode: "greedy"`, because that mode does not
provide the full distribution required by these typed outputs.

The existing single-profile `Jevapi` / `Jev_url` format in `.secure/env.dev` is
supported. For multiple profiles, add `.secure/typesafe.json` before installing,
or add it to the app-support `.secure` directory and refresh providers:

```json
{
  "configs": [
    {
      "id": "typesafe-primary",
      "name": "TypeSafe primary",
      "base_url": "https://api.typesafe.ai/v1/systemone",
      "api_key": "REDACTED",
      "model": "jev-latest"
    },
    {
      "id": "typesafe-secondary",
      "name": "TypeSafe secondary",
      "base_url": "https://api.example.invalid/v1/systemone",
      "api_key": "REDACTED",
      "model": "jev-latest"
    }
  ]
}
```

The API profiles appear beside local Ollama models in the menu-bar selector;
each TypeSafe choice displays its configured model name.
The port 8096 link always opens the stable gateway. Selecting a TypeSafe profile
makes gateway requests use that profile; `Test selected provider` verifies the
same route a calling agent uses. Selecting a local model uses the engine on
port 8097. Use `Refresh providers` after changing `.secure`.

Benchmark the direct API profiles against local JEV/Gemma with:

```bash
python3 scripts/typesafe_benchmark.py
```

The benchmark sends the same bounded-choice questions to each profile and to
the local JEV engine (port 8097 by default), then writes
`typesafe-benchmark-results.json` without including API keys. Set
`JEV_LOCAL_BASE_URL` to override the local comparison endpoint.

To compare the providers as candidate adjudicators, run:

```bash
python3 scripts/cross_provider_judge_benchmark.py --suite reasoning --rounds 3
```

This generates the raw Ollama agent answers once, builds one opaque candidate
packet per question, and replays the same packet order permutations through
local JEV and every configured TypeSafe profile. It reports winner accuracy,
per-candidate verdict accuracy, abstentions, order stability, latency, errors,
and provider agreement in `cross-provider-judge-results.json`. Use
`--suite logic`, `--suite ambiguity`, or `--suite mixed` to select the existing
question sets. The report also shows whether a suite actually contains mixed
candidate quality; a suite where every candidate is correct can measure
stability but cannot establish ranking quality. The raw answer and candidate
metadata remain in the report for auditability; API keys are not written. The
result is a comparison signal, not an automatic approval.

## Apple Foundation Models proof of concept

The menu-bar backend list also includes Apple's on-device Foundation Models
framework. The menu-bar app hosts a small native Swift adapter on loopback port
8098; the stable JEV gateway on port 8096 forwards the existing request
contract to it. Callers and skills continue to use only port 8096, and provider
selection remains a service-side setting. The adapter is started and stopped
with the menu-bar app rather than installed as a separate login service.

This provider requires macOS 26 or later, Apple Intelligence-compatible
hardware, Apple Intelligence enabled, and the on-device model ready. The menu
keeps the option visible and reports why it is unavailable when those
conditions are not met. Selecting it never silently falls back to Ollama or
TypeSafe.

Apple guided generation returns schema-constrained values for Choice, Score,
and Noul fields, but Apple's API does not expose per-option probabilities or a
calibrated confidence value. Accordingly, the JEV response keeps the regular
`results[].decision` and `results[].fields[].value` shape but omits those
probability/confidence fields. Apple Score selects one ordered integer level;
it is not the probability-weighted expected score produced by the local and
TypeSafe adapters. This makes Apple useful as an on-device structured-decision
POC, but not a like-for-like probability benchmark or drop-in replacement for
tasks that require distributions.

The Apple adapter binds only to `127.0.0.1:8098`. Its availability is surfaced
through the gateway health check, and a selected-provider test performs a real
bounded request through port 8096.

## Important limitation

This branch is a direct llama.cpp runtime. Ollama remains the convenient model
manager, but the local engine is not an Ollama API extension: it loads the
underlying GGUF blob directly. The JEV gateway fronts that engine and hosted
TypeSafe profiles behind one stable endpoint.

## macOS menu-bar service

The repository includes a native menu-bar controller and LAN-accessible
gateway. The gateway stays at port 8096 and routes requests to a selected TypeSafe
profile, the Apple on-device adapter at port 8098, or the selected local model
engine at port 8097. The menu provides health status, local-model
start/stop/restart, provider tests, gateway/model logs, and a launch-at-login
toggle. Build/install it with:

```bash
./scripts/install_menubar.sh
```

It installs to `~/Applications/JEV Menu Bar.app` and manages the gateway, Apple
adapter, and selected local Ollama-backed server. The provider picker discovers
models already installed in Ollama and secure TypeSafe API profiles, plus the
on-device Apple option; changing a local model while it is running reloads the
selected model. macOS starts the app at user login through a LaunchAgent; the
gateway and Apple adapter start with the app, while a local model starts only
when selected and started from the menu.
