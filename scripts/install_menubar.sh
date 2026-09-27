#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_dir="${JEV_APP_DIR:-$HOME/Applications/JEV Menu Bar.app}"
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
cp "$root_dir/scripts/jev_gateway.py" "$app_dir/Contents/Resources/jev_gateway.py"
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
  for name in typesafe.json typesafe-config.json typesafe.env env.dev .env; do
    source_file="$secure_source/$name"
    target_file="$secure_target/$name"
    if [[ -f "$source_file" && ! -e "$target_file" ]]; then
      install -m 600 "$source_file" "$target_file"
    fi
  done
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
