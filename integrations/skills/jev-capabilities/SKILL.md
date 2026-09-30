---
name: jev-capabilities
description: Inspect or supply task context for automatic Jev skill selection and tool recommendations across Codex, Claude Code, Pi and ZCode; diagnose missed selections or native-discovery fallback.
---

# Jev capability selection

The installed prompt hook or Pi extension normally selects guidance before
the agent starts. Its output is advisory: use the selected native skill
references for the current task, preserve explicitly requested and required
skills, and discover additional capabilities when the work needs them.
Loading guidance does not authorize tool execution or deployment.

Resolve this directory through symlinks; the shared Jev repository is three
parents above the canonical directory. Read `docs/capability-selection.md`
for packet format, native adapters and configuration.

Use actual task intent and stage, current owner corrections and unresolved
work. Never fabricate missing context. Where a native hook does not expose the
full skill or tool catalogue, retain normal discovery and report that boundary.
Do not rebuild a static tool list or disable tools to make a recommendation
look enforced. Pi supplies actual tool metadata; other adapters only classify
tools when an actual inventory has been supplied.

Project `.jev/capabilities.json` may declare always-required skill names and
stage-specific requirements. Apply the stage-specific rule only when the stage
is explicitly supplied by the orchestrator. Missing mandatory guidance stays
visible as a discovery gap; it cannot be approved away by Jev.

For diagnosis, compare the current packet, skill paths and content hashes with
the selected result. Jev sees scrubbed task and capability metadata, not full
skill bodies, runtime instructions, credential files or private reasoning.
Uncertain, unavailable or malformed judgments preserve mandatory selections
and native discovery. Cached decisions apply only to unchanged inputs.
