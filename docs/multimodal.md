# Shared image decisions

The existing `POST /v1/decision` contract now accepts an optional `assets` map.
Use the same request with any selected provider. The gateway either forwards
image evidence through its image adapter or returns HTTP 422 for unsupported
routes. It never substitutes a different model or converts an image into a
text description.

```json
{
  "contexts": ["Inspect the product photo: 9d13f901-photo"],
  "schema": {
    "damaged": {
      "type": "noul",
      "instructions": "Does the product in the photo have visible damage?"
    }
  },
  "assets": {
    "9d13f901-photo": {
      "type": "image",
      "format": "png",
      "data_base64": "<standard padded base64 of the PNG file>"
    }
  }
}
```

References can appear in contexts, caller instructions, field instructions,
descriptions, or nested Choice/Score/Noul criteria. Object keys and choice
labels are text, not image placements. Use a fresh UUID as each reference.
Only images referenced by a context's actual provider request are forwarded.
Failed-work retry packets retain their relevant assets.

## Routes

- Official TypeSafe `/v1/systemone`: native assets and
  `TypeSafe-Danger-Zone-Images: true`. Jev 1.13 and 1.14 accept images.
- Ollama System One: `"image_input": "ollama"` translates assets to Ollama's
  ordered base64 `images` array. References become numbered image labels in
  context and question values; all supplied images are shared across questions.
  Keys remain text. This differs from TypeSafe's inline image placement. D1 on
  Ollama 0.40.5 passed live checks on 16 October; see the evidence below.
- Other System One profiles: opt in with `"image_input": "systemone"` in the
  existing `typesafe.json` profile only when that upstream accepts TypeSafe's
  asset contract. The provider validates actual model support.
- Local llama finite-decision engine, Apple Foundation Models, CLM, native
  OpenAI Decisions, and unconfigured remote adapters: HTTP 422 before inference.
  Text requests continue using their existing path.

`/providers` and `/capabilities` expose `image_input` as `systemone`,
`ollama`, or `unsupported`. This describes the adapter; it is not a claim
that every model offered by the upstream is a vision model.

## Menu-bar Ollama image option

**Ollama models** in the menu bar opens the **Ollama Decision Models** panel
with Model, Batch and Image Input columns. Enable a downloaded decision model
with its checkbox. The Image Input cell is read-only: the tick shows that the
model is selected and that `POST /api/show` advertises both `decision` and
`vision`; an empty bordered cell means the capability is absent. Newly enabled
compatible models start with images enabled. **Refresh** inside the panel
re-runs discovery and also prunes selections whose model is no longer
downloaded from Ollama. No model-name allowlist or chat/OCR fallback is used.

A model's batch value is always visible; selected models edit it inline with a
stepper, and the footer records `Batch range: 1 - 512 | Ollama default: 64`.

Enabling a vision-capable model stores `image_input: "ollama"` in the same
loopback System One profile in `typesafe.json`. It does not create a second
provider. Direct API callers keep sending the shared `assets` contract to port
8096; the gateway performs the wire translation. Retry packets also retain the
shared asset format.

Ollama's body limit is 64 KiB without images and 32 MiB with images; the shared
gateway's stricter 16 MiB total body cap still applies. Capabilities advertise
both native limits plus the gateway limit. PNG/JPEG remain the common accepted
formats even though Ollama additionally supports WebP.

## Workbench

Open `/workbench`, attach PNG/JPEG files, inspect their thumbnails, and run
Choice, Score, Noul, or parallel decisions using the selected menu-bar provider.
References are appended to context; they can also be copied into instructions
and criteria. Remove detaches an image. Selecting a new case clears previous attachments and loads any fixture belonging
to the new case.
Files remain in page memory until sent. The existing analytics payload-capture
policy still applies to submitted requests.

**Visual tests → Square colour · image** in the test library loads a 320×320
image with a red square and blue circle and asks for the square's colour.
The section is first in the library and opens by default. The known answer is
`red`. It does not send anything until Run decision is pressed.

