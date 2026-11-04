# Strata assessment

## Current decision and shutdown context - 14 October 2026

The custom llama.cpp has since received the upstream hybrid batching improvement
while retaining our mods. See [runtime update](llama-runtime-update.md) for the
installed version, regression evidence and rollback. The Strata comparison below
remains the recorded pre-update measurement; no new speed comparison was run.

Keep the existing custom llama.cpp decision engine as our local baseline. The
Strata experiment is retained for future investigation and comparison, with its
services stopped. Shutdown was checked against processes and the experiment
port ranges 51240-51259 and 51380-51399: no listeners remained. Installed JEV and
Ollama were left intact. This is not a change to the selected gateway provider.

Why this exists: investigate whether Strata's advertised inference improvements
can accelerate our native System One decisions. The owner required Nimble on
both engines, with identical weights and native candidate scoring, plus single
and parallel decisions. A Qwen generation benchmark or MLX-only comparison does
not answer that question. The local fork therefore implements Nimble's dense
Qwen3.5 architecture directly in Strata C++/Metal.

Findings on the M1 Ultra, with the same Nimble BF16 GGUF:

| Decisions | Custom llama.cpp | Strata C++/Metal |
| --- | ---: | ---: |
| One single | 91.67 ms | 206.79 ms |
| Four sequential | 367.24 ms | 916.08 ms |
| Four parallel | 191.33 ms | 1624.41 ms |
| Eight sequential | 756.76 ms | 1954.13 ms |
| Eight parallel | 341.90 ms | 2338.68 ms |

These are warm medians from three repetitions, with only one experiment engine
resident at a time. All 100 selected answers agreed, and both engines scored
92/100 acceptable. Strata's single/parallel distributions matched exactly;
cross-engine probabilities differed by up to 1.65 percentage points. State
isolation checks and 314 existing Strata server tests passed.

We continue with llama.cpp because it was faster in every measured native
Nimble case. This Strata port is a working experiment, not an available speed
boost. Do not restart it or switch routing automatically. Larger prefill batches
and fewer per-branch dispatches are possible future investigations, with no
measured speed advantage promised.

Reports retained in this repository:

- [Native C++/Metal report and reproduction commands](strata/NIMBLE-METAL-RESULTS.md)
- [Native comparison results](strata/native-metal-comparison.json)
- [Earlier MLX comparison, retained separately](strata/NIMBLE-RESULTS.md)
- [Implementation context](strata/NIMBLE-IMPLEMENTATION.md)

Engine source forks:

