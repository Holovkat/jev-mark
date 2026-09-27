#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_path="${JEV_MODEL_PATH:-/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/blobs/sha256-1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606}"
mmproj_path="${JEV_MMPROJ_PATH:-/Volumes/Extreme SSD/3 Resources/LLLM/Ollama/blobs/sha256-675ad6e68101ca9413ec806855c452362f0213f2dfc5800996b086fdb8119842}"
port="${JEV_PORT:-8097}"
decision_seqs="${JEV_DECISION_SEQS:-12}"
ctx_size="${JEV_CTX_SIZE:-8192}"

[[ -f "$model_path" ]] || { echo "Model not found: $model_path" >&2; exit 1; }
[[ -x "$root_dir/build/bin/llama-server" ]] || { echo "Build first: $root_dir/build/bin/llama-server" >&2; exit 1; }

args=(
  -m "$model_path"
  -ngl 99
  -c "$ctx_size"
  -b 512
  -ub 512
  --decision-seqs "$decision_seqs"
  --port "$port"
  --host 127.0.0.1
)
if [[ -f "$mmproj_path" ]]; then
  args+=(--mmproj "$mmproj_path")
fi

exec "$root_dir/build/bin/llama-server" "${args[@]}"
