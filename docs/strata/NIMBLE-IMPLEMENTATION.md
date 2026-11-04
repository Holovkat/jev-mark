# Local Nimble decision experiment

Owner-authorized scope: Nimble native scoring on the custom llama.cpp build and
the local Strata fork, then single and parallel decisions using identical inputs.
No pushes, installed-service changes or model substitutions.

Owned surfaces: the opt-in `metal/src/nimble/decision.cpp` engine,
`metal/kernels/nimble.metal`, an optional SiLU specialization of Strata GDN,
`tools/nimble_cache.py`, opt-in Nimble scoring under `serve/`,
comparison tools and evidence under `.worktree-runtime/`, and this document.
The separate llama checkout preserves the existing custom decision-engine edits.

The installed Nimble is a dense Qwen3.5 9B decision fine-tune in MXFP8 safetensors,
already served by Ollama's MLX runner. The current fork adds an actual C++/Metal
dense Qwen3.5 port: ordinary residual layers, RMSNorm, partial RoPE, causal grouped
query attention, Strata's matrix-unit projections and GDN recurrence with SiLU
gating. Python prepares native packets and token IDs; no MLX, llama or Ollama
inference runs inside this new engine. The earlier MLX experiment is retained
and labeled separately. No training or substitute model is involved.

Acceptance:
- Read existing cached weights without changing the model store.
- Preserve native Nimble schema encoding, one-letter candidate codes, model
  system guidance, no-thinking chat framing and candidate-logit scoring.
- Return Choice distributions, fractional Score and Noul probability; generate
  zero output tokens. Reject invalid inputs without truncation or fallback.
- First compare one field, then several independent questions. Verify complete
  distributions, stable ordering and state isolation before reporting speed.
- Distinguish multiple fields batched inside the engine from concurrent clients.
- Preserve custom llama.cpp, installed JEV routing and installed providers.

Conversion: llama.cpp needs GGUF; its baseline will use an explicit BF16 expansion
of the installed MXFP8 weights. Record that provenance and any numerical changes.
The C++/Metal port and llama both use the exact same BF16 GGUF; the historical
MLX path uses cached MXFP8 directly. Different numerical kernels are expected; material
disagreement blocks a speed-only conclusion.

Order: cache adapter and GGUF -> native single-field scoring on each engine ->
parallel scoring -> one combined verification/comparison pass. Narrow diagnostics
and builds occur while implementing. The combined pass owns protocol, parity,
branch isolation, latency and regression checks. No Dev/QA deployment is included.

Local ports: Strata 51240-51259; llama 51380-51399. Both loopback only.

Current native C++/Metal comparison: [NIMBLE-METAL-RESULTS.md](NIMBLE-METAL-RESULTS.md).
Historical MLX comparison: [NIMBLE-RESULTS.md](NIMBLE-RESULTS.md).
