# Jev in ZCode

The installed ZCode desktop app (3.14.4) bundles CLI 0.16.9. Its native user
configuration and skill discovery are used directly; no signed application
files, session databases, provider configuration or trust records are changed.

Install or refresh the integration:

```sh
python3 /Volumes/Seagate/workspace/jev-mark/scripts/install_zcode.py
```

The installer preserves unrelated configuration and hooks, saves a private
configuration backup, links shared skills into `~/.zcode/skills`, and enables
four user hooks in `~/.zcode/cli/config.json`. Re-running it is idempotent.
New ZCode sessions read this configuration. Existing running sessions need a
new session after installation.

## Skills

- `/skill requirements-traceability`: the same canonical planning handoff gate
  used by Codex and Pi. It compares actual agreed discussion, canonical docs
  and live tracker criteria. Exactly one final verification task must cover
  every implemented scenario in the selected epic or sprint, after all
  implementation tasks and before Dev UAT. Missing, duplicate or uncovered
  verification fails readiness. Supporting cases and suites belong inside
  that task.
- `/skill jev-decision`: shared finite classification through the stable Jev
  gateway; provider and TypeSafe routing stay in the service.
- `/skill jev-retention`: explicit compaction preparation with private,
  extractive checkpoints. See the compaction boundary below.

Planning and orchestration skills already discovered through `~/.agents/skills`
retain their requirements handoff triggers. SessionStart also supplies concise
Jev workflow guidance. Requirements readiness runs at handoff, not every Stop.

## Native hook adapter

`integrations/zcode/jev_hook.py` translates ZCode's camelCase fields (and
compatible snake_case fields) to Mercury's canonical
`scripts/mercury_test_gate.py`. It activates that gate only in a repository
ancestor containing both that script and `docs/MERCURY_TEST_GATE.md`.

| ZCode event | Action |
| --- | --- |
| SessionStart | Supply skill and workflow guidance; no Jev request |
| PreToolUse | Enforce preparation and reviewed test cadence for recognized edits/commands |
| PostToolUse | Record actual final structured outcomes; stdout alone cannot prove completion |
| Stop | Consume an explicitly armed completion assessment; repeat-stop guard prevents automatic loops |

Installed ZCode supplies the actual Bash execution directory in event `cwd`.
The adapter exposes it as normalized `tool_input.workdir`, preserving the exact
command. Native `ApplyPatch.patch_text` becomes `apply_patch` input `patch`;
authoring packets must contain that normalized raw patch proposal. Write/Edit
inputs remain unchanged. Native `toolResponse` numeric `exitCode` supplies a
final receipt; background execution is not a completed result. Output streams
support the canonical case parser. Missing exit evidence remains unproven.

Use the canonical Mercury planner, session activation and governed runner
documented in `docs/MERCURY_TEST_GATE.md`. Activate using the native ZCode
`sess_...` ID shown in denial guidance, not a Codex thread ID. This integration
does not extend the gate to other repositories without their canonical script.
Hook JSON contains only supported event fields; quiet callbacks emit `{}`.

## Compaction boundary

ZCode's native lifecycle has no PreCompact event or summary replacement output.
Its temporary hook transcript is not complete session history. Automatic Jev
retention therefore cannot be installed through these supported hooks.

Run `/skill jev-retention` before an explicit `/compact [instructions]`.
Read the checkpoint's retained excerpts into the conversation first and pass
its preservation instruction to native compaction. Jev selects excerpts;
ZCode still creates its native summary. The source session remains untouched.
This is not an interception of automatic overflow compaction.

## Verification

One scenario gate covers adapter denial/scope, completion and repeat-stop,
native response mapping, configuration preservation/idempotence, and private
checkpoint fallback:

```sh
cd /Volumes/Seagate/workspace/jev-mark
python3 -m unittest discover -s tests -p test_zcode_integration.py -v
```

Confirm native discovery without a model request:

```sh
node /Applications/ZCode.app/Contents/Resources/glm/zcode.cjs skills list --json
```

Protocol references: [ZCode hook contracts](https://github.com/zai-org/ZCode/blob/main/apps/zcode-cli/packages/contracts/src/hooks/index.ts),
[native input implementation](https://github.com/zai-org/ZCode/blob/main/apps/zcode-cli/packages/core/src/hooks/configured-runner-input.ts),
and the installed `zcode-guide-plugin` documentation. Installed runtime source
settles differences between online documentation and the bundled version.

Installation verification on 2026-09-30: six scenario checks passed; native
`skills list` reported all three skills with no diagnostics; desktop Settings
showed the three skills and four hooks enabled. A synthetic live Jev checkpoint
kept a user correction and unresolved blocker and dropped superseded assistant
text. Live model-session hook execution remains unverified: invoking the raw
bundled CLI directly could not locate its built-in provider configuration.
Desktop discovery succeeded; provider/bootstrap configuration was not changed.
