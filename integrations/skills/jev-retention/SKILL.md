---
name: jev-retention
description: Prepare an explicit Jev retention checkpoint before conversation compaction or handoff, preserving user decisions, corrections, constraints and unfinished work as source excerpts.
---

# Jev retention checkpoint

Use the shared finite retention classifier to identify which supplied assistant
and tool excerpts can be omitted from a continuation. User directions and
corrections, governing constraints, prior accepted summaries and unresolved work
remain protected. Uncertainty or unavailable Jev retains the supplied evidence.

Resolve this skill directory through symlinks. The shared Jev repository root
is three parents above the canonical directory. Read its
`docs/compaction-retention.md` when the adapter's behavior matters.

Build a private JSON packet from actual accessible discussion text:

```json
{
  "objective": "The current agreed outcome",
  "blocks": [
    {"id": "U1", "role": "user", "text": "Exact user direction"},
    {"id": "A1", "role": "assistant", "text": "Exact accepted decision or unresolved blocker", "protected": true},
    {"id": "A2", "role": "assistant", "text": "Exact candidate excerpt"}
  ]
}
```

Keep provenance alongside the packet. Do not invent missing discussion, export
private reasoning, runtime system/developer instructions, credential files or
raw credential-bearing logs. Use mode 0600 for the packet. Do not use a hook's
`transcript_path` as full conversation evidence: installed ZCode supplies only
the current response/prompt there, or an empty file.

Run the shared writer with the resolved repository path:

```sh
python3 <jev-root>/scripts/retention_checkpoint.py --packet <private-packet.json> --output <private-checkpoint.json>
```

The writer saves an extractive checkpoint with source fingerprint and private
permissions. Inspect its status, decisions and `retained_text`. A fallback is
not a successful Jev judgment; retain all source evidence and report the cause.
Never edit/delete the original session or ask Jev to manufacture a summary.

For ZCode, this is an explicit preparation step. ZCode has no `PreCompact`
callback or supported summary replacement interface. Return the retained source
excerpts for continuation and this native action, using the actual saved path:

```text
/compact Preserve the agreed constraints and unresolved work in the Jev checkpoint at <absolute-checkpoint-path>, which has been read into this conversation.
```

Read the checkpoint's retained text into the conversation before compaction;
the compactor cannot be assumed to read a filesystem path. Native compaction
still determines its summary. This checkpoint does not automatically control
overflow compaction or remove discussion from ZCode's session history.
