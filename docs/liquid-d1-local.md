# Liquid d1 local test setup

Installed on 14 October 2026. Select **Liquid D1 local (Q8) — d1-3B-Q8_0**
under **System One API** in JEV Menu Bar. It is selected after installation.
The existing **Liquid D1 free** profile remains a separate hosted provider.

## Model and storage

Official weights: <https://huggingface.co/LiquidAI/d1-3B-GGUF>, revision
`bb1e436ea78eb96a3f1acb6da865f70c2fbeb563`.
Downloaded with `ollama pull hf.co/LiquidAI/d1-3B-GGUF:Q8_0`.
Ollama verified the blob SHA256 values during download.

The 2.87 GB text weights and 583 MB vision projector remain in the existing
`/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/blobs` store. The local runtime
reads those blobs directly, with no second model copy.

- Text blob: `sha256-2f0942d5a5f64cf69c3356d2be439b71644b1f0eb3a580912a5a0179eeaba77d`
- Vision blob: `sha256-2505920ce464b7c54acd8b7b74a931c0c671f06d0c8833760b2fbceeb253e92a`

## Runtime and provider

Ollama 0.40.3 rejects the model's native decision encoding with HTTP 400:
`unsupported decision encoding "lfm2-d1"`. Adding `CAPABILITY decision` does
not resolve the unsupported encoding. Do not use the ordinary Ollama model
picker or register this model against Ollama's System One port yet.

The working runtime is the official llama.cpp **b11606 macOS arm64** release:
<https://github.com/ggml-org/llama.cpp/releases/tag/b11606>.
The Homebrew installation (build 9090) returned HTTP 404 for `/v1/systemone`;
it was left unchanged. The repository's existing parallel-decision build was
also left unchanged.

- Runtime directory: `~/Library/Application Support/JEV Menu Bar/runtimes/liquid-d1/llama-b11606`
- LaunchAgent: `~/Library/LaunchAgents/com.codex.jev.liquid-d1.plist`
- Provider: `liquid-d1-local` in the installed `.secure/typesafe.json`
- Native endpoint: `http://127.0.0.1:8101/v1/systemone` (loopback only)
- Shared JEV endpoint: `http://127.0.0.1:8096/v1/decision`
- Settings: Metal offload, 32,768-token context, one runtime slot, Workbench batches of 16 questions
- Idle setting: unload model after 300 seconds; the next request reloads it
- Log: `~/Library/Application Support/JEV Menu Bar/logs/liquid-d1.log`

The LaunchAgent starts at login and restarts after abnormal exits. The SSD
must be mounted for loading the model. A provider configuration backup is
stored beside the configuration as `typesafe.before-liquid-d1-local.json`.

## Verification

The official native endpoint passed a three-question refund triage example
(Choice, Score and Noul), with no generated output tokens, in about 225 ms.
The installed gateway adapter correctly classified both a billing refund and
an app crash, including true and false Noul outputs.
After registering the persistent runtime and restarting the menu bar app,
`/providers` listed the local profile and `/health` confirmed it was selected.
A request through the shared JEV endpoint passed all three primitive types in
about 1.18 seconds on its first request after startup. These are smoke timings,
not a latency benchmark. Vision weights are installed; image inference and
idle wake-up have not been tested. Native UI inspection timed out; provider
registration and selection were verified through the app's gateway.

Evidence is in `output/liquid-d1/`: native smoke, installed-adapter smoke,
selected-gateway smoke and installation provenance. No app source changes,
commits or remote pushes were required.
