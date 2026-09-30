# Service analytics

The observed gateway adds a **Service analytics** link to the portal and Workbench.
After reinstalling the menu-bar app, open `http://127.0.0.1:8096/analytics` on the service Mac.
The original decision adapters and the Swift launcher are unchanged.

## Installation

After reviewing and merging this feature, update the local repository and run:

```bash
./scripts/install_menubar.sh
```

For source-tree development, stop the other gateway before running:

```bash
python3 scripts/jev_service.py
```

Only one process may listen on port 8096. Running `scripts/jev_gateway.py` directly
still starts the original, unobserved gateway. Use `jev_service.py` for analytics.
The installer preserves the launcher's existing bundled filename:

| Repository source | Installed resource |
| --- | --- |
| `scripts/jev_service.py` | `jev_gateway.py`, observed entry point |
| `scripts/jev_gateway.py` | `jev_gateway_core.py`, unchanged adapters |
| `scripts/jev_analytics.py` | `jev_analytics.py` |
| `Resources/Web/analytics.html` | `web/analytics.html` |
| `Resources/Web/analytics-portal.js` | `web/analytics-portal.js` |

Portal navigation is added while serving HTML. The original large portal and
Workbench HTML files are not rewritten. Static `file://` copies are not decorated.

## Metric definitions

**Incoming requests** count `POST /v1/decision` calls through this observed gateway,
including rejected or invalid requests. Calls directly to a provider bypass this
collection. GET requests, health checks, page loads, analytics polling and unrelated
POST routes do not inflate decision-call totals.

**Provider attempts** count explicit outbound POST dispatches initiated by gateway
adapters. Failed connections and HTTP errors are attempts. This is not a count of
transport redirects/retries or internal CLM encoder, Apple, or hosted-model
operations. Shared remote workers and temporary CLM workers retain the incoming
request's correlation context. A retry submitted by a client is a new incoming
request; an optional operation ID can link calls in the same run.

**Decision fields** are submitted schema fields multiplied by submitted contexts.
The page also counts returned requested fields. Choice/enum and Noul/bool/boolean
aliases are normalized; mixed requests are counted once, not once per field type.
Submitted workload metadata does not assert that a schema was valid. Missing
completion or token measurements stay unknown rather than becoming invented zeroes.

Outcomes are complete, partial, rejected, failed, disconnected, interrupted,
unknown and in progress. Successful fields in a non-2xx partial response remain
counted. A success response without measurable completion is marked unknown.
A disconnect is distinct from whether the provider finished work.

Latency measures gateway elapsed time, including reading the body and writing the
response. Median and p95 use linear interpolation over finished recorded requests,
including errors. In-progress/interrupted requests have no fabricated duration.
Provider-attempt timing is separate; HTTP-error timing ends when the HTTP error is
raised, before the adapter reads its error body. Input/output tokens are recorded
only when the gateway response supplies non-negative integers. Totals cover
reported usage only and are not billing totals.

Each observed response includes `X-JEV-Request-ID`. Decision JSON is unchanged.

## Caller attribution

The gateway-served Workbench automatically adds caller and purpose labels. Other
clients may supply:

```http
X-JEV-Client: integration-agent
X-JEV-Purpose: classification
X-JEV-Operation-ID: run-20260930-001
```

Use non-sensitive labels, not prompts, names, addresses or credentials. Allowed
values are 1-96 ASCII characters, beginning with a letter or digit, then letters,
digits, underscore, dot, colon, slash or hyphen. Missing/invalid caller and purpose
labels become `unknown`; missing operation IDs remain null. Caller labels are
self-reported, not authenticated identities. Explicit Workbench labels are retained.

## Access and privacy

Without a configured analytics token, the API requires a loopback peer and a
loopback/localhost Host on the service port. Recognized forwarding headers,
cross-site fetches and foreign Origins are rejected. LAN clients may load the
static page but cannot read history. Existing decision-endpoint access is unchanged.

