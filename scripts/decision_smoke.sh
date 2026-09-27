#!/usr/bin/env bash
set -euo pipefail

base_url="${JEV_BASE_URL:-http://127.0.0.1:8096}"
payload='{
  "instructions":"Classify each support request. Use only the supplied choices.",
  "schema":{
    "category":{"type":"enum","choices":["billing","technical","cancellation","other"],"description":"What type of request is this?"},
    "urgent":{"type":"boolean","description":"Does this need urgent handling?"},
    "priority":{"type":"enum","choices":["low","medium","high","critical"],"description":"Rate the priority."}
  },
  "contexts":[
    "I was charged twice and need this fixed today.",
    "The mobile app crashes whenever I open the settings screen.",
    "Please close my account at the end of the billing period."
  ]
}'

curl --fail-with-body -sS "$base_url/health"
echo
curl --fail-with-body -sS "$base_url/v1/decision" \
  -H 'Content-Type: application/json' \
  -d "$payload"
echo
