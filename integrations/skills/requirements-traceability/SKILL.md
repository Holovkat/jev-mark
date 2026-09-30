---
name: requirements-traceability
description: Gate requirements and planning handoff before epic or sprint implementation by comparing agreed session commitments with live canonical documents and tracker acceptance criteria; also check implementation coverage and done evidence.
metadata:
  short-description: Bidirectional requirements completeness check.
---

# Requirements Traceability

Run the planning readiness mode when finishing requirements or planning, and
before starting epic or sprint implementation. Run implementation/done mode
before implementation is declared complete, Dev UAT, or approval when work is
governed by tickets, epics, specs, or a long session discussion. This is a
handoff trigger, not a check on every reply or a Stop hook.

The authoritative requirement set comes from the ticket, epic, accepted spec,
and explicit owner decisions. Session discussion clarifies intent and records
decisions, but does not silently add requirements. Implementation evidence
comes from the diff, tests, runtime/UAT evidence, deployment evidence, and
documented deferrals.

## Planning readiness handoff

Read [references/schema.md](references/schema.md) and use
[references/handoff-packet.json](references/handoff-packet.json) as the packet
shape. Resolve this skill directory through symlinks; the shared repository
root is three parents above the canonical directory. Use its
`scripts/requirements_readiness.py` CLI, following the schema reference.

Gather the final agreed commitments from the actual discussion with source
references: corrections supersede earlier statements, constraints remain
binding, and explicit deferrals retain owner provenance. Brainstorming and
unaccepted suggestions are not scope. Missing discussion evidence requires
`ABSTAIN`; do not reconstruct agreement from assumptions.

Read the existing canonical requirement/design documents and real live tracker
epic/sprint and tickets, including acceptance criteria. Map every agreed
commitment to document clauses and ticket criteria, and map every scoped clause
and criterion back to an agreed commitment or established authoritative scope.
Use source IDs and evidence references in both directions. Draft issue text,
local snapshots, and proposed tickets do not prove live tracker coverage.

Require exactly one overarching verification task for the selected epic OR
sprint, after all implementation tasks and before Dev UAT. It owns every
agreed scenario, failure path, regression touchpoint, and acceptance criterion.
Multiple supporting cases and suites belong inside that task. Missing,
duplicate, uncovered, or per-implementation micro-test gates fail readiness;
narrow compile/build/diagnostic checks needed to continue safely are permitted.

Run deterministic prerequisites before bounded Jev classification. Failed
prerequisites force `FAIL`; absent or unreadable evidence yields `ABSTAIN`.
Jev classifies quoted evidence using the CLI's bounded schema, never supplies
scope, grants approval, or selects a model/provider. Preserve the packet and
result so downstream skills reuse them unless evidence changes.

For gaps, prepare concrete changes to existing canonical documents and ticket
acceptance criteria, with source commitment and missing scenario identified.
Apply only repairs within current human task authorization; external tracker
writes require that authorization. Building this process does not authorize
backlog edits. Re-read repaired documents and live tickets, rerun affected
mapping, and report readiness only from that readback. `PASS` means planning
handoff is ready; it does not authorize scope, implementation, deployment, or
release beyond the user's existing instruction.

## Two directions

### 1. Requirement gathering completeness

For every authoritative requirement, map:

- the source requirement or acceptance criterion;
- the session decision or clarification that explains it, if one exists;
- the planned task or explicit deferral;
- unresolved ambiguity or conflicting instruction.

Classify each item as `accounted`, `partial`, `missing`, `deferred`, or
`ambiguous`. A requirement is not accounted for merely because it was
mentioned in conversation; it needs a task, acceptance criterion, or explicit
owner decision.

### 2. Implementation completeness / done determination

For each requirement, map:

- implementation files or runtime contract;
- focused test or diagnostic evidence;
- Dev UAT or owner evidence where required;
- QA/deployment evidence where the requested gate requires it;
- residual risk or an explicit accepted deferral.

Classify each item as `implemented`, `partially_implemented`, `not_implemented`,
`blocked`, `deferred`, or `not_proven`. `done` requires every must-have item to
be implemented and proven at the current delivery gate. A passing unit test or
JEV result cannot prove owner acceptance, deployment, or release readiness.

## JEV use

Use the `jev-decision` skill as a secondary classifier over one requirement at
a time or a small structured batch. In an orchestrated run, create one shared
packet and let the orchestrator make the single JEV call for the batch. Planning,
implementation, code-review, and release skills consume that packet; they do
not repeat the same call. A new call requires changed evidence or an explicit
replay request.

Provide the requirement, session decision, task mapping, implementation
evidence, gate rules, and evidence references as quoted data. Use finite enums,
explicit descriptions, `abstain`/`ambiguous`, and per-item confidence.
Calculate percentages externally from the traceability matrix:

- gathering coverage = accounted requirements / total must-have requirements;
- implementation coverage = implemented-and-proven requirements / total
  must-have requirements.

Do not let JEV invent requirements, merge distinct requirements, or declare
done. Check deterministic blockers before accepting any JEV classification:
failed required checks, open must-have tasks, missing owner/UAT evidence, and
unverified deployment keep the row `not_proven` or `blocked` regardless of a
positive JEV label. Preserve the packet and result beside the source evidence
and surface disagreements for human resolution.

## Remediation and output

Return a matrix and a gate statement. Missing or partial must-have items become
`CHANGES_REQUIRED` with an implementer repair packet: requirement, evidence
gap, intended files/contracts, focused check, and owner decision needed. After
repair, rerun the affected rows and the structural review. If all current-gate
requirements are proven, report the exact gate reached; do not promote the
claim to QA or release without those gates' evidence. The repair packet is the
implementer's input; it must name the row, evidence gap, owned files/contracts,
focused check, and the next gate that can be reconsidered.