For remote access, prefer an SSH tunnel. Alternatively set a strong random
`JEV_ANALYTICS_TOKEN` of 32-256 ASCII characters in the actual gateway process and
use an HTTPS-protected connection. Once configured, all analytics API access,
including localhost, requires `Authorization: Bearer <token>`. An invalid non-empty
token fails closed. The Unlock form keeps the token only in page memory, never
URLs, browser storage or exports. Do not send tokens over untrusted plain HTTP.

A proxy can conceal its remote peer. Configure token protection before exposing
analytics through a proxy; do not publish an unauthenticated localhost proxy.
Exporting a variable in an unrelated terminal does not reconfigure an already
running menu-bar app. The environment must reach the app's gateway process.

No context text, instructions, schema field names, choice values, answers, request
or response bodies, authorization headers, provider URLs, client IP addresses, or
raw error messages are persisted. Errors use fixed categories. Explicit caller,
purpose, operation, backend and model labels are retained. The database has mode
0600 and a newly created dedicated analytics directory has mode 0700. Custom parent
permissions are not altered. Responses are no-store, have anti-framing/MIME-sniffing
headers, and exports formula-escape text.

## Persistence and limits

Default database:

```text
~/Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3
```

| Environment variable | Default |
| --- | --- |
| `JEV_ANALYTICS_ENABLED` | `1`; use `0` to disable recording |
| `JEV_ANALYTICS_DB` | Local path above |
| `JEV_ANALYTICS_RETENTION_DAYS` | `30`; range 1-365 |
| `JEV_ANALYTICS_MAX_ROWS` | `100000`; range 1-1000000 |
| `JEV_ANALYTICS_TOKEN` | Unset, meaning localhost-only API |

Use a local filesystem, not a network-mounted SQLite database. One writer owns a
WAL connection and a bounded queue of 4096 updates. A file lock prevents multiple
recorder processes sharing the database. Request start and finish updates are
queued. Attempt details are persisted with the finish record, capped at 256 per
request; total attempts and omitted-detail counts remain visible.

Retention runs at startup and approximately every minute. The row cap applies to
finished requests; active rows are not evicted by normal retention. Collection
start, retained coverage, queued/dropped updates and last completed call are
visible. Recorded starts without finishes become interrupted after restart.

This is best-effort operational telemetry, not a durable billing or audit ledger.
Queue saturation, storage failures, hard termination or power loss can cause gaps.
Service calls continue when recording fails. An unflushed loss counter can itself
be lost on a hard kill. WAL uses synchronous NORMAL, so recent committed updates
can be lost on power failure. Calls before collection began are not reconstructed.

## Portal and API

The portal provides Today, last 7/30 days and custom ranges, exact caller/purpose/
backend/model/type/outcome/operation-ID/request-ID filters, top-20 breakdowns,
request details, pagination and CSV export. Boundary time buckets can be partial.
Hourly labels use local time; daily boundaries use UTC. Pre-collection/retention
coverage is not plotted as observed zero traffic. Refresh pauses while hidden,
while details are open, and beyond the first page.

```text
GET /analytics
GET /api/analytics/health
GET /api/analytics
GET /api/analytics/export.csv
```

All API routes above are protected, including health and export. `from` and `to`
use explicit-timezone ISO timestamps and the interval `[from,to)`, limited to 90
days. `limit` is 1-200, default 50. `snapshot` pins the maximum sequence so new
arrivals do not shift a page. Ongoing requests can still finish and retention can
remove rows. Each response uses one read transaction. Exports exceeding 10,000
matching rows are rejected with a request to narrow filters, not silently truncated.

## Verification

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.mjs
bash -n scripts/install_menubar.sh
```

New tests cover storage, privacy, exact summaries, concurrency, retention, restart,
access control, partial responses, metadata failure isolation, Workbench headers
and the original gateway handler integration. Provider responses are deterministic
test doubles; tests do not call real models. CI also runs the existing regression
suites. Browser render checks use synthetic API fixtures, not user traffic.

On the service Mac, reinstall and make one Workbench request plus one labelled
external request. Verify both appear, exercise a validation error, restart and
confirm persistence, then check uncredentialed LAN access is denied. Mac app
installation and live-provider acceptance must be verified on the actual machine.
To roll back, reinstall the previous app revision. The database is outside the app
bundle and is not deleted by reinstalling or rolling back.
