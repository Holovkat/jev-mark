> Historical MLX comparison. For the requested native Strata C++/Metal port, see
> [NIMBLE-METAL-RESULTS.md](NIMBLE-METAL-RESULTS.md).

# Nimble native decision experiment

14 October 2026. Local only; no commits, pushes or installed-provider changes.

The same cached Nimble checkpoint now runs native decision scoring in the local
Strata fork and the isolated custom llama.cpp fork. Both return Choice, Score and
Noul results with zero generated output tokens. The Strata implementation is a
new opt-in **MLX backend**. It does not execute Strata's existing Flash-Next/MoE
C++ kernels, and these results do not demonstrate their speed benefit on Nimble.

## Result

Warm HTTP wall-clock medians on this M1 Ultra with 64 GiB unified memory:

| Questions | Execution | Custom llama.cpp | Strata Nimble MLX |
| --- | --- | ---: | ---: |
| 1 | Single | 92 ms | 70 ms |
| 4 | Sequential | 370 ms | 433 ms |
| 4 | Parallel | 191 ms | 246 ms |
| 8 | Sequential | 761 ms | 899 ms |
| 8 | Parallel | 333 ms | 454 ms |

Three measured repetitions per cell, after warming the prefix and execution
shape. Only one experimental engine was resident at a time. Startup/model loading
is excluded. These are provisional local timings, not a broad performance claim.
The fresh-prefix measurements are retained separately in the raw reports.

The MLX backend saved about 22 ms for one question. The custom llama.cpp build
was faster for four/eight questions, including parallel execution. Keep the
existing setup as the baseline; this is not an across-the-board speed boost.

## Behavior checks

- Replayed the existing 100-question JEV logic dataset on both engines in both
  sequential and parallel modes, in packets of up to 16 questions. Both scored
  **92/100 acceptable**, using the dataset's expected answers plus its declared
  reasonable judgment answers. All 100 selected answers agreed across engines
  and across execution modes.
- The largest cross-engine candidate-probability difference in that replay was
  **3.22 percentage points**. The probability distributions are not identical;
  confidence-threshold behavior needs its own acceptance before switching paths.
- Native Choice, fractional Score and Noul checks passed, as did fresh/warm
  consistency, reordered branch execution, unequal suffix lengths, changing and
  restoring evidence, and valid requests after four rejected invalid requests.
- Eight checked native prompts had exactly matching token IDs between the cached
  tokenizer and the GGUF tokenizer. Native framing follows installed Ollama
  **0.40.3**, including null descriptions, No/Yes defaults and the empty thinking
  block; no reasoning text is generated.
- Four new protocol regression tests passed. All **314** existing Strata server
  regression tests passed. The isolated llama worker/server builds and Python
  compilation checks passed. Foreign browser origins/hosts are rejected by the
  native endpoint; generation routes return 404 in Nimble mode.

## Model and implementation provenance

Nimble manifest SHA256:
`dfed4f707396966698374b7ffe21bd4586271b772551a02f0114e5c79fd24a21`.

The MLX backend reads the existing 427 safetensors tensor files directly from
Ollama's cache, using its MXFP8 weights. There is no inference call to Ollama.
It prefills a shared native prompt, restores independent recurrent/attention
state, batches continuation rows, and projects the final hidden state onto the
allowed one-letter answer-code weights in FP32. JSON assembly happens in code.

The custom llama.cpp worker reads a derived BF16 GGUF expanded from that same
MXFP8 cache. Small normalization tensors use the converter's F32 representation.
The original cache and installed services were not modified. The local converter
does not support this packed MXFP8 layout directly, so an HF export is an
intermediate representation; conversion uses `--outtype bf16 --no-mtp`.

An initial export incorrectly treated normalization weights as already shifted.
Those smoke results are marked `invalid-export-*` and excluded. The export code
was corrected to preserve the source HF layout. All 81 GGUF normalization tensors
were checked against the cache plus the existing converter's transformation
before the valid llama checks/replays. No retraining was performed.

Source bases:

- Strata: `296b59d2f73c8f04a805df29c2fa97655adace78`.
- Custom llama.cpp: `14d04e755fa28653e87b9a07072892265bdc0fad`, with the existing
  uncommitted hybrid-branch padding changes copied into the isolated checkout.
- MLX: `0.32.3`; MLX-LM: `ba8a08fd2ed72bbc53de84f89933f91fe4743e4a`.
- Native schema/renderer reference: Ollama `v0.40.3`.

Both checkouts are on `codex/nimble-native-decisions`, with push URLs disabled.
Additional llama changes preserve trailing suffix whitespace and allow the full
native evidence packet to live in the shared prefix without adding context text.
The standard Strata engine paths and default engine selection are unchanged.

## Run locally

From `/Volumes/Seagate/workspace/jev-strata-nimble`, start one engine at a time.
These commands use the prepared local virtual environment and isolated ports.

```sh
.venv-nimble/bin/python -m serve.server --engine nimble \
  --nimble-backend mlx --port 51240 --nimble-batch-size 8
```

```sh
.venv-nimble/bin/python -m serve.server --engine nimble \
  --nimble-backend llama --port 51380 --nimble-batch-size 8 \
  --nimble-gguf .worktree-runtime/models/nimble-cache-bf16.gguf \
  --nimble-llama-binary /Volumes/Seagate/workspace/jev-llama-nimble/build-nimble/bin/llama-parallel-decision
```

Use `POST /v1/systemone` with the existing native Nimble request shape. Optional
experiment controls are `execution_mode: "single" | "parallel"`, `fresh: true`
(clear the prefix once per packet), and `execution_order` (a permutation of
question names, for isolation checks). Parallel mode batches up to eight fields
per matrix operation; separate client requests are serialized. Ctrl-C stops the
experimental service. It is not registered in JEV Menu Bar and does not change
the selected JEV provider.

Recreate derived files, when needed, from the same cache:

```sh
.venv-nimble/bin/python tools/nimble_cache.py \
  --export-hf .worktree-runtime/models/nimble-hf \
  --export-gguf .worktree-runtime/models/nimble-cache-bf16.gguf \
  --llama-checkout /Volumes/Seagate/workspace/jev-llama-nimble
```

The llama backend rejects a GGUF whose provenance does not match the current
Nimble cache. Dependencies are pinned in `.worktree-runtime/dependencies.txt`.

## Evidence

Files under `.worktree-runtime/`:

- `comparison.json`: timing table, cohort fingerprints and cross-engine summary.
- `mlx-benchmark.json`, `llama-benchmark.json`: individual fresh/warm runs.
- `mlx-logic-100.json`, `llama-logic-100.json`: every native answer/distribution.
- `mlx-verification.json`, `llama-verification.json`: primitive/isolation checks.
- `tokenizer-parity.json`, `gguf-normalization-verification.json`: conversion checks.
- `strata-server-regression.log`, `dependencies.txt`: checks and package provenance.

Next performance work, if desired, should target dense Nimble kernels and batch
overhead. The original Strata MoE/expert-cache speed techniques have not been
ported to Nimble's architecture in this experiment.
