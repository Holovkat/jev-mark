#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir="${JEV_APP_DIR:-/Applications/JEV Menu Bar.app}"
build_dir="$root_dir/.build/release"

swift build -c release --package-path "$root_dir"

if pgrep -f "$app_dir/Contents/MacOS/JevMenuBar" >/dev/null 2>&1; then
  if ! /usr/bin/osascript -e 'tell application id "com.codex.jev.menubar" to quit' >/dev/null 2>&1; then
    echo "Could not quit JEV Menu Bar; refusing to replace the running app." >&2
    exit 1
  fi
  for _ in {1..40}; do
    if ! pgrep -f "$app_dir/Contents/MacOS/JevMenuBar" >/dev/null 2>&1; then break; fi
    sleep 0.25
  done
  if pgrep -f "$app_dir/Contents/MacOS/JevMenuBar" >/dev/null 2>&1; then
    echo "JEV Menu Bar did not stop cleanly; refusing to replace the running app." >&2
    exit 1
  fi
fi

mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Resources/web"
cp "$build_dir/JevMenuBar" "$app_dir/Contents/MacOS/JevMenuBar"
cp "$root_dir/Resources/Info.plist" "$app_dir/Contents/Info.plist"
cp "$root_dir/Resources/AppIcon.icns" "$app_dir/Contents/Resources/AppIcon.icns"
# Keep Swift's launch path stable, with the unchanged decision module alongside it.
cp "$root_dir/scripts/jev_gateway.py" "$app_dir/Contents/Resources/jev_gateway_core.py"
cp "$root_dir/scripts/openai_chatgpt_provider.py" "$app_dir/Contents/Resources/openai_chatgpt_provider.py"
cp "$root_dir/scripts/openai_decisions_provider.py" "$app_dir/Contents/Resources/openai_decisions_provider.py"
cp "$root_dir/scripts/jev_service.py" "$app_dir/Contents/Resources/jev_gateway.py"
cp "$root_dir/scripts/jev_analytics.py" "$app_dir/Contents/Resources/jev_analytics.py"
cp "$root_dir/Resources/Web/analytics.html" "$app_dir/Contents/Resources/web/analytics.html"
cp "$root_dir/Resources/Web/analytics-portal.js" "$app_dir/Contents/Resources/web/analytics-portal.js"
cp "$root_dir/Resources/Web/index.html" "$app_dir/Contents/Resources/web/index.html"
if [[ -f "$root_dir/landing.html" ]]; then
  cp "$root_dir/landing.html" "$app_dir/Contents/Resources/web/landing.html"
fi
chmod +x "$app_dir/Contents/MacOS/JevMenuBar"

secure_source="$root_dir/.secure"
secure_target="$HOME/Library/Application Support/JEV Menu Bar/.secure"
if [[ -d "$secure_source" ]]; then
  mkdir -p "$secure_target"
  chmod 700 "$secure_target"
  for name in typesafe.json openai-chatgpt.json openai-host.json; do
    source_file="$secure_source/$name"
    target_file="$secure_target/$name"
    if [[ -f "$source_file" && ! -e "$target_file" ]]; then
      install -m 600 "$source_file" "$target_file"
    fi
  done
fi

# Register the plan-backed provider alongside existing profiles. Never replace
# an installed OAuth session: its refresh token may have rotated independently.
python3 - "$secure_target" <<'PY'
import json, os, pathlib, tempfile
import sys
directory = pathlib.Path(sys.argv[1])
if (directory / 'openai-chatgpt.json').is_file():
    path = directory / 'typesafe.json'
    if path.is_symlink() or directory.is_symlink():
        raise SystemExit('Refusing symlink provider configuration')
    root = json.loads(path.read_text()) if path.exists() else {'configs': []}
    rows = root.get('configs') if isinstance(root, dict) else root
    if not isinstance(rows, list):
        raise SystemExit('System One configuration must contain a profile array')
    entry = {'id': 'openai-chatgpt-luna', 'name': 'Open AI - Decision API',
             'protocol': 'openai_chatgpt', 'base_url': 'https://api.openai.com/v1/decisions',
             'model': 'gpt-6-luna',
             'workbench_question_batch_size': 16}
    matches = [i for i, row in enumerate(rows) if isinstance(row, dict) and row.get('id') == entry['id']]
    if len(matches) > 1:
        raise SystemExit('Duplicate ChatGPT provider IDs')
    if matches:
        rows[matches[0]].update(entry)
        rows[matches[0]].pop('reasoning_effort', None)
    else:
        rows.append(entry)
    if isinstance(root, dict):
        root['configs'] = rows
    fd, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(root, stream, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
PY

# Swift owns selection in UserDefaults and projects it to gateway settings.
if [[ "${JEV_INSTALL_SELECTED_BACKEND:-}" == "remote:openai-chatgpt-luna" && -f "$secure_target/openai-chatgpt.json" ]]; then
  /usr/bin/defaults write com.codex.jev.menubar selectedBackend -string remote:openai-chatgpt-luna
fi

/usr/bin/codesign --force --deep --sign - --identifier "com.codex.jev.menubar" "$app_dir"

login_agent="$HOME/Library/LaunchAgents/com.codex.jev.menubar.plist"
if [[ -f "$login_agent" ]]; then
  account_uid="$(id -u)"
  launchctl bootout "gui/$account_uid" "$login_agent" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$account_uid" "$login_agent"
  for _ in {1..40}; do
    if pgrep -f "$app_dir/Contents/MacOS/JevMenuBar" >/dev/null 2>&1; then break; fi
    sleep 0.25
  done
  if ! pgrep -f "$app_dir/Contents/MacOS/JevMenuBar" >/dev/null 2>&1; then
    echo "JEV Menu Bar login agent did not start the app." >&2
    exit 1
  fi
else
  open "$app_dir"
fi

echo "Installed: $app_dir"
echo "Service analytics: http://127.0.0.1:8096/analytics"
