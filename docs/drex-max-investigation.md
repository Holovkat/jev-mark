# Drex Max v1 local benchmark feasibility

Investigated 31 October 2026. Scope: identify the linked model, check local feasibility, and identify installation and benchmark integration work. Research and documentation only; weights, runtime installation and inference remain pending.

## Recommendation

Use the official Q8 GGUF with Nace's `drex-max-v1` llama.cpp branch, then register a text-only System One profile in JEV. Reuse the [Liquid D1 runtime pattern](liquid-d1-local.md) and [benchmark portal](benchmark-portal.md). This is feasible enough for a local smoke test on this Mac; M1 performance and compatibility are not yet proven.

The [supplied post](https://x.com/NaceAI/status/2116163656480428220), published 30 October 2026 at 13:41:46 UTC, links to [nace-ai/drex-max-v1](https://huggingface.co/nace-ai/drex-max-v1). X returned 403; its matching text and model link were retrieved through the public FxTwitter mirror. Drex Max is a dense 27B decision model. Its decision head and non-causal attention require a compatible loader. A normal chat invocation is not an equivalent evaluation.

## Installation choices

| Route | Required work | Assessment |
| --- | --- | --- |
| Nace llama.cpp + Q8 GGUF | Download one 27.25 GB model file; build Nace's branch; serve `/v1/systemone` | Recommended: direct fit with the existing local provider pattern |
| Nace Ollama fork + Q8 GGUF | Build its Ollama fork and native runner; import with a decision Modelfile | Supported upstream, but more moving parts than a direct runtime |
| Kapitsa + affine Q4 | Install Kapitsa 0.2.25 or newer; download a model directory of about 14.47 GB | Smaller alternative; publisher specifies at least 24 GB memory |
| MLX + affine Q4 | Python environment, publisher dependencies and decision script | Local option; documented example is a command-line runner, so inspect HTTP serving before JEV integration |
| Python + original weights | About 49 GB weights; NVIDIA/CUDA environment | Published route for images; not the documented local Mac path |

Sources: [model setup](https://github.com/nace-ai/drex-decision-models/blob/main/models/drex-max-v1/README.md), [Q8 package](https://huggingface.co/nace-ai/drex-max-v1-Q8_0), [affine Q4 package](https://huggingface.co/nace-ai/drex-max-v1-affine-q4). Q4 here is an affine model directory, not a llama.cpp Q4_K_M GGUF. The published Mac packages run text only. The Q8 package includes its decision-head tensors and specifies 48 GB memory. Published Mac validation uses an M5 Pro; the social post mentions M4/M5.

Downloading into a folder only stores the weights. Stock Ollama support for this decision encoding has not been established; the publisher explicitly documents its forks. Store the file in the existing model area, outside Ollama's managed `blobs`/`manifests`, and point the compatible server to it. Do not rename a file into the blob store or assume ordinary Ollama discovery makes it runnable.

## Live local inventory

- Host: Apple M1 Ultra, 64 GiB unified memory.
- Ollama: 0.40.13. Its current model list contains no Drex model.
- Homebrew llama-server: build 9090, commit `5757c4dcb`; Metal recognizes the M1 Ultra. This does not prove Drex support.
- Model drive: `/Volumes/Extreme SSD/3 Resources/LLLM/`, with approximately 303 GiB free. Its existing `Models/` directory is a suitable parent for a named Drex directory.
- JEV gateway: `http://127.0.0.1:8096/health` returned `ok`; `/providers` has no Drex profile. Existing provider selection was preserved.
- Existing dedicated runtime: `~/Library/Application Support/JEV Menu Bar/runtimes/liquid-d1/llama-b11606/llama-server`.
- Benchmark owner: this repository, branch `codex/proxy-batching`, with substantial pre-existing edits. Designs is the conversation's starting directory, not the model service owner.

Memory and storage meet the publisher's stated minimums. Available memory under load, runtime behavior on M1, context headroom and latency remain measurements, not guarantees. Start with short text and one request at a time.

## Installation handoff

1. Download `drex-max-v1-Q8_0.gguf` from `nace-ai/drex-max-v1-Q8_0` into the existing model area; verify its SHA-256. The prebuilt GGUF avoids downloading and converting the original weights.
2. Build `llama-server` from Nace's pinned `drex-max-v1` branch in the existing per-model runtime area. Use the publisher's [build instructions](https://huggingface.co/nace-ai/drex-max-v1#llamacpp); preserve the current engines.
3. Start it on an available loopback port. For the publisher's 16,384-token configuration, context, batch and microbatch sizes are all 16,384, with one slot and warmup disabled. Reduce all three together for a smaller initial memory test. Confirm the actual effective limit and Metal offload in its logs. [Context contract](https://github.com/nace-ai/drex-decision-models/blob/main/docs/context-length.md).
4. Run the publisher's example directly. Verify Choice, Score and Noul, finite normalized distributions, exact labels, and explicit unsupported-image behavior. Record load time and memory separately from warm inference.
5. Register a local System One profile using the established Liquid D1 configuration pattern. Keep image input disabled. The existing profile loader requires a nonempty API-key string even for local services; follow the existing local placeholder convention rather than adding a hosted credential.
6. Verify the same request through JEV, then run the existing frozen benchmark cohorts. Add persistent startup only after the runtime smoke succeeds.

Observed upstream pins, to recheck when installing:

| Artifact | Revision or digest |
| --- | --- |
| Q8 model repository | `0f9d1a142e2d38a2fc64d1cc7394745df3cd9528` |
| Q8 file size | `27250125216` bytes |
| Q8 file SHA-256 | `083fe3253f15592554c4ccf2de61575bfa46d19ca4515516c87be1a4fb40db7b` |
| Nace llama.cpp branch HEAD | `8f6f9ccd8a481c0c46ddef7b5108bd3eae4493a4` |
| Affine Q4 repository, alternative | `e7d0c597706239a015608c06dfe0951197e95096` |

Pins came from the Hugging Face model metadata and GitHub branch API. No weight checksum was computed locally because no weights were downloaded.

## Benchmark fit and remaining work

The [Drex request contract](https://github.com/nace-ai/drex-decision-models/blob/main/docs/request-format.md) accepts `state` and named `questions` and returns `answers`. It supports Choice, Score and Noul, including up to 255 Choice options. That is structurally compatible with JEV's existing runner; successful inference still needs verification. Its documentation counts serialized answer tokens in `usage.output_tokens`, so that field must not be interpreted as generated text or used to claim generation speed.

Source inspection found two relevant details in [jev_benchmarks.py](../scripts/jev_benchmarks.py):

- `_capacity` applies a 26-option restriction to loopback port 11434. A direct Nace endpoint avoids conflating this existing Ollama rule with Drex's documented 255-option head. Verify all 77 BANKING77 and 151 CLINC options intact before claiming those native protocols work.
- `_model_revision` resolves digests only for Ollama on 11434. Record the Drex model hash, runtime commit/binary hash, context and GPU settings in the run evidence; a profile name alone does not freeze its implementation.

Reuse identical dataset/scorer versions, seeds, cohorts and prompts. Compare task accuracy or macro-F1, failure counts, warm median/p95 latency, cold load time and memory. Run engines sequentially for resource fairness. Keep Q8 and Q4 results separate. Published scores are reference claims, not local benchmark results; the advertised maximum context is not a promise that it fits this Mac.

## License

The weights use a [modified Nace Open RAIL-M license](https://huggingface.co/nace-ai/drex-max-v1/blob/main/LICENSE). It includes revenue/funding thresholds above US$1 million with personal/research exceptions, plus a separate competing-product restriction and use restrictions. Assess the intended use against those terms; unrestricted commercial use should not be assumed from the announcement.

## Retrospective applied

The useful navigation improvement is to keep this model assessment with JEV's runtime and benchmark documentation and link it from the existing index. Existing CI already runs Python and JavaScript checks; this documentation-only investigation warrants link and diff validation, not a new harness. Future model assessments should distinguish stored weights, supported decision encoding, API compatibility and measured inference before treating a model as installed.

Completed: post identification, publisher/runtime/license inspection, live hardware/storage/service inventory, source-level benchmark mapping, and this handoff. Pending: download, build, direct and gateway smoke tests, profile registration, and benchmark results. No runtime, model, provider configuration or hosted service was changed.
