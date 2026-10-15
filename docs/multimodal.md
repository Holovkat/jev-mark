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
- ChatGPT Responses profiles: image references become ordered `input_image`
  content parts alongside the same structured question/answer contract.
- Other System One profiles: opt in with `"image_input": "systemone"` in the
  existing `typesafe.json` profile only when that upstream accepts TypeSafe's
  asset contract. The provider validates actual model support.
- Local llama finite-decision engine, Apple Foundation Models, CLM, native
  OpenAI Decisions, and unconfigured remote adapters: HTTP 422 before inference.
  Text requests continue using their existing path.

`/providers` and `/capabilities` expose `image_input` as `systemone`,
`responses`, or `unsupported`. This describes the adapter; it is not a claim
that every model offered by the upstream is a vision model.

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
[release announcement](https://typesafe.ai/blog/jev-1-14),
[OpenAI vision inputs](https://developers.openai.com/api/docs/guides/images-vision).

## Local evidence — 15 October 2026

- TypeSafe `jev-latest`, direct adapter: red, 299 ms, 760 input / 41 output tokens.
- TypeSafe through the HTTP gateway: red, 280 ms, 763 input / 41 output tokens.
- Browser shape test: red, reference match, 245 ms. Upload and removal verified.
- Browser text-only selection: HTTP 422 with the unsupported-image message.
- Focused checks: 65 Python tests and 34 JavaScript tests passed; Python compile,
  shell syntax and diff whitespace checks passed. Responses image transport was
  covered by a mocked SSE/transport test; no live Responses vision claim.
- Broad Python run: 158 of 159 passed at that point. The failure is the untouched
  Pi native-loader fixture, whose installed `core/extensions/loader.js` path no
  longer exists. No Pi package or loader integration was changed for this feature.

The menu-bar app was subsequently rebuilt and installed with
`scripts/install_menubar.sh`. App signature verification passed; installed
gateway, image module, Responses adapter and Workbench bytes match source.
The restarted gateway on port 8096 serves the Visual tests catalog and image
loader. Existing selection `remote:openrouter-mercury-decide` was preserved;
an image request correctly returned HTTP 422 on that unsupported route.
Select a TypeSafe profile in the menu bar to run the visual test with vision.
These are local installation observations; publishing this repository does not
activate a hosted deployment or establish additional model acceptance.
