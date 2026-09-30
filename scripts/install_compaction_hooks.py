#!/usr/bin/env python3
"""Install Jev compaction adapters, preserving other hooks and extensions."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import tempfile


def install(codex_home: Path, pi_agent_dir: Path) -> dict:
    root = Path(__file__).resolve().parents[1]
    adapter = root / "integrations/codex/jev_compaction_hook.py"
    command = "python3 " + shlex.quote(str(adapter))
    extension = root / "integrations/pi/jev-compaction.ts"
    link = pi_agent_dir / "extensions/jev-compaction.ts"
    if link.exists() or link.is_symlink():
        if not link.is_symlink() or link.resolve() != extension:
            raise ValueError("Existing Pi extension at target belongs to another installation")
    config_path = codex_home / "hooks.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    hooks = config.setdefault("hooks", {})
    for event, matcher, message in (
        ("PreCompact", "manual|auto", "Selecting context with Jev"),
        ("SessionStart", "^compact$", "Restoring Jev retention evidence"),
    ):
        groups = hooks.setdefault(event, [])
        expected = {"matcher": matcher, "hooks": [{"type": "command", "command": command, "statusMessage": message}]}
        matches = [index for index, group in enumerate(groups) if any(
            handler.get("command") == command for handler in group.get("hooks", [])
        )]
        if matches:
            # Preserve unrelated handlers even if they share our matcher group.
            for index in reversed(matches):
                groups[index]["hooks"] = [h for h in groups[index]["hooks"] if h.get("command") != command]
                if not groups[index]["hooks"]:
                    groups.pop(index)
        groups.append(expected)
    rendered = json.dumps(config, indent=2) + "\n"
    codex_home.mkdir(parents=True, exist_ok=True)
    changed = not config_path.exists() or config_path.read_text() != rendered
    if changed:
        if config_path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            backup = config_path.with_name(f"hooks.json.before-jev-{stamp}")
            backup.write_bytes(config_path.read_bytes())
            backup.chmod(0o600)
        descriptor, temporary = tempfile.mkstemp(dir=codex_home, prefix=".jev-hooks-")
        try:
            with os.fdopen(descriptor, "w") as target:
                target.write(rendered)
            os.replace(temporary, config_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.is_symlink():
        link.symlink_to(extension)
    return {"codex_hooks": str(config_path), "codex_changed": changed, "pi_extension": str(link),
            "activation": "Codex requires exact hook trust review; Pi requires a new session or /reload."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--pi-agent-dir", type=Path, default=Path.home() / ".pi/agent")
    args = parser.parse_args()
    print(json.dumps(install(args.codex_home, args.pi_agent_dir), indent=2))


if __name__ == "__main__":
    main()
