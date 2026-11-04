# Native Nimble on Strata C++/Metal

> Benchmark snapshot from 14 October 2026. Services are stopped and llama.cpp
> remains the local baseline. The owner subsequently authorized publication to
> [Holovkat/Strata](https://github.com/Holovkat/Strata/tree/codex/nimble-native-decisions)
> and [Holovkat/llama.cpp](https://github.com/Holovkat/llama.cpp/tree/codex/nimble-native-decisions).
> No-push statements below describe the original experiment.

The local fork implements a dense Qwen3.5 port for the installed Nimble decision
checkpoint. This is actual C++/Metal inference using Strata's runtime and kernels.
The earlier MLX experiment is separate: [NIMBLE-RESULTS.md](NIMBLE-RESULTS.md).

No installed service, JEV routing or Ollama model file was changed. Nothing was
pushed. Both local forks use `codex/nimble-native-decisions` and disabled push URLs.

## Native implementation

`metal/src/nimble/decision.cpp` loads the derived Nimble BF16 GGUF through Strata's
read-only GGUF loader and wraps its weights as Metal buffers. It executes all 32
layers: RMS normalization and residuals, dense SwiGLU, gated delta recurrence,
partial RoPE and causal grouped query attention. Projections use Strata's
`gemv_mma_30_2` FP32 matrix-unit kernel. GDN reuses `gdn_step` with an opt-in SiLU
gate; the original sigmoid specialization remains the default. The existing GDN
parity program passes with that default.

Native decisions evaluate only the allowed one-letter answer-code logits and
normalize those candidates. No generated text, reasoning token loop or auxiliary
trained head is involved. The model remains the cached Nimble fine-tune, not a
replacement Qwen checkpoint. Python prepares the existing native schema and token
IDs; it performs no model inference in the Metal backend. The binary links Metal,
Foundation and the system C++ runtime, with no MLX or llama compute dependency.

Single mode restores the shared-prefix state and evaluates each field separately.
Parallel mode shares matrix weight reads across up to eight independent branches;
each branch has its own recurrent, convolution and attention state. Unequal
suffixes are padded only after capturing each field's real final-token logits.
States and scratch buffers are preallocated. Fresh requests rebuild the prefix;
warm requests reuse it. Requests from multiple HTTP clients are serialized.

This prototype supports this Nimble layout, BF16/F32 tensors, an 8192-token
context, 2–26 candidates per field and up to 64 fields per packet. It does not
claim general support for arbitrary GGUF quantizations, model architectures or
all of Strata's Flash-Next features.

## Reproduce

From `/Volumes/Seagate/workspace/jev-strata-nimble`:

```sh
cmake -S metal -B build-nimble-metal -DCMAKE_BUILD_TYPE=Release
cmake --build build-nimble-metal --target strata-nimble-decision -j 8
.venv-nimble/bin/python serve/server.py --engine nimble \
  --nimble-backend metal --port 51240 \
  --nimble-gguf .worktree-runtime/models/nimble-cache-bf16.gguf
```

The worker target needs no metal-cpp checkout or full Flash-Next engine build.
It uses the same Strata `mtl_rt` and native kernel library infrastructure. The
HTTP endpoint is `POST /v1/systemone`; generation endpoints are unavailable.

Run the custom llama baseline in a separate process, after stopping Metal when
measuring latency:

```sh
.venv-nimble/bin/python serve/server.py --engine nimble \
  --nimble-backend llama --port 51380 \
  --nimble-gguf .worktree-runtime/models/nimble-cache-bf16.gguf \
  --nimble-llama-binary /Volumes/Seagate/workspace/jev-llama-nimble/build-nimble/bin/llama-parallel-decision
```

Benchmark/verification tools: `tools/benchmark_nimble.py`,
`tools/verify_nimble.py`, `tools/verify_nimble_suite.py` and
`tools/compare_nimble_native.py`. Raw results live under `.worktree-runtime/`.

## Provenance and measurement

Hardware: Apple M1 Ultra, 64 GiB unified memory, macOS 27.0.1. These are same-day
local prototype measurements, not a claim about other hardware or upstream
Strata's published workloads. Only one experimental model engine is resident
while final benchmarks run. Three repetitions per warm cell follow a shape
warm-up; single/parallel order alternates. Model loading and pipeline compilation
happen before worker readiness. Fresh-prefix latencies are recorded separately.

Both engines read the **same BF16 GGUF** expanded from the installed MXFP8 cache.
Shared and suffix strings are independently tokenized on both paths, matching
the custom llama scorer. The comparison checks cohort fingerprints, source
fingerprints, shared boundaries, token counts, checkpoint identity and zero
output tokens before comparing results.

Nimble manifest SHA256:
`dfed4f707396966698374b7ffe21bd4586271b772551a02f0114e5c79fd24a21`.
GGUF provenance: `.worktree-runtime/models/nimble-cache-bf16.provenance.json`.
The original cached checkpoint is unchanged; there is no retraining.

Source bases: Strata `296b59d2f73c8f04a805df29c2fa97655adace78`;
custom llama.cpp `14d04e755fa28653e87b9a07072892265bdc0fad`, including the
existing decision-specific modifications copied to its isolated local fork.

## Results

Warm median request latency:

| Decisions | Mode | Custom llama.cpp | Strata C++/Metal | Strata / llama |
|---:|---|---:|---:|---:|
| 1 | Single | 91.67 ms | 206.79 ms | 2.26× |
| 4 | Sequential | 367.24 ms | 916.08 ms | 2.49× |
| 4 | Parallel | 191.33 ms | 1624.41 ms | 8.49× |
| 8 | Sequential | 756.76 ms | 1954.13 ms | 2.58× |
| 8 | Parallel | 341.90 ms | 2338.68 ms | 6.84× |

The custom llama.cpp is faster in every measured cell. Parallel Strata execution
also takes longer than sequential Strata execution for these short field suffixes.
Keep the installed setup and custom llama baseline in place. The native port is
usable for experiments, but this implementation is **not a Nimble speed boost**.
These numbers do not evaluate upstream Strata's Flash-Next workload.

Both engines returned the same selected answer on **100/100** existing JEV logic
questions, in both execution modes. Both scored **92/100 acceptable** under the
existing dataset's declared expected/reasonable answers. Native Metal's single
and parallel probability distributions matched exactly throughout the replay.
The largest cross-engine probability difference was
**1.65 percentage points**. Identical winners do
not imply identical confidence thresholds.

Native Choice, fractional Score and Noul checks passed. Fresh/warm equivalence,
branch-order independence, unequal suffix padding, changed/restored evidence,
state isolation and recovery after four rejected invalid requests all passed.
All **314** existing Strata server tests and four native protocol tests passed.
The native worker build, Python compilation, original GDN parity and diff checks
passed. The standard Flash-Next full-model path was not tested with its weights;
its default GDN specialization passed the existing kernel reference checks.

Final evidence:
- `.worktree-runtime/native-metal-comparison.json`
- `.worktree-runtime/metal-benchmark.json`
- `.worktree-runtime/llama-metal-baseline-benchmark.json`
- `.worktree-runtime/metal-logic-100.json`
- `.worktree-runtime/llama-metal-baseline-logic-100.json`
- `.worktree-runtime/metal-verification.json`
- `.worktree-runtime/metal-default-gdn-parity.log`
- `.worktree-runtime/metal-server-regression.log`

The earlier `metal-before-state-pool-benchmark.json` is development evidence and
is excluded from the table. The final binary preallocates states and compiles
pipelines before readiness. Both experimental services were stopped after their
runs. Installed JEV remained on `remote:openrouter-mercury-decide` at port 8096;
Ollama remained version 0.40.3 at port 11434. No commits or pushes were made.

Further speed work would target larger prefill matrix batches and fewer
per-branch attention/GDN dispatches. Those changes have not been measured and
are not evidence of a future speed advantage.
