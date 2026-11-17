"""Soft selections preserve native authority and do not alter tool availability."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import skill_preferences as prefs


class SkillPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / '.git').mkdir()
        self.env = patch.dict(os.environ, {'JEV_SKILL_SELECTION_DIR': str(self.root / 'sessions')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.packet = {'project': str(self.root), 'harness': 'codex', 'session_id': 'one',
                       'skills': [{'id': n, 'name': n, 'path': str(self.root / n)}
                                  for n in ('chosen', 'explicit', 'mandatory', 'dependency', 'other')],
                       'tools': [{'id': 'tool', 'name': 'tool', 'available': True}]}

    def save(self, names, scope='session', session='one'):
        path = prefs.selection_path(self.root, 'codex', session, scope)
        prefs.write_json(path, {'version': 1, 'mode': 'soft', 'skills': [
            {'name': n, 'path': str(self.root / n)} for n in names]})
        return path

    def test_authority_dependency_closure_and_tools(self):
        path = self.save(['chosen'])
        self.packet['skills'][0]['dependencies'] = ['dependency']
        self.packet['skills'][1]['explicit'] = True
        self.packet['skills'][2]['required'] = True
        result = prefs.apply_selection(copy.deepcopy(self.packet))
        self.assertEqual({r['name'] for r in result['skills']}, {'chosen', 'explicit', 'mandatory', 'dependency'})
        self.assertEqual(result['tools'], self.packet['tools'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_scopes_canonical_subdirectory_and_unlock(self):
        self.save(['mandatory'], scope='project')
        self.save(['chosen'])
        nested = self.root / 'frontend'; nested.mkdir()
        self.assertEqual(prefs.load_selection(nested, 'codex', 'one')['skills'][0]['name'], 'chosen')
        self.assertEqual(prefs.load_selection(nested, 'codex', 'two')['skills'][0]['name'], 'mandatory')
        self.assertEqual(prefs.load_selection(nested, 'claude', 'one')['skills'][0]['name'], 'mandatory')
        prefs.write_json(prefs.selection_path(nested, 'codex', 'one'), {'version': 1, 'mode': 'open'})
        self.assertEqual(prefs.load_selection(nested, 'codex', 'one')['mode'], 'open')
        self.assertEqual(prefs.load_selection(nested, 'codex', 'two')['mode'], 'soft')
        with self.assertRaises(ValueError): prefs.selection_path(nested, 'codex', None)

    def test_stale_malformed_and_missing_dependency_retain_discovery(self):
        path = self.save(['gone'])
        result = prefs.apply_selection(copy.deepcopy(self.packet))
        self.assertEqual(result['skills'], self.packet['skills'])
        self.assertEqual(result['skill_selection']['mode'], 'stale')
        path.write_text('{broken')
        self.assertEqual(prefs.apply_selection(copy.deepcopy(self.packet))['skills'], self.packet['skills'])
        self.save(['chosen'])
        self.packet['skills'][0]['dependencies'] = ['missing']
        self.assertEqual(prefs.apply_selection(copy.deepcopy(self.packet))['skill_selection']['mode'], 'missing_dependency')

    def test_hook_uses_selection_and_explicit_override(self):
        spec = importlib.util.spec_from_file_location('preferences_hook', ROOT / 'integrations/capabilities/hook.py')
        hook = importlib.util.module_from_spec(spec); spec.loader.exec_module(hook)
        files = []
        for n in ('chosen', 'explicit', 'mandatory', 'other'):
            path = self.root / n
            path.write_text('---\nname: ' + n + '\ndescription: fixture\n---\nBODY_NOT_FOR_CONTEXT')
            files.append({'name': n, 'path': str(path)})
        self.save(['chosen'])
        (self.root / '.jev').mkdir(exist_ok=True)
        (self.root / '.jev/capabilities.json').write_text(json.dumps({'required_skills': ['mandatory']}))
        packet = hook.build_packet({'cwd': str(self.root), 'session_id': 'one', 'prompt': '$explicit', 'skills': files}, 'codex')
        self.assertEqual({r['name'] for r in packet['skills']}, {'chosen', 'explicit', 'mandatory'})
        self.assertNotIn('BODY_NOT_FOR_CONTEXT', json.dumps(packet))
        env = {**os.environ, 'JEV_CAPABILITY_STATE_DIR': str(self.root / 'cache')}
        # Empty optional catalogue keeps the subprocess fixture entirely local.
        event = {'cwd': str(self.root), 'session_id': 'open', 'skills': []}
        (self.root / '.jev/capabilities.json').unlink()
        result = subprocess.run([sys.executable, str(ROOT / 'integrations/capabilities/hook.py'), '--harness', 'codex'],
                                input=json.dumps(event), text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')


if __name__ == '__main__':
    unittest.main()
