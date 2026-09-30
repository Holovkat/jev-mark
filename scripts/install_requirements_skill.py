#!/usr/bin/env python3
"""Link the canonical requirements skill into Codex and Pi, preserving originals."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re


def install(codex_home: Path, pi_agent_dir: Path) -> dict:
    source = Path(__file__).resolve().parents[1] / 'integrations/skills/requirements-traceability'
    if not (source / 'SKILL.md').is_file():
        raise ValueError('Canonical requirements-traceability SKILL.md is missing')
    targets = [codex_home / 'skills/requirements-traceability',
               pi_agent_dir / 'skills/requirements-traceability']
    # Validate both destinations before making any change.
    for target in targets:
        if target.is_symlink():
            if target.resolve() != source.resolve():
                raise ValueError(f'Refusing unrelated skill symlink: {target}')
        elif target.exists():
            entry = target / 'SKILL.md'
            if not target.is_dir() or not entry.is_file():
                raise ValueError(f'Refusing unrelated skill collision: {target}')
            text = entry.read_text()
            frontmatter = text.split('---', 2)
            if len(frontmatter) < 3 or not re.search(
                r'^name:\s*requirements-traceability\s*$', frontmatter[1], re.M
            ):
                raise ValueError(f'Refusing unrelated skill collision: {target}')
    changes = []
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    for target in targets:
        backup = None
        changed = not target.is_symlink()
        if changed:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                # Backup outside skills discovery, preserving the entire directory.
                backup = target.parent.parent / 'skill-backups' / f'{target.name}.before-jev-{stamp}'
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
            target.symlink_to(source, target_is_directory=True)
        changes.append({'path': str(target), 'changed': changed,
                        'backup': str(backup) if backup else None})
    return {'canonical': str(source), 'installations': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path.home() / '.codex')
    parser.add_argument('--pi-agent-dir', type=Path, default=Path.home() / '.pi/agent')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.codex_home.expanduser(), args.pi_agent_dir.expanduser()), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
