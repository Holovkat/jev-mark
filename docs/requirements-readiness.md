# Requirements readiness handoff

The existing `requirements-traceability` skill now has a planning readiness
mode alongside its implementation/done checks. It runs when requirements or
planning finishes, and before epic or sprint implementation starts. No Stop
hook, extension registration, trust setting, or every-turn check is required.

Read the final agreed discussion, retaining provenance for corrections,
constraints and explicit deferrals. Map both directions between these
commitments, the existing canonical requirement/design documents, and real
live tracker tickets and acceptance criteria. Brainstorming and draft tickets
do not establish scope or tracker coverage.

Exactly one overarching verification task belongs to the selected epic OR
sprint, after implementation and before Dev UAT. All agreed scenarios,
acceptance criteria, failure paths and regression touchpoints map to it.
Supporting cases and suites may be numerous; missing, duplicate, uncovered or
per-task micro-test gates fail readiness. Narrow development diagnostics remain
permitted by project policy.

The packet contract and CLI usage are in
[`schema.md`](../integrations/skills/requirements-traceability/references/schema.md),
with a [`handoff-packet.json`](../integrations/skills/requirements-traceability/references/handoff-packet.json)
starting shape. The CLI reads live sources and uses bounded Jev classification.
Failed prerequisites force FAIL; missing evidence yields ABSTAIN. Jev cannot
invent scope, grant approval, or authorize implementation or deployment.

On gaps, prepare concrete repairs to existing documents and tracker criteria.
Apply only those authorized in the current task. External tracker writes need
current human authorization; installing this process does not authorize backlog
changes. Re-read live sources after repair before reporting readiness.

## Shared installation

From the Jev repository run:

```sh
python3 scripts/install_requirements_skill.py
```

Optional `--codex-home PATH` and `--pi-agent-dir PATH` select installation roots.
The installer links both skills directories to the canonical shared directory,
backs up existing same-name skill directories outside discovery, refuses
unrelated collisions, and is idempotent. It does not touch hooks or settings.
Invoke `$requirements-traceability` in Codex, or
`/skill:requirements-traceability` in Pi. Reload skill discovery in an existing
session if the newly installed skill is not yet listed.

The `plan-feature` and `orchestrate` skill handoffs call this mode. Existing
implementation/done evidence checks remain available. PASS proves this planning
handoff only; owner acceptance, deployment and release retain their own gates.
