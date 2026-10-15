# Custom llama.cpp runtime update - 14 October 2026

The owner chose to retain our custom decision engine and incorporate the newer
upstream performance improvement. Official llama.cpp was downloaded for the
initial migration request, but was not activated after that clarification.
Generic Gemma/MiniCPM decision support remains available through `/v1/decision`.
Native Ollama and Liquid D1 providers remain as configured.

## Source and change

- Custom source: `/Volumes/Seagate/workspace/jev-llama-nimble`, branch
  `codex/nimble-native-decisions`, base `e6a127c32636ffcc6307a03eb241349e6c08805c`.
- Integrated patch: [ad129b0](https://github.com/thecodacus/llama.cpp/commit/ad129b08d9f134cd298d1f8a85efc52b1b66e18e),
  the latest commit on the upstream `parallel-decision` branch when checked.
- The source mirror in this workspace's `llama.cpp/` contains the same four
  decision module files. Its previous custom probability changes were retained.

The patch detects recurrent/hybrid models, orders branches by length, and
right-pads each batch to its longest branch. This allows recurrent layers to
score the branches in one microbatch. Logits are read at each branch's last real
token; causal padding does not enter the decision. Results are restored to the
original field order. Ordinary transformer models keep their existing path.

Retained custom modifications: complete candidate distributions, an empty
context when a nonempty native shared prefix supplies the evidence, and exact
suffix whitespace for Nimble. No generic `/v1/decision` features were removed.
No local speed comparison was run; upstream GPU timings are not Mac results.

## Installed runtime and rollback

The verified build was installed at `build/bin/llama-server` with its matching
shared libraries and decision worker. The menu-bar app still uses this existing
path and `--decision-seqs 12`. Runtime version reports `0.4.1-dev`, build 2,
commit `e6a127c`; the added upstream patch is recorded separately because it is
an uncommitted source change. Both checkouts remain available.

The previous complete binary directory and source module snapshot are in
`build/runtime-backups/20261014-hybrid-batching/`. To roll back, stop the menu-bar
app and its local model first, retain the updated directory, and restore that
backup `bin` directory to `build/bin` before restarting the app.

The menu-bar service was restarted through its existing LaunchAgent. The
selected provider was preserved as `remote:openrouter-mercury-decide`. The local
model is idle while that remote provider is selected; the next local Start uses
the updated runtime. Strata services remain stopped.

The old outer `build/CMakeCache.txt` references a removed historical checkout.
For a fresh build, use `build/custom-runtime` as shown in the README rather than
reusing that cache. The update itself used the existing warm `build-nimble`
configuration in the custom source checkout.

## Focused regression evidence

- Custom server and worker rebuilt with Metal successfully.
- All 20 existing gateway tests passed.
- Native Nimble Choice, fractional Score and Noul checks passed, including
  unequal suffixes, single/parallel execution, fresh/warm state, reordered
  branches, changed/restored evidence and four invalid requests followed by a
  valid request. No selected answers changed between execution modes. Maximum
  single/parallel probability difference was 0.000062; state isolation was exact.
- The regular MiniCPM local model returned identical decisions and complete
  distributions before and after the update: two contexts, three fields each.
- The installed server and server library hashes match the verified build.
- The installed runtime passed `/v1/decision`, invalid schema rejection (400),
  recovery with a valid request, and `/completion`. Generic decisions and
  probabilities still matched the original runtime exactly.
- The stable gateway returned healthy with the original selected provider after
  restart. Test-only model workers were stopped afterward.

Reports and provenance: `output/llama-runtime-update/`. This is change-scoped
regression verification, not a new speed benchmark or a full dataset replay.
The engine source patch remains uncommitted in the separate custom llama.cpp
checkout. This repository's `llama.cpp/` mirror, binary directories and backups
are ignored and are not distributed by a JEV source push. The base commit,
upstream patch, hashes and reports recorded here identify the local installation;
a fresh JEV clone alone does not reproduce that patched engine. Publishing this
document and its JSON evidence does not commit or push the engine checkout.
