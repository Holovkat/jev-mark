# OpenAI Workbench latency investigation

8 October 2026. Investigation only; app configuration and selected provider unchanged.

Replayed the Workbench's exact 100-question ambiguity payload: six batches of
16 plus four questions, seven concurrent calls, GPT-6-Luna with medium reasoning.
Used the installed app's credential record and the same provider implementation.

| Result | Owner report | Replay |
| --- | --- | --- |
| Total wall time | 18.7 s | 20.865 s |
| Completed questions | 36 | 36 |
| Failed questions | 64 | 64 |
| Gateway requests | 7 | 7 |

Four batches failed in 1.0–1.3 s with HTTP 400, code `invalid_json_schema`,
parameter `text.format.schema`. OpenAI's message says quotation marks are not
allowed in strict structured-output string literals. The adapter inserts original
choice labels directly into schema enums. A safe fix is to represent choices and
distribution keys with opaque IDs, then restore the exact original labels locally.
This preserves question meaning without rewriting user labels.

The two successful 16-question batches took 18.907 and 20.864 s. First text
arrived at 2.249 and 2.196 s, with 919 and 1030 output tokens respectively. The
four-question batch took 8.422 s and generated 337 output tokens. Each successful
request reported zero reasoning tokens. Most measured time followed the first
text event, so generated structured output dominates this replay's latency.
Medium effort was submitted; the usage evidence does not attribute the delay
to reasoning. No 429, timeout or automatic retry was observed.

This is `/v1/responses`, despite the requested display label **Open AI - Decision
API**. It generates probabilities/confidence as model estimates. It is not a
native `/v1/decisions` performance result. The [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
describes a dedicated typed classification endpoint; the [SIWC inference guide](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
documents ChatGPT-plan inference through Responses. Actual Decisions endpoint
access has not been tested, and its examples use a separately billed API key.

The Workbench's 94% acceptable figure uses returned questions only (34/36),
excluding 64 missing questions. It is not 94% success across the whole test.

Recommendations: correct the strict-schema label encoding in the ChatGPT adapter;
show the actual inference protocol; add native Decisions as a separate provider
with its own authorized credential and compare identical complete cohorts.

Detailed evidence: `openai-latency-investigation.json`.
