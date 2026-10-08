# OpenAI login test and System One integration

Research checked 8 October 2026. Account access requires completed live inference.

Current owner requirement: native `/v1/decisions` through the System One ChatGPT
connection. A direct live probe with that registration's OAuth access token
returned HTTP 401, `rejected_by_access_enforcement` / `no_matching_rule`.
The same registration successfully listed models and completed a GPT-6-Luna
Responses control request. This proves the current grant is rejected for the
Decisions route; it does not establish that every ChatGPT account or future grant
is unsupported. No API-key fallback was tested or configured. Evidence:
`output/openai-decisions-chatgpt-probe.json`.

Live test passed on 8 October: the owner registered the display name **System
One**. OAuth identity and direct plan permission validated, the public models
endpoint returned seven visible models, and a `gpt-6.1-sol` Responses request
produced the expected greeting and `response.completed`. This proves that
request's account access; it does not establish Decisions endpoint access or
benchmark performance. Six local smoke-tool tests passed, and specialist review
found no blocking issue. No existing provider selection was changed.

The owner selected Luna as the preferred cost-conscious starting point. A second
live Responses smoke test with `gpt-6-luna` also passed with the expected greeting
and `response.completed`. The helper now defaults to that exact model and stops
if it is absent from the account catalog. This is connectivity proof, not a
decision-quality benchmark.

The Responses smoke tool explicitly requests `reasoning: {"effort": "medium"}`
per owner preference. This setting applies to Responses; the documented native
Decisions request schema does not expose a reasoning-effort parameter.

The active profile is now labelled **Open AI - Decision API** and targets native
`/v1/decisions` with `gpt-6-luna` through the existing System One OAuth connection.
The gateway and benchmark runner share the native converter. It has no Responses
or API-key fallback. The owner requested this route remain selected for manual
retesting later in the week. Access remains rejected by the current grant.

The earlier Responses adapter completed all 100 ambiguity questions in 18.144
seconds after its label repair (`output/openai-choice-label-repair.json`). That
historical result is Responses evidence and does not measure native Decisions.

## Two authentication paths

| Path | Endpoint | Credential | Status |
| --- | --- | --- | --- |
| ChatGPT plan inference | `GET /v1/models`, `POST /v1/responses` | SIWC OAuth token with `chatgpt.tokens.use.direct` | Documented for eligible local/open-source apps |
| Native decisions | `POST /v1/decisions`, model `gpt-6-luna` | OpenAI API key in official examples | Public beta; SIWC authorization for this route is not documented |

ChatGPT identity login alone does not authorize inference. A saved Codex token
does not establish a JEV registration or grant. Use a JEV-specific consent flow.
Paid/remote application eligibility needs separate consideration under the
[SIWC overview](https://developers.openai.com/siwc/token-sharing-open-source).

## Repeatable login smoke test

From the repository root, with Python, PyJWT and cryptography installed:

```sh
python3 scripts/openai_chatgpt_smoke.py --login
```

Complete OpenAI login and plan consent in the browser. The helper validates
state, the issued client ID, ID-token signature, issuer, audience, expiry and
nonce before saving credentials in ignored `.secure/openai-chatgpt.json` with
owner-only permissions. A persistent host ID lives beside that record.

It retrieves the live account catalog, selects `gpt-6-luna` by default (or an
explicit `--model` slug), and sends a small greeting request. If the selected
model is unavailable, it stops rather than choosing a more expensive model. Success requires
both matching output and `response.completed`; partial output is insufficient.
It does not change the selected JEV provider. Existing valid JEV credentials can
be retested without `--login`. Expired credentials require another sign-in;
automatic refresh and production account management are outside this smoke tool.

The request follows the [published inference contract](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference):
`store: false`, `stream: true`, full context in an input array. No automatic
API-key fallback is permitted. [Preview restrictions](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
also exclude several normal Responses parameters and hosted tools.

## Fit with JEV's existing model list

The canonical profile store remains `typesafe.json` (see README's System One
API profiles). The installed app-support file is independent of the source
`.secure` file: the installer does not overwrite an existing installed profile.

The native converter sends `input` and ordered named questions to `/v1/decisions`,
validates named answers and distributions, and maps Choice/Score/Predicate results
back to the gateway's Choice/Score/Noul contract. It preserves native confidence
and fractional scores. Refusals and malformed answers fail explicitly. HTTP
errors remain visible without switching routes or retrying automatically.

The installer bundles both adapters, updates the existing `openai-chatgpt-luna`
profile to the native route and preserves other profiles and installed OAuth
credentials. Native Decisions has no reasoning parameter; medium remains a
setting only in the retained Responses smoke tool.

Installed and restarted `/Applications/JEV Menu Bar.app` on 8 October 2026.
The live provider list shows **Open AI - Decision API — gpt-6-luna**, and the
selected gateway reports `native_decisions` through the ChatGPT plan. A live
installed predicate test returned HTTP 401. This verifies route wiring and the
current access rejection, not successful Decisions inference. Code-signature
verification, native adapter tests and gateway/batching checks passed; specialist
review found no blockers.

Sources: [Decisions guide](https://developers.openai.com/api/docs/guides/decisions),
[API schema](https://developers.openai.com/api/reference/resources/decisions/methods/create),
[SIWC registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[SIWC errors](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).
