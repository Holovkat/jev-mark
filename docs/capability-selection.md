# Jev capability selection

One shared selector recommends skills and tools before each task turn in
Codex desktop/CLI, Claude Code, Pi and ZCode. It uses the stable Jev gateway
at `http://127.0.0.1:8096/v1/decision`; the service owns TypeSafe/provider
routing. No caller model setting or credential is required.

This version is advisory. The adapter adds selected native skill references
and actual tool names to context. It does not load every skill body, remove
existing context, disable tools, install plugins, or grant execution permission.
The agent still loads the selected guidance through native discovery. Native
project instructions and skill discovery remain authoritative.

## Selection contract

`scripts/capability_selector.py` accepts a versioned packet containing:

```json
{
  "version": 1,
  "harness": "pi",
  "session_id": "native-session-id",
  "project": "/local/project",
  "task": {"request": "Current task", "stage": "requirements_handoff"},
  "skills": [{
    "id": "requirements-traceability",
    "name": "requirements-traceability",
    "description": "Check agreed requirements against documents and tickets",
    "path": "/native/skill/SKILL.md",
    "content_hash": "sha256-of-exact-file-bytes",
    "required": true,
    "dependencies": []
  }],
  "tools": [{
    "id": "read",
    "name": "read",
    "description": "Read a local file",
    "available": true
  }],
  "catalogue_complete": true
}
```

Explicit and required candidates are preserved in code before Jev is called.
Known skill dependencies are included transitively. Missing dependencies,
unreadable or changed skill sources, unavailable mandatory tools, malformed
responses and incomplete work preserve native discovery and the known mandatory
references. A candidate abstention leaves that candidate to native discovery
while retaining useful recommendations for the others. Unavailable tools are
never recommended.

Jev classifies remaining metadata as `use_now`, `available_later`,
`not_relevant` or `abstain`. Only `use_now` references are injected. These
labels do not suppress future discovery. A partial catalogue can produce
useful advice for known candidates without claiming complete coverage.

Only scrubbed task text and candidate names/descriptions go to Jev. Local
paths, session identity, hashes, full skill bodies, transcripts, runtime
system prompts and credential files stay local. Relevant public `AGENTS.md`
paragraphs naming skills provide policy evidence; they are quoted data rather
than execution instructions to the decision model.

## Adapters and inventories

| Harness | Trigger | Inventory boundary |
| --- | --- | --- |
| Codex desktop/current CLI | `UserPromptSubmit` | Filesystem skills and resolvable enabled plugins; native overrides/discovery remain authoritative |
| Claude Code | `UserPromptSubmit` | Project/personal skills and enabled installed plugin skills; native discovery remains authoritative |
| Pi | `before_agent_start` | Native event skill catalogue, `getAllTools()` and `getActiveTools()` |
| ZCode | `UserPromptSubmit` | Configured/default skill roots and disabled overrides; native discovery remains authoritative |

Hook adapters cannot reconstruct a complete runtime tool registry. They only
classify tools supplied by the caller; they never generate a static tool list.
Pi keeps active tools unchanged. Its adapter appends guidance to the current
turn's original system prompt and deletes its private temporary packet on
every completion path.

All command hooks emit exactly one native JSON object with
`hookSpecificOutput.hookEventName: "UserPromptSubmit"` and
`hookSpecificOutput.additionalContext`. Adapter errors emit `{}`. No Stop or
SessionStart schema is reused here.

## Explicit project policy

Optional project `.jev/capabilities.json` supplies deterministic requirements:

```json
{
  "required_skills": [],
  "stages": {
    "requirements_handoff": {"required_skills": ["requirements-traceability"]},
    "epic_verification": {"required_skills": ["mercury-test-evidence"]}
  }
}
```

An orchestrator can supply `task_context` (or `taskContext`) with `request`,
`objective`, `stage`, `unresolved` and `required_skills`. An explicitly supplied
`task_context_path` can name the same JSON metadata. Stage rules apply only
when a stage was supplied; the hook does not guess an epic or release stage.
Missing configured mandatory skills are surfaced as a discovery gap.
Explicit `$skill-name`, `/skill:skill-name` and `/skill skill-name` requests
protect known skills. Conditional native project requirements continue to
bind the agent even when a prompt hook lacks enough stage context to classify
them deterministically.

## Cache and operation

Successful finite decisions are cached under
`~/.local/state/jev-capabilities/cache` (`0700` directory, `0600` files).
`JEV_CAPABILITY_STATE_DIR` overrides that path. Keys include task/stage/policy,
harness, session, project, catalogue, actual skill bytes, selector source and
gateway address. Changed inputs invalidate reuse; outages and abstentions
are not cached as successful judgments.

Requests respect the gateway's 64-context/16 MiB bounds. Total decision
deadlines follow the native boundary: Claude prompt hooks use 30 seconds,
ZCode 60 seconds, and Codex/Pi use the gateway's 180-second deadline. Large
catalogues may reach that deadline and retain native discovery. `--timeout`
can select a shorter operation deadline without changing the native contract.

Install with:

```bash
python3 scripts/install_capability_selector.py
```

The installer preserves unrelated hooks/settings, backs up changed configs
outside discovery directories, and links one shared `jev-capabilities` skill
into all four harnesses. It adds a Pi extension without replacing existing
extensions. Re-running is idempotent; unrelated same-name destinations are
reported before any installation changes.

Review/trust the new Codex hook through native `/hooks` in the current bundled
CLI, then open a new session. Reload Claude hooks/start a new session, use Pi
`/reload`, and start a new ZCode session. Registration alone does not prove
Codex trust or that an already-running session loaded the integration.

For a private local catalogue diagnostic:

```bash
python3 integrations/capabilities/hook.py --harness codex --catalogue < event.json
```

Catalogue output contains local paths and task evidence: keep it local. Normal
hook output contains only selected references, recommendations and fallback
guidance. This selector complements the existing Jev compaction and SDLC
readiness processes; it does not change their requirements or approvals.

## Local installation evidence (2026-09-30)

The combined scenario gate passed all eight cases:

```bash
python3 -m unittest discover -s tests -p test_capability_selection.py -v
```

It exercises the shared core, real Python hook subprocess, isolated installer
destinations and the installed Pi loader/callback. Jev response failures are
fixtures; they do not claim a full model session in every harness. The native
installed Codex hook also returned valid context with four skill references
through the live gateway using the real local catalogue. ZCode's native
`skills list` discovers `jev-capabilities`. Re-running the real installer made
no changes. Local command/case/source receipts are under ignored
`logs/capability-selection/20260930/`.

Codex 0.159.0's native hook review showed the exact new UserPromptSubmit
command, saved trust, and reported all three prompt hooks active. The shell's
Homebrew `codex` remains 0.45.0 and cannot run these lifecycle hooks. Use the
current app-bundled CLI for hook-enabled sessions:

```bash
/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex
```

Restart existing Codex/Claude/ZCode sessions and reload Pi to adopt the new
configuration. End-to-end model-session behavior across all four harnesses
has not been claimed by this local integration verification.
