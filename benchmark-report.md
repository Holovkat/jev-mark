# Local logic benchmark

Run date: 2026-09-22. The current run used the 11 prompts in
`scripts/logic_benchmark.py`: the supplied car-wash question plus 10 bounded
logic questions. Each Ollama request was asked to return exactly one listed
choice. JEV used the same choices as a finite decision schema.

## Results

| Backend/model | Correct | Concise | Mean time | Median | Range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ollama `gemma4:12b` | 11/11 | 11/11 | 2.99 s | 3.45 s | 1.92–4.23 s |
| Ollama `granite4.2:latest` | 10/11 | 11/11 | 7.13 s | 11.95 s | 0.87–12.64 s |
| Ollama `maternion/minicpm5:2b-f16` | 11/11 | 11/11 | 4.90 s | 7.95 s | 0.38–9.34 s |
| Ollama `maternion/minicpm5:2b` | 11/11 | 11/11 | 3.15 s | 5.38 s | 0.43–5.43 s |
| Ollama `SparkLLM/Spark-X2.5-4B:latest` | 11/11 | 11/11 | 9.34 s | 16.03 s | 1.05–16.48 s |
| Ollama `ornith-1.5:9b` | 11/11 | 11/11 | 7.24 s | 12.03 s | 1.36–12.25 s |
| JEV `gemma4:12b` | 11/11 | 11/11 | 0.62 s | 0.56 s | 0.50–1.36 s |

The Ollama calls were concurrent across models, so the large ranges and high
medians include model loading/eviction and contention. They should not be
treated as steady-state single-model latency. JEV ran against the already
loaded `gemma4:12b` server and used schema-specific requests. Compared with
Ollama `gemma4:12b`, JEV reduced mean decision latency by about 79% in this
run, or 2.38 seconds per decision; this is a decision-stage comparison, not an
end-to-end agent workflow saving.

For the supplied car-wash question, JEV and five Ollama backends selected
`drive`; Granite selected `walk` in this run. JEV returned `confidence: high`.

## Interpretation

This is a correctness and bounded-output smoke test, not a claim that all
models are equally capable. The prompts are intentionally simple and the
choices are explicit. The useful signal is that JEV gives reliable finite
decisions without generating explanations, reasoning traces, markdown fences,
or post-hoc JSON repair. A production benchmark should add ambiguous cases,
adversarial wording, long contexts, and domain-specific labels.

## Current adjudication replay

The same run generated four raw model responses per question—including
Granite—and asked JEV to rank them. A single pass selected a
reference-correct response in 11/11 cases at 2.07 seconds per case. Five
shuffled passes also produced 11/11 correct majority winners across 55
decisions. However, the winning candidate was in the first position 40/55
times, so shuffled repetition and external aggregation remain necessary; a
single `winner` field is not sufficient evidence.

## Direct TypeSafe API comparison

The supplied `.secure/env.dev` profile was also tested against the same 11
questions. TypeSafe `jev-latest` returned 11/11 correct at 0.91 seconds mean,
0.72 seconds median, and 0.67–1.79 seconds range. Local JEV/Gemma returned
11/11 at 0.55 seconds mean. The direct hosted API was therefore about 0.36
seconds slower per decision in this run, while retaining the same bounded
answer contract. This comparison includes network latency and should be
repeated over several runs before choosing a default provider.
