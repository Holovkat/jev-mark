# JEV documentation

Status reconciled against source, installed service and repository history on
15 October 2026. The [main README](../README.md) introduces the app and summarizes
changes from 8–15 October.

## Running the app and testing decisions

| Guide | Use it for |
| --- | --- |
| [Shared image decisions](multimodal.md) | PNG/JPEG assets, route support, Visual tests library case, CLI smoke, limits, and installed-app evidence. |
| [OpenAI integration](openai-decision-integration.md) | Project-key native Decisions setup, credited organization, and verification evidence. |
| [Liquid D1 local runtime](liquid-d1-local.md) | Separate native runtime, cached weights, LaunchAgent, profile and text-decision smoke evidence. |
| [Benchmark portal](benchmark-portal.md) | Eight datasets, native protocols/scorers, pinned setup, frozen profiles, durable jobs, comparisons, exports, and open verification gates. |
| [Service analytics](service-analytics.md) | Request metadata, local body capture/expiry, privacy/access controls, storage, API and implementation map. |

The installed gateway is `http://127.0.0.1:8096`; its main pages are `/workbench`,
`/benchmarks`, and `/analytics`. Any temporary development port shown in an older
smoke record is not the installed menu-bar service. Model selection is current
operator state, not a permanent property of a test report.

## Local engine decisions and evidence

- [Custom llama.cpp runtime update](llama-runtime-update.md): retained probability
  and prompt fixes, upstream hybrid batching patch, installed binary provenance,
  regression parity and rollback. Its engine patch remains a separate checkout
  change; publishing JEV documentation does not publish that engine source.
- [Strata assessment and current decision](strata-assessment.md): custom llama.cpp
  remains the baseline; the native Strata experiment is stopped.
- [Native C++/Metal comparison](strata/NIMBLE-METAL-RESULTS.md),
  [earlier MLX comparison](strata/NIMBLE-RESULTS.md), and
  [implementation notes](strata/NIMBLE-IMPLEMENTATION.md) preserve distinct
  experiments. Their results must not be combined into a new performance claim.
- [State-machine design](state-machine-design.md): implemented grid behavior,
  measured guided runs, and explicitly proposed future policy modes.

## Agent integrations

- [Capability selection](capability-selection.md)
- [Compaction retention](compaction-retention.md)
- [Requirements readiness](requirements-readiness.md)
- [ZCode integration](zcode-integration.md)

## Evidence boundaries

A synthetic image smoke proves one request, not general visual accuracy.
Responses estimates are distinct from native decision probabilities. Published
Cloudflare reference values are distinct from local benchmark results. Model
aliases, source commits, runtime hashes and protocol identifiers matter when
comparing runs. The open benchmark epic and owner acceptance gates are not
closed by source publication or local app installation.