Gateway limits: JSON only, at most 32 images, 16 MiB total HTTP request body,
16 MiB per decoded image, PNG/JPEG signatures and strict base64. Paths, remote
URLs, multipart parts, audio and video are unsupported. Full image decoding and
provider-specific limits remain the upstream's responsibility. The Workbench
also checks image dimensions against TypeSafe's current limits (256–1568 per
side; at least 78,400 pixels) and never resizes silently. TypeSafe images are
experimental; Box output is outside this change.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_jev_images.py'
node --test tests/image_request.test.mjs
# Direct adapter: replace typesafe-primary with an ID in your source profile store.
# Set TYPESAFE_SECURE_DIR to use another profile directory.
python3 scripts/image_smoke.py --profile typesafe-primary
# Installed gateway: select TypeSafe in the menu bar first.
python3 scripts/image_smoke.py --url http://127.0.0.1:8096
```

The smoke uses a generated image with no private source material and does not
change menu-bar selection or credentials. `--profile` tests an adapter directly;
`--url` exercises the running gateway. A passed smoke demonstrates one synthetic
image decision, not general image accuracy.

Sources: [TypeSafe images](https://docs.typesafe.ai/images),
[release announcement](https://typesafe.ai/blog/jev-1-14).

## Local evidence — 15 October 2026

- TypeSafe `jev-latest`, direct adapter: red, 299 ms, 760 input / 41 output tokens.
- TypeSafe through the HTTP gateway: red, 280 ms, 763 input / 41 output tokens.
- Browser shape test: red, reference match, 245 ms. Upload and removal verified.
- Browser text-only selection: HTTP 422 with the unsupported-image message.
- Focused checks: 65 Python tests and 34 JavaScript tests passed; Python compile,
  shell syntax and diff whitespace checks passed. The former ChatGPT Responses
  adapter was covered by a mocked test at that time and was later removed.
- Broad Python run: 158 of 159 passed at that point. The failure is the untouched
  Pi native-loader fixture, whose installed `core/extensions/loader.js` path no
  longer exists. No Pi package or loader integration was changed for this feature.

The menu-bar app was subsequently rebuilt and installed with
`scripts/install_menubar.sh`. App signature verification passed; installed
gateway, image module, then-existing Responses adapter and Workbench bytes matched source.
The restarted gateway on port 8096 serves the Visual tests catalog and image
loader. Existing selection `remote:openrouter-mercury-decide` was preserved;
an image request correctly returned HTTP 422 on that unsupported route.
Select a TypeSafe profile in the menu bar to run the visual test with vision.
These are local installation observations; publishing this repository does not
activate a hosted deployment or establish additional model acceptance.


## Ollama D1 evidence — 16 October 2026

The installed Ollama is 0.40.5. This morning's `d1:3b` download reports native
decision and vision capabilities. The earlier 0.40.3 encoding rejection in
[Liquid D1 setup](liquid-d1-local.md) is historical.

- Direct native image request returned Choice `red`, Noul about 0.9935, and a
  Score distribution concentrated on one visible circle, with zero output tokens.
- Shared adapter returned `red`; a blue-square counterfactual returned `blue`.
- A two-image request returned `red` for the first square and `blue` for the
  second, retaining reference order. These are synthetic smoke checks, not a
  general visual benchmark.
- Image transport/retry tests, text-only and then-existing Responses checks, and
  Swift profile-store checks cover the new option and unrelated-profile
  preservation. The release build compiles the native toggle and discovery path.

The menu-bar app was rebuilt, installed and restarted with D1 selected and
`Image input (Ollama)` enabled. Installed Python/web resources match source and
app signature verification passed. The browser shape test returned `red` with
a reference match in 423 ms. Through port 8096, two independent image contexts
returned red/blue Choices, true/false Nouls and fractional Scores with modal level
one circle, with zero output tokens. The paired call took 957 ms; a text routing
check returned billing in 90 ms. These timings are smoke observations.

The installed example catalog initially stalled while importing fixtures from
the external source checkout. The installer now bundles its existing fixture
modules and JSON, and the core loads them beside itself. A standalone Python
3.9 check with an unavailable source root loaded all 41 cases; the restarted
installed service and browser loaded them too.

Native UI automation timed out on this Mac. The Swift store tests and release
build verify the toggle's backing behavior and wiring; direct native clicking
was not verified. Only the existing D1 profile's image mode was changed, and
other provider records were checked against the saved configuration backup.

Verification commands include:

```sh
swiftc Sources/JevMenuBar/TypesafeAPI.swift tests/ollama_store.swift -o /tmp/jev-ollama-store-tests
/tmp/jev-ollama-store-tests
```

All 11 image tests, 24 gateway checks, eight remote-batching checks, 25 OpenAI
adapter checks, and three image-request JavaScript checks passed. The catalog
check was rerun after the packaging repair. Live service evidence is retained in
`output/ollama-images/installed-service-smoke.json`.

No existing Liquid D1 runtime or model weights
were removed or replaced.

Ollama sources: [System One API](https://docs.ollama.com/api/systemone),
[D1 model](https://ollama.com/library/d1),
[0.40.5 runner bridge](https://github.com/ollama/ollama/blob/v0.40.5/llm/llama_server_systemone.go).


## Box assessment — 16 October 2026

Status: researched and directly probed; not implemented in the shared gateway or
Workbench. The existing statement that Box is outside the implementation still
applies. Source: [TypeSafe Box contract](https://docs.typesafe.ai/primitives/box).

Box is image localisation: `type: "box"`, instructions naming a target and image,
and no criteria. The native result contains `top`, `bottom`, `left`, `right` in
0–1 coordinates plus confidence. Strict edge ordering is required. It needs Jev
1.14 (`jev-1.14.0` or `jev-preview`) and the images opt-in header; an older Jev
alias is not sufficient evidence of support. TypeSafe labels the contract and
accuracy experimental.

A Box always returns coordinates, including when the target is absent. Pair it
with a Noul presence question and apply a caller-owned presence policy before
using the location. Confidence alone is not an existence guarantee. Multiple
targets require separate questions; ambiguous duplicates need disambiguation.

Direct native probes using the existing generated shape fixture:

- Jev 1.14 returned a presence probability of 0.98 and a red-square box with
  confidence 0.93. Intersection-over-union with the known square was 0.9118;
  observed latency was 284 ms. This is one synthetic localisation result.
- Ollama 0.40.5 / D1 rejected `box` with HTTP 400, listing only Choice, Score and
  Noul as accepted types. Native image support does not imply native Box output.
- Full non-sensitive results: `output/box-assessment/native-probes.json`.
  Provider configuration, selection and installed app were not changed by these
  probes.

Implemented shared Box support:

- Submit `{"type":"box","image_ref":"<asset reference>","instructions":"Locate ..."}` in
  the shared schema. Box has no criteria. A single image binds automatically;
  multiple images require an explicit `image_ref`. The response preserves the
  normalized rectangle, confidence and image reference; it does not invent
  categorical probabilities.
- Enabled image routes forward Box without a model allowlist. The upstream
  accepts or rejects the type. Ollama D1 currently returns an explicit native
  unsupported-type error. Text-only routes retain their image-unsupported error.
- Coordinates and confidence are strictly validated. Invalid fields preserve
  successful sibling fields and the existing bounded retry contract.
- **Visual tests → Locate the square · Box** pairs Box with Noul presence, draws
  the returned rectangle and known reference, and reports intersection-over-union.
  Its demonstration policy requires Noul presence >= 0.5 before drawing a location;
  this is a caller policy, not a recommended universal threshold. Missing or absent
  presence hides the overlay while preserving the returned data.
- Analytics recognizes Box requests. Total fields includes Box; the existing
  Choice/Score/Noul per-type counters retain their original meanings.

The earlier native probes above were assessment-only. The subsequent installed
app includes the implementation and a separate TypeSafe Jev 1.14 model profile.

Installed Workbench verification: **Locate the square · Box** on Jev 1.14 returned
presence 1.0, valid coordinates with confidence 0.86, and IoU 0.824 in 291 ms.
The provider and reference rectangles both rendered. Native coordinates remain
experimental; the earlier direct probe had a different overlap. Focused tests
also cover missing/ambiguous image bindings, malformed geometry and confidence,
partial sibling preservation and explicit Ollama rejection. The installed D1 route was exercised separately and retained HTTP
400 for Box with no model substitution.
