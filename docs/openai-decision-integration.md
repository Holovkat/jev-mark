# OpenAI Decisions API integration

JEV uses OpenAI's native `/v1/decisions` endpoint with an explicitly configured
project API key. The installed profile is **OpenAI Decisions API (API credits)
— gpt-6-luna** under **System One API**. The gateway and benchmark service share
the native converter for Choice, Score and Noul; no credential or inference
fallback is used. Native Decisions image inputs are not supported by this JEV
adapter and return HTTP 422 before inference.

## API credits and configuration

OpenAI's [API credits guide](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
includes Decisions. Credits belong to the linked API organization, so use a
project key from that organization. The verified profile uses the credited
organization and project configured by the owner. Organization and project IDs
are supplied as explicit request headers; they may be omitted when the project
key identifies the correct organization and project.

All provider profiles use the existing owner-only
`~/Library/Application Support/JEV Menu Bar/.secure/typesafe.json` file. A
separate project-key profile has this shape:

```json
{
  "id": "openai-decisions-api",
  "name": "OpenAI Decisions API (API credits)",
  "protocol": "openai_decisions",
  "base_url": "https://api.openai.com/v1/decisions",
  "model": "gpt-6-luna",
  "api_key": "<project API key>",
  "organization_id": "<optional organization ID>",
  "project_id": "<optional project ID>"
}
```

Keep credentials out of source control and maintain owner-only permissions.
Refresh providers after changing the profile. The installer preserves an
existing app-support profile file and does not copy over configured keys.

## Verification — 30 October 2026

A live source-gateway request using the credited organization and project
returned HTTP 200 with Choice, Noul and Score answers (`billing`, `true`, and
`1.0`). It reported 536 input tokens and zero output tokens. The installed
gateway listed the API-key profile and a one-case ANLI benchmark through the
running service completed without failed or unsupported cases.
The owner subsequently tested the profile and reported that it looked good.
These checks establish connectivity and the exercised contract, not general
model accuracy.

The earlier ChatGPT sign-in route was retired at the owner's request. Its
historical native Decisions test returned HTTP 401; that result does not apply
to the successful project-key route above. On 30 October 2026, the owner also
requested removal of its cached login, host identity and lock files from the
source checkout and installed app-support directory.
After removal, the rebuilt installed app retained the selected API-key profile,
the retired profile and adapter were absent, and an HTTP request through the
running `/v1/decision` endpoint returned complete OpenAI API answers (`billing`
and `true`), HTTP 200.

Sources: [Decisions guide](https://developers.openai.com/api/docs/guides/decisions),
[Decisions API reference](https://developers.openai.com/api/reference/resources/decisions/methods/create),
[OpenAI API authentication](https://developers.openai.com/api/reference/overview#authentication).
