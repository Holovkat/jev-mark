# Capability report

Open `/capability-report`, select the judge through the menu-bar model selector,
refresh the catalog, choose target models and run. Each question simply asks:
**Does this model allow this capability or question type?** The answers are
**Yes, No, or Unknown**, using finite Choice questions. Expected labels are
withheld from the judge. There are no special Box judgement rules or forced
answers based on the model's probability.

The catalog covers configured remote profiles. Expectations use adapter contracts,
Ollama advertised metadata and the official TypeSafe image and Box documentation.
These are evidence-based expectations, not inference probes or routing gates.
Missing evidence stays unknown. TypeSafe's documented image aliases are
`jev-latest`, `jev-1.14.0` and `jev-preview`; Box is documented for the latter two.
Image input does not by itself establish support for the Box question type.

The matrix has one row per model and small vertical capability headings:

- Checked blue: Yes; empty blue: No; a dash: Unknown.
- Yellow: a Yes/No contradiction with the expected capability.
- Unknown is a valid answer, not a failure. Unknown matching Unknown counts as
  agreement; comparisons involving one unknown remain unconfirmed.
- An exclamation mark means a missing answer or failed request, not Unknown.

Hover a square for the expectation evidence and the judge's confidence. This
report shows the judge's interpretation; it does not execute Box or vision calls
against every model. Separate native probes on 16 October accepted Box on
`jev-1.14.0` and rejected it on Ollama D1 and `jev-latest` at that time. These are
bounded observations, not permanent model restrictions.

## Batching

Questions from multiple models share the catalog context within each batch.
Configure Questions per batch (1–512 preferred) and Parallel batches (1–4). The default is the
profile batch size or 32 questions, with two parallel batches. Published question
limits and a conservative request byte budget bound each batch. Questions are
partitioned explicitly; evidence is never trimmed.

Each run freezes the judge and input. Selection is checked before and after every
batch. Stop waits for active batches and prevents queued batches from starting.
Partial responses retain completed answers and expose missing fields individually.
There are no automatic retries. Batch grouping can change model judgements, so
JSON exports retain the exact requests, responses, mapping and concurrency settings.
Actual usage remains at batch level; totals are not duplicated across model rows.

## Access and verification

`GET /api/capability-catalog` uses the analytics access policy: localhost, or the
configured analytics token for remote access. No credentials or private endpoint
URLs are returned. Calls use the existing decision service and appear in analytics
with client `capability-report`. The page does not retain runs after reload;
export JSON before leaving if needed. Normal analytics payload retention applies.

Focused checks cover request construction, answer comparison, unique batch IDs,
question/byte limits, partial result mapping, credential exclusion and access policy.
Diagnostic evidence is retained under `output/capability-report/`, including the
original D1 seven-disagreement report, native Box checks and image colour reversal
checks. Older diagnostic prompts and run counts are historical, not the current
Yes/No/Unknown protocol.

Installed verification: D1 completed 96 questions as three 32-question batches,
with two requests overlapping in time. All fields returned Yes, No or Unknown;
there were no failed answers. The exported run is
`output/capability-report/d1-simple-parallel-report.json`.

## Provider limits and timing

The menu-bar batch preference can be entered directly up to 512 and survives
profile reloads. The report distinguishes this requested size from the effective
provider size. Ollama 0.40.5 rejects 65 questions even in a 4 KB request;
its `decision.ValidateLimits` hardcodes 1–64. The web app retains the requested
preference but limits each Ollama request to 64. No environment variable changes
that validation. `OLLAMA_NUM_PARALLEL` and `OLLAMA_CONTEXT_LENGTH` govern different
resources and do not remove the question cap.

The live status and Batch timing details show active/queued/completed requests,
start offsets and elapsed time. A provider response arrives as one complete
batch; the report cannot stream individual answers from a non-streaming API.
Overlapping requests do not prove faster GPU execution. One bounded D1 check
took 19.77 s for two serial 32-question calls, 20.21 s for two concurrent calls,
and 19.65 s for one 64-question call. There was no speed improvement in that
comparison; cache state and runtime scheduling can affect these observations.
Results: `output/capability-report/d1-parallelism-timing.json`.

The existing **Liquid D1 local (Q8)** profile is an alternative for larger native
requests: its direct llama.cpp System One endpoint on port 8101 accepted 512
short Noul questions in one 31,701-byte request, returning all 512 answers in
32.97 s. This is a small synthetic capacity check, not proof that 512 full
catalog questions fit or run faster. It bypasses Ollama's API validation; the
selected backend was not changed. Evidence:
`output/capability-report/direct-d1-512-question-probe.json`.
