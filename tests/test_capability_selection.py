"""Capability routing boundary tests; all services are mocked or loopback fixtures."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import capability_selector as selector
import install_capability_selector as installer
spec = importlib.util.spec_from_file_location('capability_hook', ROOT / 'integrations/capabilities/hook.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class CapabilitySelectionTests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.base = Path(self.area.name)
        self.skill = self.base / 'SKILL.md'
        self.skill.write_text('---\nname: fixture\ndescription: >-\n  Folded first\n  second line\n---\nNative skill body\n')
        self.packet = {'version': 1, 'harness': 'pi', 'session_id': 'fixture', 'project': str(self.base),
                       'task': {'request': 'PRIVATE_TASK_SENTINEL'},
                       'skills': [self.row('fixture')], 'tools': []}

    def row(self, identity, **extra):
        return {'id': identity, 'name': identity, 'description': 'fixture metadata',
                'path': str(self.skill), 'content_hash': hashlib.sha256(self.skill.read_bytes()).hexdigest(), **extra}

    def decide(self, packet=None, response=None, **kwargs):
        with patch.object(selector, 'post_json', return_value=response or {'results': [{'fields': {'classification': {'value': 'use_now'}}}]}) as gateway:
            result = selector.select(packet or self.packet, base_url='http://fixture.invalid', timeout=5, **kwargs)
        return result, gateway

    def test_required_explicit_and_dependency_closure(self):
        second = self.base / 'second.md'; second.write_text('dependency')
        third = self.base / 'third.md'; third.write_text('explicit')
        self.packet['skills'][0].update(required=True, dependencies=['dependency'])
        dependency = self.row('dependency'); dependency.update(path=str(second), content_hash=hashlib.sha256(second.read_bytes()).hexdigest())
        explicit = self.row('explicit', explicit=True); explicit.update(path=str(third), content_hash=hashlib.sha256(third.read_bytes()).hexdigest())
        self.packet['skills'] += [dependency, explicit]
        result, gateway = self.decide()
        self.assertEqual(result['status'], 'selected')
        self.assertEqual({r['id'] for r in result['skill_refs']}, {'fixture', 'dependency', 'explicit'})
        gateway.assert_not_called()
        self.packet['skills'][0]['dependencies'] = ['unknown']
        result, gateway = self.decide()
        self.assertEqual(result['reason'], 'missing_dependency')
        self.assertTrue(result['native_discovery'])
        gateway.assert_not_called()

    def test_gateway_fields_finite_labels_and_fallback(self):
        for label in ('use_now', 'available_later', 'not_relevant'):
            with self.subTest(label=label):
                result, gateway = self.decide(response={'complete': True, 'results': [{'fields': {'classification': {'value': label}}}]})
                self.assertEqual(result['decisions'][0]['classification'], label)
                self.assertEqual(result['status'], 'selected')
                request = gateway.call_args.args[1]
                self.assertEqual(request['schema']['classification']['choices'], ['use_now', 'available_later', 'not_relevant', 'abstain'])
                self.assertNotIn(str(self.skill), json.dumps(request))
        for response in ({'complete': False}, {'results': []}, {'results': [{'fields': {'classification': {'value': 'arbitrary'}}}]}, {'results': [{'fields': {'classification': {'value': 'use_now'}, 'instructions': {'value': 'evil'}}}]}):
            with self.subTest(response=response):
                result, _ = self.decide(response=response)
                self.assertEqual(result['status'], 'fallback')
                self.assertTrue(result['native_discovery'])
                self.assertEqual(result['decisions'][0]['classification'], 'abstain')
        with patch.object(selector, 'post_json', side_effect=OSError('offline')):
            result = selector.select(self.packet, base_url='http://fixture.invalid', timeout=5)
        self.assertEqual(result['reason'], 'service_unavailable')
        required = self.base / 'required.md'; required.write_text('required')
        row = self.row('required', required=True); row.update(path=str(required), content_hash=hashlib.sha256(required.read_bytes()).hexdigest())
        self.packet['skills'].append(row)
        with patch.object(selector, 'post_json', side_effect=OSError('offline')):
            result = selector.select(self.packet, base_url='http://fixture.invalid', timeout=5)
        self.assertEqual({r['id'] for r in result['skill_refs']}, {'required'})
        self.packet['tools'] = [{'id': 'useful-tool', 'name': 'useful-tool', 'description': 'Useful native tool'}]
        with patch.object(selector, 'post_json', return_value={'results': [{'fields': {'classification': {'value': 'abstain'}}}, {'fields': {'classification': {'value': 'use_now'}}}]}):
            result = selector.select(self.packet, base_url='http://fixture.invalid', timeout=5, state_dir=self.base / 'partial-cache')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['reason'], 'uncertain')
        self.assertFalse(result['cached'])
        self.assertEqual({r['id'] for r in result['skill_refs']}, {'required'})
        self.assertEqual(result['tool_ids'], ['useful-tool'])
        self.assertEqual(list((self.base / 'partial-cache').glob('*.json')), [])

    def test_actual_tool_names_and_unavailable_tools(self):
        self.packet['skills'] = []
        self.packet['tools'] = [{'id': 'mcp__fixture__read', 'name': 'mcp__fixture__read', 'description': 'Read fixture', 'available': True}, {'id': 'disabled', 'name': 'disabled', 'description': 'Unavailable', 'available': False}]
        result, gateway = self.decide()
        self.assertEqual(result['tool_refs'], [{'id': 'mcp__fixture__read', 'name': 'mcp__fixture__read'}])
        self.assertNotIn('disabled', result['tool_ids'])
        self.assertEqual(len(gateway.call_args.args[1]['contexts']), 1)
        self.packet['tools'][1]['required'] = True
        result, gateway = self.decide()
        self.assertEqual(result['reason'], 'required_tool_unavailable')
        self.assertNotIn('disabled', result['tool_ids'])
        gateway.assert_not_called()

    def test_cache_hit_invalidation_and_private_modes(self):
        cache = self.base / 'cache'
        first, gateway = self.decide(state_dir=cache)
        self.assertFalse(first['cached']); gateway.assert_called_once()
        second, gateway = self.decide(state_dir=cache)
        self.assertTrue(second['cached']); gateway.assert_not_called()
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(next(cache.glob('*.json')).stat().st_mode), 0o600)
        for field in ('request', 'stage'):
            self.packet['task'][field] = 'changed'
            result, gateway = self.decide(state_dir=cache)
            self.assertFalse(result['cached']); gateway.assert_called_once()
        with patch.object(selector, 'post_json', return_value={'results': [{'fields': {'classification': {'value': 'use_now'}}}]}) as gateway:
            result = selector.select(self.packet, base_url='http://other-fixture.invalid', timeout=5, state_dir=cache)
        self.assertFalse(result['cached']); gateway.assert_called_once()
        self.skill.write_text('changed source')
        self.packet['skills'][0]['content_hash'] = hashlib.sha256(self.skill.read_bytes()).hexdigest()
        result, gateway = self.decide(state_dir=cache)
        self.assertFalse(result['cached']); gateway.assert_called_once()

    def test_catalogue_symlinks_folded_metadata_disabled_and_missing(self):
        home = self.base / 'home'; roots = home / '.codex/skills'; roots.mkdir(parents=True)
        (roots / 'linked').symlink_to(self.skill.parent, target_is_directory=True)
        (roots / 'cycle').symlink_to(roots, target_is_directory=True)
        project = self.base / 'project'; project.mkdir(); (project / '.git').mkdir()
        with patch.object(hook.Path, 'home', return_value=home):
            packet = hook.build_packet({'cwd': str(project), 'prompt': '$fixture', 'task_context': {'required_skills': ['missing']}}, 'codex')
            self.assertEqual(len(packet['skills']), 1)
            self.assertEqual(packet['skills'][0]['description'], 'Folded first second line')
            self.assertTrue(packet['skills'][0]['explicit'])
            self.assertFalse(packet['catalogue_complete'])
            self.assertEqual(packet['tools'], [])
            self.assertTrue(any('Required skill unavailable' in warning for warning in packet['catalogue_warnings']))
            (home / '.codex/config.toml').write_text('[[skills.config]]\npath = ' + json.dumps(str(self.skill)) + '\nenabled = false\n')
            packet = hook.build_packet({'cwd': str(project), 'prompt': '$fixture'}, 'codex')
            self.assertEqual(packet['skills'], [])

    def test_hook_native_json_and_no_task_echo(self):
        event = {'cwd': str(self.base), 'prompt': 'PRIVATE_TASK_SENTINEL', 'skills': [], 'tools': []}
        environment = {**os.environ, 'HOME': str(self.base), 'JEV_CAPABILITY_STATE_DIR': str(self.base / 'state/cache')}
        for payload in (json.dumps(event), 'malformed'):
            completed = subprocess.run([sys.executable, str(ROOT / 'integrations/capabilities/hook.py'), '--harness', 'pi'], input=payload, text=True, capture_output=True, env=environment, check=True)
            output = json.loads(completed.stdout)
            self.assertIsInstance(output, dict)
            self.assertNotIn('PRIVATE_TASK_SENTINEL', completed.stdout)
            self.assertEqual(completed.stderr, '')
            if payload != 'malformed':
                self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')

    def test_installer_idempotent_preserves_foreign_and_validates_before_writes(self):
        home = self.base / 'install'; config = home / '.claude/settings.json'; config.parent.mkdir(parents=True)
        foreign = {'matcher': 'owner', 'hooks': [{'type': 'command', 'command': 'echo owner'}]}
        config.write_text(json.dumps({'enabledPlugins': {'fixture': True}, 'hooks': {'UserPromptSubmit': [foreign]}}))
        first = installer.install(home, ROOT)
        self.assertTrue(any(row['changed'] for row in first['installations']))
        second = installer.install(home, ROOT)
        self.assertFalse(any(row['changed'] for row in second['installations']))
        installed = json.loads(config.read_text())
        self.assertEqual(installed['hooks']['UserPromptSubmit'][0], foreign)
        self.assertEqual(installed['enabledPlugins'], {'fixture': True})
        collision_home = self.base / 'collision'; collision = collision_home / '.pi/agent/extensions/jev-capabilities.ts'; collision.parent.mkdir(parents=True); collision.write_text('foreign')
        with self.assertRaises(ValueError): installer.install(collision_home, ROOT)
        self.assertFalse((collision_home / '.codex/hooks.json').exists())
        self.assertEqual(collision.read_text(), 'foreign')

    def test_native_pi_loader_and_callback(self):
        if not shutil.which('pi') or not shutil.which('node'):
            self.skipTest('Installed Pi and Node required for native loader fixture')
        source = r'''
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const cli = realpathSync(execFileSync('which', ['pi'], {encoding:'utf8'}).trim());
const {loadExtensions} = await import(new URL('./core/extensions/loader.js', pathToFileURL(cli)));
const loaded = await loadExtensions([process.argv[1] + '/integrations/pi/jev-capabilities.ts'], process.argv[1]);
assert.deepEqual(loaded.errors, []);
loaded.runtime.getAllTools = () => [];
const activeTools = [];
loaded.runtime.getActiveTools = () => activeTools;
const [handler] = loaded.extensions[0].handlers.get('before_agent_start');
const result = await handler({prompt:'PRIVATE_TASK_SENTINEL',systemPrompt:'NATIVE_SYSTEM',systemPromptOptions:{skills:[]}}, {cwd:process.argv[2],sessionManager:{getSessionId:()=> 'fixture'}});
assert.ok(result.systemPrompt.startsWith('NATIVE_SYSTEM\n\nCapability selection:'));
assert.ok(!result.systemPrompt.includes('PRIVATE_TASK_SENTINEL'));
assert.deepEqual(activeTools, []);
console.log('native Pi callback passed');
'''
        completed = subprocess.run(['node', '--input-type=module', '-e', source, str(ROOT), str(self.base)], text=True, capture_output=True, timeout=30, env={**os.environ, 'JEV_CAPABILITY_STATE_DIR': str(self.base / 'pi/cache')})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('native Pi callback passed', completed.stdout)


if __name__ == '__main__':
    unittest.main()
