# Ticket: Decision replay cache, savings metrics, and the model rate card

- **Date**: 2026-11-18
- **Branch**: `main`
- **Status**: implemented, deployed to the installed service, and verified live
  (commits `d55d6a3`, `fc049f5`, `bbdf556`, `d910def`, `0ce9e49`)

## Summary

Lands a content-addressed **decision replay cache** in the gateway, automatic
storage housekeeping for the analytics recorder, an **avoided-cost metrics**
layer so every cache hit records what the live call would have spent (tokens
and provider time), an editable **model rate card** in the menu-bar Models
panel, a **Savings line** on the menu usage chart (`Cost: $… · Time: H:MM:SS`),
and a one-off backfill that repairs history created before the metrics existed.
Motivated by the 17 November usage audit: 36.6% of captured gateway bytes were
byte-identical repeat requests, and the analytics DB carried ~281 MB of
never-reclaimed free pages.

## Changes

### Decision replay cache (gateway)

- `POST /v1/decision` requests are intercepted in the service layer
  (`jev_service.py`): key = sha256 over the canonical request (instructions,
  schema, contexts) + selected backend + cache version. A hit returns the
  stored answer with `"cached": true` and `X-JEV-Cache: hit` without calling
  the provider.
- Entries live in `decision_cache` (same analytics SQLite): 14-day TTL,
  10,000-row LRU cap, per-entry `hits` counter and `admitted_via` provenance
  (`replay` / `bootstrap-luna`).
- Errors, disconnects and incomplete responses are never cached. Any cache
  fault falls through to the live path — cache failures cannot alter a
  decision response. Kill switch `JEV_DECISION_CACHE=0`; per-request bypass
  header `X-JEV-No-Cache: 1`.
- Entries store the **avoided spend** of the originating live call: input
  tokens, output tokens, and provider duration. Every `cache_hit` analytics
  row carries those metrics plus the real model name, so savings are summable
  from the `requests` table alone. `estimated=1` marks rows whose metrics are
  byte-size estimates rather than exact recorded usage.

### Automatic housekeeping (analytics recorder)

- `PRAGMA auto_vacuum=INCREMENTAL` is set before the database header is
  initialized; a one-time full `VACUUM` runs at startup past a 16 MB
  free-list threshold; `incremental_vacuum` runs on every prune tick.
- Captured request/response bodies are content-addressed (`payload_bodies`,
  keyed by sha256): 37% of captured bytes were exact repeats. The first
  offline backfill took the analytics DB from 408 MB to 93 MB.
- Tools: `scripts/tools/export_answer_store.py` (bootstrap/refresh cache
  entries from captured payloads), `backfill_payload_bodies.py` (one-time
  dedupe + vacuum), `backfill_savings_estimates.py` (repair legacy entries and
  hit rows), `ablate_batch_size.py` (batch-composition ablation).

### Avoided-cost backfill

- `export_answer_store.py` seeds cache entries from captured request/response
  pairs and threads the originating rows' tokens/duration; re-running
  refreshes metrics in place.
- `backfill_savings_estimates.py` repairs history: recovers exact metrics for
  entries whose originating call is uniquely identifiable, prices
  unknown-model entries from their backend's profile model in `typesafe.json`
  (`remote:openai-decisions-api` → `gpt-6-luna`), estimates legacy hit rows
  from captured request size (~4 bytes/token) with the backend's mean live
  duration, and marks all estimates `estimated=1`. First runs: 323 entries
  seeded, 8 entries recovered exactly, 150 hit rows estimated.

### Model rate card (menu bar)

- New `RateCardStore` (`TypesafeAPI.swift`) persists
  `~/Library/Application Support/JEV Menu Bar/rates.json` (outside `.secure` —
  editable preferences, not credentials), seeded with published prices:
  gpt-6-luna **$0.10 input / $0 output per MTok** — the Decisions API bills
  input tokens only, unlike the Responses API's $0.10/$0.50 — and TypeSafe
  models at the $0.042 reference rate.
- The "Ollama models" popover is renamed **"Models"** and grouped:
  **Ollama** rows are unchanged (checkbox, batch size, image input) and show
  a static "Free"; a new **Service models** section lists every hosted
  profile with editable "In $/M" and "Out $/M" fields (inline-binding
  pattern, persisted on every edit). Panel widened 420→560. Batching
  controls for service models are deliberately deferred.

### Savings line (menu bar)

- `UsageHistory.snapshot` now reads `outcome`, `model`, token counts and
  `duration_ms`, pricing cache-hit rows against the rate card.
- The usage chart gains a second footer row: left **Savings**, right-aligned
  `Cost: $0.712 · Time: 0:03:49` (3-decimal dollars; sub-cent amounts gain
  decimals instead of rounding to $0.000; time is H:MM:SS of avoided provider
  time). Accessibility text reflects both figures.
- Analytics portal: `cache_hit` added to the outcome filter and badge styles.

### Pricing correction

- First seed used the Responses API card for gpt-6-luna ($0.10/$0.50). The
  deployment actually calls the **Decisions API**, which bills **input only**
  ($0.10/MTok, cached $0.01, no output charges) per OpenAI's announcement and
  pricing pages. Seed and installed `rates.json` corrected; recorded output
  tokens were ~0, so prior savings figures were unaffected.

## Verification

- `python3 -m unittest tests.test_jev_analytics` — 67/67 green (cache
  roundtrip with metrics, TTL/LRU eviction, hit-row avoided-spend assertions,
  estimation fallback, vacuum reclaim, payload dedup).
- Live: identical POST twice → first `complete`, second `cache_hit` with the
  real model and the original call's tokens/duration; bypass header and kill
  switch confirmed; entry-model repair confirmed in the store.
- Post-repair window (12 h): 171 hits avoided 7,124,632 input tokens =
  **$0.71** against $1.36 of live input spend — ~34%, matching the 171/532
  hit share and the operator's expectation.
- Menu verified by operator screenshot: `Request: 541 · Cache: 171` over
  `Savings  Cost: $0.712 · Time: 0:03:49`, green hit bars stacked on live
  bars, and the grouped Models panel with editable rates.

## Known limits

- Hits against entries created before the metrics columns existed are
  byte-size estimates (`estimated=1`); exactness accrues as history ages out.
- The rate card is list-price. The Decisions API's own prompt caching, batch
  discounts and the operator's Codex quota can lower real spend below these
  figures — the card is an intentionally conservative upper bound and is
  editable.

## Files

- `scripts/jev_analytics.py`, `scripts/jev_service.py`
- `scripts/tools/export_answer_store.py`, `backfill_payload_bodies.py`,
  `backfill_savings_estimates.py`, `ablate_batch_size.py`
- `Sources/JevMenuBar/TypesafeAPI.swift`, `main.swift`, `UsageHistory.swift`
- `Resources/Web/analytics.html`
- `tests/test_jev_analytics.py`
- `docs/images/menubar-decision-service.png`, `docs/images/models-panel.png`
- `README.md`, `docs/README.md`, `docs/service-analytics.md`
- `docs/tickets/2026-11-18-decision-cache-savings-and-rate-card.md` (this ticket)
