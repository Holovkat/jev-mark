#!/usr/bin/env python3
"""Install repository-owned Jev hooks and shared skills into ZCode."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

EVENTS = ('SessionStart', 'PreToolUse', 'PostToolUse', 'Stop')


def install(zcode_home: Path, codex_home: Path = None, repository_root: Path = None) -> dict:
    root = (repository_root or Path(__file__).resolve().parents[1]).resolve()
    codex_home = codex_home or Path.home() / '.codex'
    adapter = root / 'integrations/zcode/jev_hook.py'
    sources = {name: root / 'integrations/skills' / name for name in ('requirements-traceability', 'jev-retention')}
    sources['jev-decision'] = codex_home / 'skills/jev-decision'
    if not adapter.is_file():
        raise ValueError('ZCode adapter is missing')
    for name, source in sources.items():
        if not (source / 'SKILL.md').is_file():
            raise ValueError(f'Canonical {name} SKILL.md is missing')
        target = zcode_home / 'skills' / name
        if target.is_symlink():
            if target.resolve() != source.resolve():
                raise ValueError(f'Refusing unrelated skill symlink: {target}')
        elif target.exists():
            entry = target / 'SKILL.md'
            if not target.is_dir() or not entry.is_file():
                raise ValueError(f'Refusing unrelated skill collision: {target}')
            parts = entry.read_text().split('---', 2)
            if len(parts) < 3 or not re.search(r'^name:\s*' + re.escape(name) + r'\s*$', parts[1], re.M):
                raise ValueError(f'Refusing unrelated skill collision: {target}')
    config_path = zcode_home / 'cli/config.json'
    if config_path.is_symlink():
        raise ValueError('Refusing symlinked ZCode config')
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError('ZCode config must be an object')
    updated = deepcopy(config)
    hooks = updated.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('ZCode hooks must be an object')
    events = hooks.setdefault('events', {})
    if not isinstance(events, dict):
        raise ValueError('ZCode hook events must be an object')
    for event, groups in events.items():
        if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks'), list) or any(not isinstance(h, dict) for h in g['hooks']) for g in groups):
            raise ValueError(f'Invalid ZCode hook groups: {event}')
    hooks['enabled'] = True
    for event in EVENTS:
        groups = events.setdefault(event, [])
        retained = []
        for group in groups:
            remaining = [h for h in group['hooks'] if not (h.get('type') == 'process' and
                         isinstance(h.get('args'), list) and h['args'][:1] == [str(adapter)])]
            if remaining:
                retained.append({**group, 'hooks': remaining})
        retained.append({'hooks': [{'type': 'process', 'command': sys.executable, 'args': [str(adapter), '--event', event]}]})
        events[event] = retained
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    changes = []
    for name, source in sources.items():
        target = zcode_home / 'skills' / name
        backup = None
        if not target.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = zcode_home / 'skill-backups' / f'{name}.before-jev-{stamp}'
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
            target.symlink_to(source.resolve(), target_is_directory=True)
            changes.append({'path': str(target), 'backup': str(backup) if backup else None})
    backup = None
    if updated != config or not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            backup = zcode_home / 'config-backups' / f'config.before-jev-{stamp}.json'
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_path, backup)
            backup.chmod(0o600)
        with tempfile.NamedTemporaryFile(mode='w', dir=config_path.parent, prefix='.jev-config-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(updated, indent=2) + '\n')
        try:
            temporary.chmod(0o600)
            temporary.replace(config_path)
        finally:
            temporary.unlink(missing_ok=True)
    config_path.chmod(0o600)
    return {'config': str(config_path), 'config_changed': updated != config,
            'config_backup': str(backup) if backup else None, 'skills_changed': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zcode-home', type=Path, default=Path.home() / '.zcode')
    parser.add_argument('--codex-home', type=Path, default=Path.home() / '.codex')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.zcode_home.expanduser(), args.codex_home.expanduser()), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
