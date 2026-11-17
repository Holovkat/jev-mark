"""Local, advisory skill selections shared by the prompt hook and skills-help."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def project_root(path):
    path = Path(path).expanduser().resolve()
    return next((p for p in (path, *path.parents) if (p / '.git').exists()), path)


def selection_path(project, harness, session_id=None, scope='session'):
    project = project_root(project)
    if scope == 'project':
        return project / '.jev/skill-selection.json'
    if not session_id or session_id == 'unknown':
        raise ValueError('Session selection needs a native session ID; use --session-id or --scope project.')
    identity = json.dumps([str(project), harness, session_id], separators=(',', ':'))
    key = hashlib.sha256(identity.encode()).hexdigest()
    root = Path(os.environ.get('JEV_SKILL_SELECTION_DIR', '~/.local/state/jev-capabilities/skill-selections')).expanduser()
    return root / (key + '.json')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_selection(project, harness, session_id):
    paths = [selection_path(project, harness, scope='project')]
    if session_id and session_id != 'unknown':
        paths.insert(0, selection_path(project, harness, session_id))
    for path in paths:
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or value.get('version') != 1 or value.get('mode') not in ('soft', 'open'):
                raise ValueError('Invalid selection')
            if value['mode'] == 'soft':
                rows = value.get('skills')
                if not isinstance(rows, list) or not rows or any(
                    not isinstance(r, dict) or not isinstance(r.get('name'), str) or not isinstance(r.get('path'), str)
                    for r in rows
                ):
                    raise ValueError('Invalid selected skills')
            return {**value, 'source': str(path)}
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return {'mode': 'invalid', 'source': str(path)}
    return {'mode': 'open'}


def apply_selection(packet):
    """Narrow advisory candidates, retaining explicit/required/dependency closure."""
    preference = load_selection(packet['project'], packet['harness'], packet['session_id'])
    mode = preference['mode']
    if mode == 'open':
        packet['skill_selection'] = {'mode': 'open'}
        return packet
    skills = packet['skills']
    known = {r['id']: r for r in skills}
    selected = set()
    if mode == 'soft':
        for saved in preference['skills']:
            matches = [r for r in skills if r['name'] == saved['name'] and r['path'] == saved['path']]
            if not matches:
                mode = 'stale'
                break
            selected.update(r['id'] for r in matches)
    if mode != 'soft':
        packet['skill_selection'] = {'mode': mode}
        return packet
    selected.update(r['id'] for r in skills if r.get('required') or r.get('explicit'))
    pending = list(selected)
    while pending:
        for dependency in known[pending.pop()].get('dependencies', []):
            if dependency not in known:
                packet['skill_selection'] = {'mode': 'missing_dependency'}
                return packet
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    packet['skills'] = [r for r in skills if r['id'] in selected]
    packet['skill_selection'] = {'mode': 'soft', 'names': [r['name'] for r in packet['skills']]}
    return packet


def selection_context(packet):
    state = packet.get('skill_selection', {})
    if state.get('mode') == 'soft':
        names = ', '.join(json.dumps(n) for n in state['names'])
        return ('Skill soft selection: ' + names + '. Load only the selected guidance needed for this task. '
                'Explicit owner requests and mandatory native/project guidance take precedence. '
                'Explain a necessary expansion; retain native discovery. This preference grants no tool or release authority.')
    if state.get('mode') not in ('open', None):
        return 'Skill selection could not be applied (' + state['mode'] + '); native discovery retained.'
    return ''
