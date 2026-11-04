"""One scenario verification gate for the ZCode Jev integration."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_zcode
import retention_checkpoint

ADAPTER = ROOT / 'integrations/zcode/jev_hook.py'
GATE = Path(os.environ.get('MERCURY_GATE_SOURCE', '/Volumes/Seagate/workspace/fmsmercury/scripts/mercury_test_gate.py'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class ZCodeScenarios(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.repo = self.root / 'mercury'
        (self.repo / 'scripts').mkdir(parents=True)
        (self.repo / 'docs').mkdir()
        shutil.copyfile(GATE, self.repo / 'scripts/mercury_test_gate.py')
        (self.repo / 'docs/MERCURY_TEST_GATE.md').write_text('Canonical workflow fixture')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)

    def invoke(self, name, event):
        result = subprocess.run([sys.executable, str(ADAPTER), '--event', name],
                                input=json.dumps(event), text=True, capture_output=True, check=True,
                                env={key: value for key, value in os.environ.items() if key != 'MERCURY_TEST_PACKET'})
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def test_native_test_proposals_and_unrelated_work(self):
        base = {'cwd': str(self.repo), 'sessionId': 'sess_fixture', 'toolCallId': 'call_fixture'}
        proposals = [
            ('Bash', {'command': 'python3 -m unittest missing_fixture'}),
            ('ApplyPatch', {'patch_text': '*** Begin Patch\n*** Add File: tests/test_fixture.py\n+assert True\n*** End Patch'}),
            ('Write', {'file_path': str(self.repo / 'tests/test_fixture.py'), 'content': 'assert True\n'}),
        ]
        for name, inp in proposals:
            with self.subTest(name=name):
                output = self.invoke('PreToolUse', {**base, 'toolName': name, 'toolInput': inp})
                specific = output['hookSpecificOutput']
                self.assertEqual(specific['hookEventName'], 'PreToolUse')
                self.assertEqual(specific['permissionDecision'], 'deny')
                self.assertIn('sess_fixture', specific['permissionDecisionReason'])
        self.assertEqual(self.invoke('PreToolUse', {**base, 'toolName': 'Bash', 'toolInput': {'command': 'pwd'}}), {})
        self.assertEqual(self.invoke('PreToolUse', {**base, 'cwd': str(self.root), 'toolName': 'Bash',
                                                  'toolInput': {'command': 'python3 -m unittest missing_fixture'}}), {})

    def test_completion_stop_and_repeated_stop(self):
        event = {'cwd': str(self.repo), 'sessionId': 'sess_fixture'}
        packet = {'task': {'stage': 'explicit_test_review', 'requirement': 'Integration scenario'},
                  'source_refs': [], 'candidates': [], 'requirements': [{'id': 'R1', 'evidence_candidate_ids': []}]}
        packet_path = self.root / 'packet.json'
        packet_path.write_text(json.dumps(packet))
        state = self.repo / '.git/mercury-test-gate'
        for category in ('active', 'completion-intent'):
            folder = state / category
            folder.mkdir(parents=True)
            (folder / (digest('sess_fixture') + '.json')).write_text(json.dumps({'packet_path': str(packet_path.resolve())}))
        stopped = self.invoke('Stop', event)
        self.assertEqual(stopped['decision'], 'block')
        self.assertIn('NEEDS_EVIDENCE', stopped['reason'])
        self.assertEqual(self.invoke('Stop', {**event, 'stopHookActive': True}), {})

    def test_session_start_and_post_response_normalization(self):
        spec = importlib.util.spec_from_file_location('jev_zcode_hook', ADAPTER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        event = module.normalize({'toolName': 'Bash', 'toolInput': {'command': 'pwd'}, 'cwd': str(self.repo),
                                  'toolResponse': {'exitCode': 0, 'output': 'fixture'}}, 'PostToolUse')
        self.assertEqual(event['tool_response']['exit_code'], 0)
        self.assertEqual(event['tool_input']['command'], 'pwd')
        unknown = module.normalize({'toolResponse': {'output': 'fixture'}}, 'PostToolUse')
        self.assertNotIn('exit_code', unknown['tool_response'])
        start = self.invoke('SessionStart', {'cwd': str(self.repo)})
        self.assertIn('requirements-traceability', start['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.invoke('PostToolUse', {'cwd': str(self.repo), 'sessionId': 'sess_fixture',
                                                   'toolName': 'Bash', 'toolInput': {'command': 'pwd'}}), {})

    def test_final_receipt_requires_exit_and_preserves_stderr_cases(self):
        spec = importlib.util.spec_from_file_location('fixture_mercury_gate', self.repo / 'scripts/mercury_test_gate.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        row = {'id': 'run', 'action': 'run', 'path': '', 'intent': 'Fixture receipt', 'assertions': 'Case passes',
               'boundary': 'fixture', 'regression_purpose': 'Outcome mapping', 'replacement_refs': [],
               'command': 'python3 -m unittest fixture -v', 'workdir': '.', 'result_format': 'unittest_verbose'}
        packet = {'task': {'stage': 'explicit_test_review', 'requirement': 'Final exit and case receipt'},
                  'source_refs': [], 'candidates': [row]}
        packet_path = self.root / 'receipt-packet.json'
        packet_path.write_text(json.dumps(packet))
        state = self.repo / '.git/mercury-test-gate'
        (state / 'active').mkdir(parents=True)
        (state / 'active' / (digest('sess_fixture') + '.json')).write_text(json.dumps({'packet_path': str(packet_path.resolve())}))
        (state / 'pending').mkdir()
        pending_path = state / 'pending' / digest(['sess_fixture', 'call_fixture'])
        pending_path.write_text(json.dumps({'identity': 'call_fixture', 'session_id': 'sess_fixture',
            'packet_digest': digest(packet), 'content_digest': gate.snapshot(packet, self.repo),
            'environment': None, 'candidate_ids': ['run'], 'cwd': str(self.repo.resolve()),
            'started_ns': 0, 'artifacts': {}}))
        event = {'cwd': str(self.repo), 'sessionId': 'sess_fixture', 'toolCallId': 'call_fixture',
                 'toolName': 'Bash', 'toolInput': {'command': row['command']}}
        unknown = self.invoke('PostToolUse', {**event, 'toolResponse': {'stdout': '', 'stderr': 'partial'}})
        self.assertIn('no final exit', unknown['hookSpecificOutput']['additionalContext'])
        background = self.invoke('PostToolUse', {**event, 'toolResponse': {'exitCode': 0, 'status': 'backgrounded'}})
        self.assertIn('no final exit', background['hookSpecificOutput']['additionalContext'])
        self.assertFalse((state / 'results').exists())
        self.invoke('PostToolUse', {**event, 'toolResponse': {'exitCode': 0, 'status': 'completed', 'stdout': '',
            'stderr': 'test_fixture (fixture.Cases.test_fixture) ... ok\n'}})
        receipt = json.loads((state / 'results' / (digest('run') + '.json')).read_text())
        self.assertEqual(receipt['exit_code'], 0)
        self.assertEqual(receipt['cases'], [{'id': 'fixture.Cases.test_fixture', 'status': 'passed'}])
        self.assertFalse(pending_path.exists())

    def test_install_preserves_existing_config_and_is_idempotent(self):
        home, codex = self.root / 'zcode', self.root / 'codex'
        skill = codex / 'skills/jev-decision'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: jev-decision\ndescription: Fixture\n---\n')
        config_path = home / 'cli/config.json'
        config_path.parent.mkdir(parents=True)
        foreign = {'hooks': [{'type': 'process', 'command': 'existing-hook'}]}
        original = {'plugins': {'enabled': True}, 'hooks': {'events': {'Stop': [foreign]}}}
        config_path.write_text(json.dumps(original))
        first = install_zcode.install(home, codex, ROOT)
        self.assertTrue(first['config_changed'])
        updated = json.loads(config_path.read_text())
        self.assertEqual(updated['plugins'], original['plugins'])
        self.assertIn(foreign, updated['hooks']['events']['Stop'])
        self.assertEqual(json.loads(Path(first['config_backup']).read_text()), original)
        self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
        for name in ('requirements-traceability', 'jev-retention', 'jev-decision'):
            self.assertTrue((home / 'skills' / name / 'SKILL.md').is_file())
        second = install_zcode.install(home, codex, ROOT)
        self.assertFalse(second['config_changed'])
        self.assertEqual(second['skills_changed'], [])
        before = config_path.read_bytes()
        target = home / 'skills/jev-retention'
        target.unlink()
        target.symlink_to(self.root / 'foreign')
        with self.assertRaises(ValueError):
            install_zcode.install(home, codex, ROOT)
        self.assertEqual(config_path.read_bytes(), before)

    def test_private_checkpoint_preserves_source_and_fallback(self):
        source, output = self.root / 'source.json', self.root / 'checkpoint.json'
        source.write_text(json.dumps({'blocks': [{'id': 'U1', 'role': 'user', 'text': 'Keep current scope'}]}))
        original = source.read_bytes()
        output.write_text('old public file')
        output.chmod(0o644)
        with patch.object(retention_checkpoint, 'classify', return_value={
                'status': 'fallback', 'retained_text': 'Keep current scope', 'reason': 'service_unavailable'}):
            result = retention_checkpoint.checkpoint(source, output)
        self.assertEqual(result['status'], 'fallback')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(result['source']['sha256'], hashlib.sha256(original).hexdigest())
        with self.assertRaises(ValueError):
            retention_checkpoint.checkpoint(source, source)


if __name__ == '__main__':
    unittest.main()
