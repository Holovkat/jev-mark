# Jev compaction retention

One shared classifier serves Pi, Codex and explicit ZCode checkpoints. It selects source excerpts through
the stable Jev gateway at `http://127.0.0.1:8096/v1/decision`; provider routing
remains in the Jev menu-bar service. It never asks TypeSafe to generate a prose
summary and never deletes original session history.

## Retention policy

User directions and corrections, explicitly protected prior summaries, and
runtime instruction blocks supplied by an adapter are retained deterministically.
Jev classifies assistant and tool evidence against all retained user directions:
keep essential decisions, constraints, unfinished work, blockers, and evidence
needed to continue; drop only demonstrably superseded or irrelevant material.
Uncertain classifications retain the original excerpt. Service failure,
malformed or contradictory decisions, and unsupported formats fall back to
native compaction. There is no probability threshold or invented content cap.

Quoted data is classified as evidence. It cannot grant permissions or override
current instructions. Credential-shaped values are redacted before outbound
classification. This is pattern matching, not a guarantee that arbitrary private
information can be detected: a selected remote provider receives the remaining
conversation evidence, just like other Jev requests. Full system/developer
runtime instructions and opaque reasoning are not exported by the Codex adapter.

`scripts/compaction_retention.py` reads `{blocks:[{id,role,text,protected?}],
objective?}` on stdin and returns decisions plus an extractive `retained_text`.
Gateway limits (64 contexts and 16 MiB request bodies) determine batching. The
180-second HTTP timeout follows the gateway's provider timeout. No arbitrary
truncation is performed. If data does not fit the gateway or host runtime,
the adapter uses the runtime's normal summarizer.

## Pi

`integrations/pi/jev-compaction.ts` handles `session_before_compact` for manual,
threshold, and overflow compaction. It preserves `previousSummary`, user
directions, custom compaction instructions, file operation provenance, and the
native recent-history cut at `firstKeptEntryId`. Successful Jev selection replaces
the older-history summary. It does not alter recent messages or historical JSONL.

The adapter honors cancellation and checks the extractive result against Pi's
native summary output allowance and model window. Installed Pi derives the
history allowance from `0.8 * reserveTokens` and an additional split-turn prefix
allowance from `0.5 * reserveTokens`, each capped by the model's maximum output.
The adapter follows these runtime values using Pi's own character-based token
estimate. Oversized results and Jev failures
use normal Pi summarization with a warning. Load only one custom compaction
replacement extension: Pi's hook runner uses the last supplied result.

For a single session:

```sh
pi -e /Volumes/Seagate/workspace/jev-mark/integrations/pi/jev-compaction.ts
```

A symlink in `~/.pi/agent/extensions/` enables discovery for new sessions.
Existing sessions need `/reload`.

Install both adapters while preserving existing configuration:

```sh
python3 /Volumes/Seagate/workspace/jev-mark/scripts/install_compaction_hooks.py
```

## Codex desktop and modern CLI

`integrations/codex/jev_compaction_hook.py` uses `PreCompact` to save a private,
session-scoped retention packet. `SessionStart` with `source: compact` restores
the selected excerpts before the next model request. Both hooks must be trusted
through Codex's hook review. They do not replace or filter Codex's native summary:
the documented hook API offers no history-selection or summary-replacement output.

Packets are written atomically with mode 0600 under
`~/.local/state/jev-compaction/codex/`. `JEV_COMPACTION_STATE_DIR` can change that
location. A transcript prefix hash and observed subsequent compaction prevent
stale packet restoration. A new capture invalidates the previous packet;
restoration delivers each packet once. The latest packet also serves as a local
decision audit. No persistent memory files are written.

Codex's transcript format is not a stable API. Unsupported records or nontext
message content disable custom retention for that compaction. Native compaction
continues. Codex's standard additional-context limit handles large restored
packets by supplying a preview and file reference; selected excerpts may require
reading that reference. Do not interpret this as exact message removal control.

The configured hooks apply through `~/.codex/hooks.json` to both desktop and
compatible CLI sessions. The shell's Homebrew CLI reports `codex-cli 0.45.0`,
which predates these hooks. The desktop app already bundles `codex-cli 0.159.0`
with stable hooks enabled; it can also be launched directly from a terminal
without changing the Homebrew installation:

```sh
/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex
```

Use `/hooks` there to review and trust the two Jev definitions. Trust state is
shared through the user Codex configuration. Desktop and CLI each still need
an observed compaction smoke test; a version/feature check is not that proof.

Official hook contract: https://learn.chatgpt.com/docs/hooks

## ZCode

ZCode has no native PreCompact hook or summary replacement interface. The
shared `jev-retention` skill prepares an explicit private retention checkpoint
before `/compact [instructions]`; it does not intercept automatic compaction.
Read the retained excerpts into the conversation before instructing native
compaction to preserve them. The temporary hook transcript is not complete
conversation evidence. Installation, skill invocation and supported Mercury
tool/Stop hooks are documented in [zcode-integration.md](zcode-integration.md).

## Verification

Run focused classifier and Codex adapter tests:

```sh
python3 -m unittest discover -s tests -p 'test_*compaction*.py'
node --test tests/test_pi_compaction.mjs
```

Pi loading and synthetic event checks can verify adapter wiring without making
an agent-model request. Final runtime proof requires a disposable session with
a goal, correction, completed detour, and unresolved blocker: compact it and
confirm the correction and blocker survive. This is distinct from classifier
unit tests or successful gateway requests. Never use real credential-bearing
conversations as smoke-test fixtures.