- [Holovkat/Strata, experiment branch](https://github.com/Holovkat/Strata/tree/codex/nimble-native-decisions)
- [Holovkat/llama.cpp, custom decision branch](https://github.com/Holovkat/llama.cpp/tree/codex/nimble-native-decisions)

Local checkouts are `/Volumes/Seagate/workspace/jev-strata-nimble` and
`/Volumes/Seagate/workspace/jev-llama-nimble`. Full raw benchmark/verification
evidence and derived weights remain in the Strata fork's `.worktree-runtime/`;
model weights, environments and runtime caches are not published. The owner
subsequently authorized creating the GitHub forks and pushing source and reports.
Earlier "no push" statements in the reports describe the original experiment.

## Original assessment and investigation (historical)

The assessment below predates the completed native Nimble port. Its feasibility
recommendations and "no benchmark performed" statements are historical; the
measured findings above govern the current decision.

Checked 14 October 2026 against live upstream documentation and the installed
JEV gateway. No runtime, model, provider configuration or selection was changed.

## Finding

The project behind the recent llama.cpp speed comparisons is
[Niko1221/Strata](https://github.com/Niko1221/Strata). It specializes in
Qwen3.8-Flash-Next, using expert placement, specialized kernels and speculative
decoding. It uses parts of llama.cpp/ggml; it is not a general replacement for
every model llama.cpp runs.

Its new [Mac engine](https://github.com/Niko1221/Strata/blob/main/docs/MAC.md)
uses Metal and supports Apple Silicon on macOS 15 or later. Upstream reports
Q2_0 story decoding of 108.2 tokens/s with its setup defaults against llama.cpp's
56.6 on an M5 Max with 128 GB. These are upstream generation measurements, not
JEV decision benchmarks or measurements on this machine.

The current machine is an M1 Ultra with 64 GiB unified memory. Upstream's Mac
recommendation starts Q2_0 at 64 GB, with about 46 GB needed and roughly 73 GB
of downloads/preparation. M1 Ultra performance is unverified. The Mac engine
currently queues requests one at a time. Streaming from external storage is
untested upstream; this matters because existing JEV model storage is external.

## Compatibility with existing JEV providers

Live `/providers` includes Ollama Nimble, Ollama clef-flash:9b, Liquid D1 local,
Liquid D1 hosted, TypeSafe, OpenRouter Mercury Decide and OpenAI Decisions.
Live `/health` selected `remote:openrouter-mercury-decide` at assessment time.

- Strata's documented Mac model families do not include Nimble, Clef, Liquid D1,
  Gemma or Granite. Hosted inference engines are controlled by their providers.
- The repository's llama.cpp fork implements `/v1/decision`: candidate token
  paths branch from shared context and return scored distributions. The local
  Liquid D1 runtime uses native `/v1/systemone` with its decision encoding.
- Strata documents OpenAI chat/Responses and Anthropic generation APIs, but no
  native `/v1/systemone` or `/v1/decision` contract. An OpenAI-compatible URL
  alone does not make it a compatible System One provider.
- Its JSON mode uses schema prompting followed by validation, not constrained
  decoding or direct finite-choice scoring. A generation adapter would change
  the inference method and could not manufacture equivalent probabilities.

API evidence: [Strata technical details](https://github.com/Niko1221/Strata/blob/main/docs/DETAILS.md),
especially "JSON response formats". Local evidence:
`llama.cpp/tools/parallel-decision/README.md`, `scripts/jev_gateway.py`,
`Sources/JevMenuBar/main.swift`, and `docs/liquid-d1-local.md`.

## Recommended path

### Custom decision build portability

The relevant baseline is `thecodacus/llama.cpp`'s `parallel-decision` branch,
not standard llama.cpp chat generation. Its decision engine directly depends on
`llama_decode`, `llama_get_logits_ith`, and `llama_memory_seq_cp/rm` to score
independent candidate paths from a shared context. Missing HTTP endpoints alone
do not establish that the decision algorithm cannot be ported.

A source inspection of Strata commit
`296b59d2f73c8f04a805df29c2fa97655adace78` found useful building blocks:
`Verifier::copy_logits` in `include/strata/core/verify.hpp`, and Metal window
checkpoint save/restore plus `copy_logits` in `metal/src/engine/window.cpp`.
These suggest a possible prototype that restores a shared prompt state, scores
each candidate path, and assembles decisions using the existing schema logic.
That is an engineering inference, not a working port. Checkpoint completeness,
arbitrary candidate-token evaluation, tokenizer boundary behavior and numerical
parity all require verification. Sequential checkpoint scoring would not retain
the current parallel branch execution; Mac branch batching would need additional
work, and could erase the advertised speed advantage.

The second, independent obstacle remains model support. Strata's
`include/strata/artifact/model_family.hpp` recognizes only Qwen4Exp and Qwen35Moe,
with the Flash-Next engine path restricted to Qwen4Exp. This is not a loader for
the existing decision models. Moving Liquid D1 or Clef would require their model
architecture and native decision encoding support as well as the scoring port.

Therefore a custom Strata decision build is plausible for its supported Qwen
model, but reuse of the current decision models is not established. Benchmark
any port against our custom decision build, using identical weights and schema,
not the ordinary llama.cpp chat baseline.

Keep llama.cpp and existing System One providers as the working baseline.
Do not switch their runtime to Strata: current support does not match their
models or decision protocol.

If a Qwen generation provider is useful, evaluate Strata separately, with a
distinct provider identity and explicit generation semantics. Compare the same
Qwen weights on Strata and llama.cpp first, then compare its decision usefulness
against the existing native decision providers. Reuse the benchmark portal and
existing question sets, including Choice, Score, Noul, ambiguity and parallel
questions. Record cold/warm latency, total wall time, correctness, invalid
responses, queue behavior and memory pressure; tokens/s alone is insufficient.
Only select it as an optional faster provider after it demonstrates a useful
local result. Supporting native decisions would require engine work, not a URL
or configuration change.

No Strata installation or benchmark was performed; no local speed gain is
claimed. The assessment preserves the current runtime and comparison baseline.

## Detailed retrofit investigation

The owner clarified that the intended experiment is native scoring retrofitted
into Strata, retaining cached model references and comparing against our custom
llama.cpp build. A chat-generation adapter would not satisfy that experiment.

### Training and scoring are separate concerns

The local fork is commit `14d04e755fa28653e87b9a07072892265bdc0fad`, branch
`parallel-decision`. Its generic scorer requires an ordinary model's tokenizer,
next-token logits and independent continuation state; it does not load a learned
decision head or require a decision fine-tune. It compiles candidate strings
into token tries, normalizes logits only over allowed tokens at each divergence,
multiplies those constrained probabilities along each path, then assembles typed
results. These are constrained candidate probabilities, not independently
calibrated confidence. Replacing this with full-vocabulary sequence likelihood
or a generated JSON response would change the algorithm.

Strata is specialized for an architecture, rather than requiring weights trained
for a particular classification task. Its supported Qwen checkpoint could use
the generic scorer without retraining. This does not establish the quality of
that model on our decision tasks.

The installed native System One models are a separate path. Live Ollama
`/api/show` plus cached manifests and tensor headers establish:

| Model | Cache and runner | Model-specific requirement |
| --- | --- | --- |
| Nimble | safetensors tensor blobs; `runner: mlx`; Qwen3.5 causal LM config | Decision fine-tune; preserve native prompt/label encoding |
| Clef Flash 9B | safetensors tensor blobs; `runner: mlx`; `ClefForDecision` config | Learned evidence layers, question/option attention and residual scorer |
| Liquid D1 Q8 | GGUF; `lfm2` architecture | Native `lfm2-d1` decision encoding and System One chat template |
| Granite 4.2 | GGUF; `granite` architecture | Generic scorer can use causal LM logits; Strata has no corresponding architecture implementation |

Nimble's fine-tuning is documented in its
[official Ollama model page](https://ollama.com/library/nimble). Clef's joint,
non-autoregressive decision behavior is documented on its
[model page](https://ollama.com/library/clef-flash) and implemented in Ollama's
`mlxrunner/model/clef/head.go` and `score.go`. Cache inspection read metadata and
tensor names only; it did not load model weights for inference.

### Code mapping

| Our code | Portable part | Required Strata integration |
| --- | --- | --- |
| `compile_schema`, `field_spec`, `assemble` | Finite values, numeric aggregation, typed JSON and distributions | Small build dependency changes; retain current contract |
| `decision_field` | Candidate trie, allowed-token normalization, tree/greedy selection | Replace llama token type with backend token IDs without changing math |
| `tokenize`, `render_prompt` | Token-boundary and chat-prefix rules | Strata tokenizer and exact chat rendering; tokenize suffix plus values together |
| `decode_parts`, `prepare_prefix` | Shared instructions and context caching | Strata prefill and explicit cached-prefix state |
| `score_branches` | Independent suffix/node evaluation | Evaluate supplied tokens, read logits, restore trunk before each branch |
| Batched branches and contexts | Isolation and ordered results | New Metal branch-state/batch support to retain actual parallel execution |

Strata's Metal `Window::run` accepts supplied token IDs and positions,
`copy_logits` returns vocabulary logits, and checkpoint save/restore copies
recurrent/conv state, PLE history and attention indexer tails. That is enough to
justify a sequential native-scoring prototype. It is not proof of safe branch
forking: positional KV and pooled keys are not copied by those checkpoint
methods. Rewinding and overwriting must be tested around pooled attention block
boundaries, repeated restores, unequal suffix lengths and reordered branches.
Its recurrent state also makes per-branch copies materially more expensive than
sharing a plain attention KV prefix.

The non-Metal verifier exposes `init_slots`, `run_slots` and per-slot state;
the documented Mac engine has not ported that batching. Speculative generation
is not the first optimization to use here: our candidates are already known and
we need exact logits for prescribed paths, not drafted output. Prefill and kernel
improvements may help, but the generation throughput advantage cannot be assumed.

### Reusing the Ollama cache

GGUF is a container, not a universal architecture interface. Strata's GGUF
reader and engine still check model family. For supported files it can reference
existing paths, but its setup can produce derived packs, an MTP file, expert
copies or a repacked Metal GGUF; therefore "no redownload" and "no derived model
copy" are separate requirements. Unsupported families cannot be enabled merely
by bypassing the guard.

The current Nimble/Clef cache is many per-tensor safetensors blobs, JSON config
and tokenizer blobs referenced by an Ollama manifest, rather than a standard
MLX-LM directory. Their installed manifests explicitly select MLX. Strata does
not provide an MLX/safetensors model loader for this layout. Reading those blobs
would require a loader, matching quantization support and architecture execution.
Clef additionally requires its learned head and hidden-state interface.

[MLX-LM's loader](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/utils.py)
expects configuration plus `model*.safetensors`, resolves a supported model class,
and applies compatible quantization. A reference directory or manifest-aware
adapter could potentially reuse cached weights without copying, but must verify
tensor names, quantization scales, tokenizer and model-specific head support.
Standard MLX-LM loading alone is not demonstrated to execute Clef correctly.
Moving to MLX would also not be a new backend for Nimble or Clef on this Mac;
Ollama already selects it.

### Smallest defensible experiment

1. Preserve the custom llama.cpp build and installed native System One providers.
2. For a Strata-supported Qwen model, port only generic trie scoring using
   supplied tokens, logits and checkpoint restore. Disable generation sampling
   and speculative drafting for the parity test. Keep it outside active routing.
3. Compare with our custom llama.cpp scorer on identical weights, tokenization,
   prompts and schemas. Check full candidate distributions, winner agreement,
   numeric aggregation, branch-order invariance and state isolation first.
4. Measure cold/warm prefill, scoring time, whole-request latency and memory for
   one and many fields. Add Metal batching only after a correct sequential port.
5. If the aim remains existing Nimble/Clef/Liquid weights, treat architecture,
   cache loader and native encoding/head support as a separate feasibility gate.
   The existing MLX native path is the appropriate baseline for Nimble/Clef.

This investigation establishes a plausible generic-scoring port, not a build,
working cache adapter, native-model port or speed gain. No currently cached model
was found that matches Strata's supported Mac family.

Source snapshots inspected: Strata
`296b59d2f73c8f04a805df29c2fa97655adace78`; Ollama
`63b4f61ca926d382b9010e6e15aee93449eab2ac`. Upstream source and docs are newer
than some installed components; runtime facts above came from the live local
API and manifests, not an assumption that upstream main is installed.
