#!/usr/bin/env python3
"""Install advisory Jev skill selection across local Codex, Claude, Pi and ZCode."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile


def owned(handler, adapter, harness):
    if handler.get('type') == 'process':
        args = handler.get('args', [])
    elif handler.get('type') == 'command':
        try:
            args = shlex.split(handler.get('command', ''))
        except ValueError:
            return False
    else:
        return False
    return str(adapter) in args and '--harness' in args and harness in args


def upsert(groups, handler, adapter, harness):
    retained = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
            raise ValueError('Invalid existing hook group')
        if any(not isinstance(h, dict) for h in group['hooks']):
            raise ValueError('Invalid existing hook handler')
        remaining = [h for h in group['hooks'] if not owned(h, adapter, harness)]
        if remaining:
            retained.append({**group, 'hooks': remaining})
    return [*retained, {'hooks': [handler]}]


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.jev-selector-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install(home=None, repository_root=None):
    home = Path(home or Path.home()).expanduser().resolve()
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    adapter = root / 'integrations/capabilities/hook.py'
    extension = root / 'integrations/pi/jev-capabilities.ts'
    skill = root / 'integrations/skills/jev-capabilities'
    for source in (adapter, extension, skill / 'SKILL.md'):
        if not source.is_file():
            raise ValueError(f'Integration source is missing: {source}')
    configs, links = [], []
    for harness, relative in [('codex', '.codex/hooks.json'), ('claude', '.claude/settings.json'),
                              ('zcode', '.zcode/cli/config.json')]:
        path = home / relative
        if path.is_symlink():
            raise ValueError(f'Refusing symlinked configuration: {path}')
        original = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(original, dict):
            raise ValueError(f'Configuration must be an object: {path}')
        updated = deepcopy(original)
        hooks = updated.setdefault('hooks', {})
        if not isinstance(hooks, dict):
            raise ValueError(f'Hook configuration must be an object: {path}')
        if harness == 'zcode':
            events = hooks.setdefault('events', {})
            hooks['enabled'] = True
            handler = {'type': 'process', 'command': sys.executable,
                       'args': [str(adapter), '--harness', harness]}
        else:
            events = hooks
            handler = {'type': 'command', 'command': shlex.join([sys.executable, str(adapter), '--harness', harness])}
        if not isinstance(events, dict) or not isinstance(events.get('UserPromptSubmit', []), list):
            raise ValueError(f'Hook events must be an object of arrays: {path}')
        events['UserPromptSubmit'] = upsert(events.get('UserPromptSubmit', []), handler, adapter, harness)
        configs.append((path, original, updated))
    for relative in ('.codex/skills', '.claude/skills', '.pi/agent/skills', '.zcode/skills'):
        links.append((home / relative / 'jev-capabilities', skill))
    links.append((home / '.pi/agent/extensions/jev-capabilities.ts', extension))
    # Validate every destination before mutating any of the four harnesses.
    for path, source in links:
        if path.is_symlink():
            if path.resolve() != source.resolve():
                raise ValueError(f'Refusing unrelated integration symlink: {path}')
        elif path.exists():
            raise ValueError(f'Refusing existing integration collision: {path}')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    changes = []
    for path, original, updated in configs:
        changed = original != updated or not path.exists()
        backup = None
        if changed:
            if path.exists():
                backup = home / path.relative_to(home).parts[0] / 'config-backups' / f'{path.name}.before-jev-selector-{stamp}'
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
                backup.chmod(0o600)
            private_write(path, updated)
        changes.append({'path': str(path), 'changed': changed,
                        'backup': str(backup) if backup else None})
    for path, source in links:
        changed = not path.is_symlink()
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(source, target_is_directory=source.is_dir())
        changes.append({'path': str(path), 'changed': changed})
    return {'installations': changes,
            'activation': {'codex': 'Review/trust UserPromptSubmit through native /hooks; start a new session.',
                           'claude': 'Reload hooks or start a new session.',
                           'pi': 'Use /reload or start a new session.',
                           'zcode': 'Start a new session.'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.home), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
