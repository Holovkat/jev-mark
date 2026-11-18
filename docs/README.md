# JEV documentation

Status reconciled against source, installed service and repository history on
16 October 2026. The [main README](../README.md) introduces the app and summarizes
changes from 8–15 October.

## Running the app and testing decisions

| Guide | Use it for |
| --- | --- |
| [Capability report](capability-report.md) | Selected-model judgement versus documented and advertised expectations, with evidence and export. |
| [Shared image decisions](multimodal.md) | PNG/JPEG assets, TypeSafe/Ollama routes, native image toggle, Visual tests, CLI smoke, limits, and installed-app evidence. |
| [OpenAI integration](openai-decision-integration.md) | Project-key native Decisions setup, credited organization, and verification evidence. |
| [Liquid D1 local runtime](liquid-d1-local.md) | Separate native runtime, cached weights, LaunchAgent, profile and text-decision smoke evidence. |
| [Benchmark portal](benchmark-portal.md) | Eight datasets, native protocols/scorers, pinned setup, frozen profiles, durable jobs, comparisons, exports, and open verification gates. |
| [Service analytics](service-analytics.md) | Request metadata, local body capture/expiry, privacy/access controls, storage, API and implementation map. |

## Change tickets

| Ticket | Use it for |
| --- | --- |
| [Menu bar overlays and usage pulse](tickets/2026-11-04-menubar-decision-overlays.md) | 4 November 2026 popover rework: usage pulse, overlay selectors, services toggle, Ollama selection pruning, with retro and verification. |
| [Decision cache, savings and rate card](tickets/2026-11-18-decision-cache-savings-and-rate-card.md) | 17–18 November 2026: replay cache with avoided-cost metrics, automatic vacuum and payload dedup, editable model rate card, and the menu savings line, with backfill tools and verification. |

The installed gateway is `http://127.0.0.1:8096`; its main pages are `/workbench`,
`/benchmarks`, and `/analytics`. Any temporary development port shown in an older
smoke record is not the installed menu-bar service. Model selection is current
operator state, not a permanent property of a test report.

## Local engine decisions and evidence

- [Drex Max v1 investigation](drex-max-investigation.md): local installation choices, Nace runtime requirement, storage and memory fit, and existing benchmark integration work.
- [EmbeddingGemma 2 investigation](embeddinggemma2-investigation.md): source-backed local System One feasibility, runtime gaps, online learning design and epic #10.

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
- [Skills library UI and API proposal](skill-library-design.md) — design draft and interactive preview for central sources, task recommendations and preferences.
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
