# Benchmark portal implementation

Status: approved for implementation, 4 October 2026. GitHub epic #4;
implementation tasks #5, #6, #7; combined verification #8. Owner instruction:
"write up your tickets / epic etc and make it so". Local dependencies and selected
dataset preparation are part of the implementation; hosted deployment is not.

## Status — 15 October 2026

The catalog, runner, portal, export controls, and service integration are
implemented and packaged in the installed menu-bar app. The portal exposes
checkbox dataset selection, preparation status, model profiles, identical seeded
cohorts, and saved jobs at `http://127.0.0.1:8096/benchmarks`. The local smoke
observations below are limited evidence; epic #4 and tasks #5–#8 remain open,
including combined verification and owner acceptance. This document retains the
original implementation plan as context, not as a claim that every final gate
has passed.

The new [Workbench image test](multimodal.md) is a separate synthetic smoke case.
It does not add a visual benchmark dataset, change the eight native protocols,
or establish image accuracy for these comparisons.

## Goal

Add a **Benchmarks** section beside the existing Workbench and parallel reports.
Run a fixed case set against selected model profiles, retain results, and compare
native metrics for Clef, Clef-Flash, Jev and other configured decision models.

## Reproduction route

Cloudflare identifies its evaluation suite as Decision Index 0.2.1 in the
[Clef model card](https://huggingface.co/Cloudflare/clef).
The independent [Decision Index reproduction kit](https://github.com/apolinario/decision-index)
offers reconstruction recipes, hashes, native scorers and an HTTP engine.
It is not affiliated with TypeSafe. Pin its commit and validate artifacts before
treating a run as a reproduction. Select the eight requested benchmarks;
do not build the entire suite by default. Dataset terms still apply.

Two edition-specific qualifications from the kit matter: RouterBench remains
displayable but is excluded from the aggregate because its prompt reveals the
best route; home-appliance scoring retains 88 cases after duplicate and dev-overlap
exclusions. Preserve these rules when comparing to edition 0.2.1.

## Sources and metrics

The requested names refer to datasets and evaluation tasks, not interchangeable
100-question tests. Use the Decision Index task adapters and scorer revision for
the Cloudflare comparison; the original benchmark can define a different task.

| Benchmark | Original source | Portal metric / qualification |
| --- | --- | --- |
| BFCL | [Berkeley Function Calling Leaderboard](https://github.com/gorilla-llm/gorilla) | Decision Index case-exact accuracy; not a claim of full native BFCL function execution. |
| API-Bank | [Alibaba DAMO-ConvAI API-Bank](https://github.com/AlibabaResearch/DAMO-ConvAI/tree/main/api-bank) | Decision Index accuracy; distinguish tool selection from complete API calls. |
| BANKING77 | [PolyAI task-specific datasets](https://github.com/PolyAI-LDN/task-specific-datasets) | Macro-F1 across banking intents. |
| CLINC150+OOS | [CLINC out-of-scope evaluation](https://github.com/clinc/oos-eval) | Macro-F1 including out-of-scope. |
| Home appliance simulator | [Decision Index simulator generator](https://github.com/apolinario/decision-index/blob/main/decision_index/suite/build/home_appliance.py) | Case-exact accuracy; preserve complete multi-field cases. |
| ANLI | [Facebook Research ANLI](https://github.com/facebookresearch/anli) | Macro-F1 under the kit's frozen split/protocol. |
| RouterBench | [RouterBench](https://github.com/withmartian/routerbench) | Selected quality, not ordinary classification accuracy; flag known prompt leakage. |
| PhishNChips | [AreLit dataset](https://huggingface.co/datasets/AreLit/PhishNChips), [author repository](https://github.com/R-Lit/PhishNChips) | Accuracy of the verdict question; check mixed source terms. |
| Median / p95 latency | Measured by our runner | Milliseconds per request, with protocol, concurrency, warmup and hardware recorded. |

## Compatibility gate

The kit's [intent builders](https://raw.githubusercontent.com/apolinario/decision-index/main/decision_index/suite/build/normalize_direct.py)
use all 77 BANKING77 options and 151 CLINC options. The current
[Ollama System One contract](https://docs.ollama.com/api/systemone)
allows 2–26 options per Choice question. Therefore current Ollama profiles cannot
run these two native protocols unchanged. This also warrants checking API-Bank's
catalog size and every other task's option/question/body requirements.

Reducing labels, splitting candidate lists, one-vs-rest scoring, changing prompts,
or splitting questions belonging to one case creates an **adapted protocol**.
Keep adapted scores in a separate comparison group. Do not label them as native
Cloudflare reproductions. Question batching does not solve an option-count limit.

## Published reference values

These are external reference values, not results from our app. Source:
[Cloudflare Clef-Flash model card](https://huggingface.co/Cloudflare/clef-flash).
Quality values are percentages; latency values are milliseconds.

| Metric | Clef | Clef-Flash | Jev |
| --- | ---: | ---: | ---: |
| BFCL case-exact | 98.5 | 98.8 | 95.8 |
| API-Bank accuracy | 91.9 | 93.1 | 88.2 |
| BANKING77 macro-F1 | 94.2 | 90.9 | 79.7 |
| CLINC150+OOS macro-F1 | 97.4 | 66.8 | 89.3 |
| Home appliance case-exact | 83.0 | 97.7 | 52.3 |
| ANLI macro-F1 | 69.8 | 59.1 | 74.8 |
| RouterBench selected quality | 79.7 | 79.9 | 79.9 |
| PhishNChips accuracy | 79.6 | 75.0 | 62.5 |
| Median latency | 209.3 | 38.8 | 524.1 |
| p95 latency | 238.6 | 122.4 | 536.0 |

Hardware, serving path, precision, model revision and workload affect comparison.
Record local Ollama quantization and model digest; record the resolved hosted Jev
revision when available. A mutable `jev-latest` alias alone is insufficient for
repeatable attribution. Local Mac versus hosted API timing must remain explicit.

## Portal design

Reuse existing portal navigation and report styling. Give Benchmarks three views:

1. **Catalog:** benchmark, metric, source, pinned revision, split, case count,
   installed/access status, and compatibility with the chosen model.
2. **Run:** select model profiles, identical full or seeded sampled case set,
   start/progress/cancel/resume controls, and visible failures or unsupported cases.
3. **Compare:** rows for benchmark/metric, columns for exact model runs; show score,
   answered/total cases, completion status and median/p95. Export JSON and CSV.

Keep **Parallel tests** visibly separate. They measure our custom workflow and
batching behavior; benchmark datasets measure different tasks. Link to both from
the portal and retain their respective scoring definitions.

Only group runs with the same dataset revision, split, cohort hash, task adapter,
scorer and execution protocol. Label samples explicitly. A partial run must never
look like a full score; preserve all errors and apply the selected scorer's
coverage policy. Latency should use a declared successful-request denominator
alongside failure counts, rather than silently dropping slow or rejected cases.

## Implementation path

1. **Catalog and compatibility:** pin the reproduction kit, record source/license
   metadata, expose full versus sample protocols, and inventory actual model
   capacity. Verify pinned dataset terms and access before enabling downloads.
2. **Runner and evidence:** wrap the kit's existing engine/scorers instead of
   recreating their mathematics. Freeze each selected profile for the job; never
   switch a long run when the menu-bar selection changes. Preserve the frozen
   System One state/questions exactly rather than altering them through the
   Workbench's schema guidance. Keep secrets server-side.
3. **Durable run history and page:** use a separate benchmark store under app
   support, plus catalog/run/progress/detail/export routes and portal navigation.
4. **Combined verification:** verify scorer parity, unsupported/partial/resumed
   jobs, identical cohorts, provider isolation, privacy and installed resources;
   then owner UAT on the canonical local portal.

Relevant existing surfaces:

- `Resources/Web/index.html`: Workbench, localStorage parallel reports and explicit
  batching. Do not place large dataset execution inside this browser script.
- `scripts/jev_service.py`: observed service and new page/API extension point.
- `scripts/jev_gateway.py`: profile loading and current decision adapters.
- `scripts/jev_analytics.py`: metadata-only telemetry. Benchmark answers and
  expected labels belong in the dedicated evidence store, not analytics tables.
- `scripts/install_menubar.sh`: package every added runtime module and page asset.

The runner must refuse incompatible cases rather than truncate evidence or change
options. Capacity refusals remain visible. Run small identical cohorts first to
validate transport and scoring, then the compatible full benchmark cases. Do not
produce a combined Decision Index score from only these eight selected tasks.

## Accepted implementation requirements

R1: Catalog all eight requested benchmarks with pinned source/protocol metadata and native metrics.
R2: Prepare selected datasets and use pinned native scorers without changing options, evidence or case groups.
R3: Freeze model profiles per job and retain durable progress, cancellation/resume, case outcomes and errors without storing credentials.
R4: Compare identical cohorts and report native scores, coverage, median/p95 latency, and JSON/CSV exports.
R5: Provide a separate Benchmarks portal section alongside the existing parallel tests and analytics.
R6: Package the local app resources and verify the complete epic before owner Dev UAT.


## Implementation map

- `scripts/setup_benchmarks.py`: prepare the eight selected datasets, pinned kit,
  isolated Python 3.10+ environment, source pins and license evidence.
- `scripts/jev_benchmark_data.py`: dataset integrity, deterministic complete-group
  sampling and pinned native scorers. Gateway runtime remains Python 3.9 compatible.
- `scripts/jev_benchmarks.py`: private durable jobs, frozen profiles/local model
  digests, capacity checks, cancellation/resume, metrics and exports.
- `scripts/jev_service.py`: protected `/api/benchmarks` routes and `/benchmarks`.
- `Resources/Web/benchmarks.html`: dataset/model selection, run history and results.
- `scripts/install_menubar.sh`: packages these modules and assets into the app.

Data, kit, isolated environment and run evidence reside under
`~/Library/Application Support/JEV Menu Bar/benchmarks`. Configured profiles come
from the sole `typesafe.json` config. Jobs never change the selected menu backend.
Cancellation waits for the current HTTP request; resume retains already recorded
outcomes. Failed or unsupported cases remain visible and have no complete score.
Hosted model aliases do not expose a resolved revision; local Ollama digests do.

Scores in the UI are percentages; JSON/CSV preserve native fractions. Samples
select complete groups, so one group can contain multiple requests. Samples are
exploratory and must not be presented as full published benchmark reproduction.
The eight-task subset does not produce an overall Decision Index score.

## Local delivery evidence — 4 October 2026

All eight datasets were prepared. Release build and application installation
succeeded; the local Benchmarks catalog and profiles routes returned successfully.
A one-group ANLI run completed with native scoring for Clef-Flash, Clef and Jev.
BANKING77 against Clef-Flash was retained as unsupported with a null score.
JSON and CSV exports succeeded. A cancelled job resumed and completed two ANLI
groups; PhishNChips completed through the native verdict scorer. Final installed
module/page bytes match source and app signature verification passed. These are
integration smoke observations, not
full benchmark results or owner acceptance. Full model/dataset runs remain an
operator choice in the portal; GitHub verification #8 tracks the final evidence.
