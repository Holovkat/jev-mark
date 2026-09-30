#!/usr/bin/env python3
"""Advisory native prompt hook. Never changes skills, tools, or permissions."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))


def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def project_levels(cwd):
    """Closest workspace first, bounded by the first repository root."""
    result = []
    for directory in (cwd, *cwd.parents):
        result.append(directory)
        if (directory / '.git').exists():
            break
    return result


def skill_file(path, supplied=None):
    try:
        path = Path(path).expanduser().resolve()
        raw = path.read_bytes()
        text = raw.decode('utf-8')
    except (OSError, UnicodeError):
        return None
    lines = text.splitlines()
    fields = {}
    if lines and lines[0] == '---':
        index = 1
        while index < len(lines) and lines[index] != '---':
            match = re.match(r'^([\w-]+):\s*(.*)$', lines[index])
            index += 1
            if not match:
                continue
            key, value = match.groups()
            if value in ('>', '|', '>-', '|-'):
                parts = []
                while index < len(lines) and (lines[index].startswith((' ', '\t')) or not lines[index]):
                    parts.append(lines[index].strip())
                    index += 1
                value = (' ' if value.startswith('>') else '\n').join(parts).strip()
            fields[key] = value.strip().strip('"\'')
    supplied = supplied or {}
    name = supplied.get('name') or fields.get('name') or path.parent.name
    return {'id': supplied.get('id') or name, 'name': name,
            'description': supplied.get('description') or fields.get('description', ''),
            'path': str(path), 'content_hash': hashlib.sha256(raw).hexdigest()}


def scan_root(root):
    """Follow installed skill symlinks; resolved directories prevent cycles."""
    root = Path(root).expanduser()
    found, visited, files = [], set(), set()
    def walk(directory):
        try:
            resolved = directory.resolve()
            if resolved in visited:
                return
            visited.add(resolved)
            skill = directory / 'SKILL.md'
            if skill.is_file():
                actual = skill.resolve()
                if actual not in files:
                    files.add(actual)
                    found.append(skill)
                return
            for child in sorted(directory.iterdir()):
                if child.name == 'node_modules' or (child.name.startswith('.') and child.name != '.system'):
                    continue
                if child.is_dir():
                    walk(child)
        except (OSError, RuntimeError):
            return
    if root.is_file():
        return [root]
    if root.is_dir():
        walk(root)
    return found


def strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def native_config(harness, cwd):
    roots, disabled = [], set()
    if harness == 'codex':
        try:
            import tomllib
            config = tomllib.loads((Path.home() / '.codex/config.toml').read_text())
        except (ImportError, OSError, ValueError):
            config = {}
        for entry in config.get('skills', {}).get('config', []):
            if isinstance(entry, dict) and entry.get('enabled') is False and isinstance(entry.get('path'), str):
                disabled.add(str(Path(entry['path']).expanduser().resolve()))
    elif harness == 'zcode':
        settings = [Path.home() / '.zcode/cli/config.json']
        settings += [p / '.zcode/config.json' for p in reversed(project_levels(cwd))]
        for path in settings:
            config = read_json(path)
            skills = config.get('skills', {})
            if isinstance(skills, dict):
                for root in strings(skills.get('roots')):
                    candidate = Path(root).expanduser()
                    roots.append(candidate if candidate.is_absolute() else path.parent / candidate)
            overrides = config.get('skillOverrides', {})
            if isinstance(overrides, dict):
                for target, options in overrides.items():
                    if options is False or isinstance(options, dict) and (options.get('enable') is False or options.get('enabled') is False):
                        disabled.add(str(Path(target).expanduser().resolve()))
    return roots, disabled


def enabled_plugin_roots(harness, cwd):
    """Resolve enabled installed plugins only; never scan every cached plugin."""
    home = Path.home()
    roots = []
    if harness == 'claude':
        enabled = {}
        settings = [home / '.claude/settings.json']
        settings += [p / '.claude/settings.json' for p in reversed(project_levels(cwd))]
        settings += [cwd / '.claude/settings.local.json']
        for path in settings:
            enabled.update(read_json(path).get('enabledPlugins', {}))
        installed = read_json(home / '.claude/plugins/installed_plugins.json').get('plugins', {})
        for identity, on in enabled.items():
            if on is not True:
                continue
            for entry in installed.get(identity, []):
                project = entry.get('projectPath')
                if project and Path(project).resolve() not in project_levels(cwd):
                    continue
                if entry.get('installPath'):
                    roots.append((Path(entry['installPath']) / 'skills', identity.split('@')[0]))
    elif harness == 'codex':
        try:
            import tomllib
            config = tomllib.loads((home / '.codex/config.toml').read_text())
        except (ImportError, OSError, ValueError):
            return roots
        for identity, options in config.get('plugins', {}).items():
            if options.get('enabled') is not True or '@' not in identity:
                continue
            name, market = identity.rsplit('@', 1)
            cache = home / '.codex/plugins/cache' / market / name
            if not cache.is_dir():
                continue
            # Only an unambiguous installed cache can be resolved from disk.
            candidates = [p for p in cache.iterdir() if p.is_dir() and (p / 'skills').is_dir()]
            if len(candidates) == 1:
                roots.append((candidates[0] / 'skills', name))
    return roots


def discover_skills(harness, cwd, supplied=None):
    """Return (effective metadata, complete, warnings). Native catalogues win.

    Filesystem discovery is conservative: plugin/CLI overrides cannot be fully
    reconstructed from a prompt hook, so native discovery remains authoritative.
    """
    if supplied is not None:
        skills = [skill_file(s.get('path') or s.get('filePath', ''), s) for s in supplied if isinstance(s, dict)]
        return [s for s in skills if s], all(skills), [] if all(skills) else ['Some native skill files could not be read.']
    home = Path.home()
    levels = project_levels(Path(cwd).resolve())
    if harness == 'codex':
        roots = [home / '.codex/skills', home / '.agents/skills']
        roots += [p / kind / 'skills' for p in levels for kind in ('.agents', '.codex')]
    elif harness == 'claude':
        # Claude project skills override personal skills; plugins are namespaced.
        roots = [p / '.claude/skills' for p in levels] + [home / '.claude/skills']
    elif harness == 'zcode':
        roots = [home / '.zcode/skills', home / '.agents/skills']
        roots += [p / kind / 'skills' for kind in ('.zcode', '.agents') for p in levels]
    else:
        roots = []  # Pi must provide its native loaded catalogue.
    configured, disabled = native_config(harness, Path(cwd).resolve())
    roots = configured + roots
    skills = {}
    for root in roots:
        for path in scan_root(root):
            item = skill_file(path)
            if item and item['path'] not in disabled and str(Path(item['path']).parent) not in disabled:
                skills.setdefault(item['name'], item)
    for root, namespace in enabled_plugin_roots(harness, Path(cwd).resolve()):
        for path in scan_root(root):
            item = skill_file(path)
            if item and item['path'] not in disabled and str(Path(item['path']).parent) not in disabled:
                item['name'] = namespace + ':' + item['name']
                item['id'] = item['name']
                skills.setdefault(item['name'], item)
    return list(skills.values()), False, ['Partial filesystem catalogue; use native discovery for configured roots, enabled plugins, and overrides.']


def build_packet(event, harness):
    cwd = Path(event.get('cwd') or event.get('project') or Path.cwd()).resolve()
    context = event.get('task_context') or event.get('taskContext') or {}
    if not isinstance(context, dict):
        context = {}
    # Optional sidecar is explicit metadata only; never inspect session transcripts.
    if event.get('task_context_path'):
        context = {**read_json(event['task_context_path']), **context}
    supplied = event.get('skills') if isinstance(event.get('skills'), list) else None
    skills, complete, warnings = discover_skills(harness, cwd, supplied)
    prompt = event.get('prompt') or event.get('userPrompt') or event.get('user_prompt') or ''
    request = context.get('request') or prompt
    policy = read_json(cwd / '.jev/capabilities.json')
    required = strings(context.get('required_skills')) + strings(policy.get('required_skills'))
    stage = context.get('stage')
    stages = policy.get('stages', {})
    stage_policy = stages.get(stage, {}) if isinstance(stages, dict) and isinstance(stage, str) else {}
    if isinstance(stage_policy, dict):
        required += strings(stage_policy.get('required_skills'))
    for skill in skills:
        name = re.escape(skill['name'])
        explicit = bool(re.search(r'(?:\$|/skill:|/skill\s+)' + name + r'(?![\w:-])', request))
        skill['explicit'] = explicit
        skill['required'] = explicit or skill['id'] in required or skill['name'] in required
    known = {s['id'] for s in skills} | {s['name'] for s in skills}
    missing = sorted(set(required) - known)
    if missing:
        warnings.append('Required skill unavailable; retain native discovery: ' + ', '.join(missing))
    skills = [s for s in skills if s['name'].split(':')[-1] != 'jev-capabilities' or s['explicit'] or s['required']]
    task = {'request': request}
    for key in ('objective', 'stage', 'unresolved'):
        if key in context:
            task[key] = context[key]
    # Public project instructions only; never copy runtime/system prompt bodies.
    policies = []
    for directory in project_levels(cwd):
        path = directory / 'AGENTS.md'
        try:
            text = path.read_text()
        except (OSError, UnicodeError):
            continue
        heading = ''
        for paragraph in re.split(r'\n\s*\n', text):
            if paragraph.lstrip().startswith('#'):
                heading = paragraph.splitlines()[0]
            if any(re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', paragraph) for name in known):
                policies.append(str(path) + '\n' + heading + '\n' + paragraph)
    if policies:
        task['policy'] = '\n\n'.join(policies)
    tools = []
    for item in event.get('tools', []):
        if isinstance(item, dict) and item.get('name'):
            tools.append({k: item[k] for k in ('id', 'name', 'description', 'available', 'required') if k in item})
            tools[-1].setdefault('id', item['name'])
    return {'version': 1, 'harness': harness,
            'session_id': str(event.get('session_id') or event.get('sessionId') or 'unknown'),
            'project': str(cwd), 'task': task, 'skills': skills, 'tools': tools,
            'catalogue_complete': bool(event.get('catalogue_complete', complete)), 'catalogue_warnings': warnings}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--harness', choices=['codex', 'claude', 'zcode', 'pi'], required=True)
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--base-url', default=os.environ.get('JEV_BASE_URL', 'http://127.0.0.1:8096'))
    parser.add_argument('--catalogue', action='store_true')
    parser.add_argument('--input-file', help='Private adapter-owned prompt packet')
    args = parser.parse_args()
    output = {}
    try:
        event = read_json(args.input_file) if args.input_file else json.load(sys.stdin)
        packet = build_packet(event, args.harness)
        if args.catalogue:
            output = packet
        else:
            from capability_selector import select, render
            timeout = args.timeout or {'claude': 30, 'codex': 180, 'zcode': 60, 'pi': 180}[args.harness]
            if any(w.startswith('Required skill unavailable') for w in packet['catalogue_warnings']):
                context = 'Capability selection: native discovery retained. ' + ' '.join(packet['catalogue_warnings'])
            else:
                state_dir = Path(os.environ.get('JEV_CAPABILITY_STATE_DIR', str(Path.home() / '.local/state/jev-capabilities/cache'))).expanduser()
                state_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                state_dir.mkdir(mode=0o700, exist_ok=True)
                state_dir.chmod(0o700)
                context = render(select(packet, base_url=args.base_url, timeout=timeout, state_dir=state_dir))
            if context:
                output = {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': context}}
    except Exception:
        pass  # Advisory fail-open; stdout must remain one native JSON object.
    print(json.dumps(output))


if __name__ == '__main__':
    main()
