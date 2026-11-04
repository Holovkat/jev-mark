#!/usr/bin/env python3
"""Translate ZCode native hook events to the repository-owned Mercury gate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

OPERATIONS = {'PreToolUse': 'hook', 'PostToolUse': 'post-hook', 'Stop': 'stop-hook'}
INSTRUCTIONS = ('Use requirements-traceability before declaring an epic or sprint ready; keep exactly one final scenario verifier. '
                'For Mercury test proposals follow docs/MERCURY_TEST_GATE.md and the repository mercury_test_gate.py planner/runner. '
                'Jev uses the configured gateway and never grants UAT or release approval. Use jev-retention only for explicit manual retention work; do not check requirements on every turn.')


def repository(cwd):
    start = Path(cwd).expanduser().resolve()
    for root in (start, *start.parents):
        if (root / 'scripts/mercury_test_gate.py').is_file() and (root / 'docs/MERCURY_TEST_GATE.md').is_file():
            return root
    return None


def normalize(event, name):
    result = dict(event)
    for native, canonical in [('sessionId', 'session_id'), ('toolName', 'tool_name'),
                              ('toolInput', 'tool_input'), ('toolResult', 'tool_response'), ('toolResponse', 'tool_response'),
                              ('stopHookActive', 'stop_hook_active'), ('toolCallId', 'tool_use_id')]:
        if native in event:
            result[canonical] = event[native]
    result['hook_event_name'] = name
    # ZCode supplies its native working directory separately from the exact proposal.
    if isinstance(event.get('cwd'), str):
        result['native_execution_cwd'] = event['cwd']
    inp = result.get('tool_input', {})
    # Installed ZCode runs Bash in event.cwd; retain the exact command and expose
    # that authoritative scope to Mercury without rewriting Write/Edit proposals.
    if (result.get('tool_name') == 'Bash' and isinstance(inp, dict)
            and 'workdir' not in inp and 'cwd' not in inp
            and isinstance(event.get('cwd'), str)):
        result['tool_input'] = {**inp, 'workdir': event['cwd']}
    if result.get('tool_name') == 'ApplyPatch':
        result['tool_name'] = 'apply_patch'
        if isinstance(inp, dict) and isinstance(inp.get('patch_text'), str):
            result['tool_input'] = {'patch': inp['patch_text']}
    response = result.get('tool_response')
    if (isinstance(response, dict) and type(response.get('exitCode')) is int
            and response.get('status') != 'backgrounded'):
        result['tool_response'] = {**response, 'exit_code': response['exitCode']}
        # unittest's verbose cases are on stderr. Preserve an existing aggregate
        # output and append any native stream it does not already contain.
        output = response.get('output') if isinstance(response.get('output'), str) else ''
        for key in ('stdout', 'stderr'):
            stream = response.get(key)
            if isinstance(stream, str) and stream and stream not in output:
                output = output + ('\n' if output and not output.endswith('\n') else '') + stream
        result['tool_response']['output'] = output
    return result


def recognized(output, name):
    if not isinstance(output, dict):
        raise ValueError('Invalid gate output')
    result = {}
    if name == 'Stop' and output.get('decision') == 'block':
        result = {'decision': 'block', 'reason': str(output.get('reason', 'Mercury needs completion evidence.'))}
    specific = output.get('hookSpecificOutput')
    if isinstance(specific, dict) and specific.get('hookEventName') == name:
        filtered = {'hookEventName': name}
        if isinstance(specific.get('additionalContext'), str):
            filtered['additionalContext'] = specific['additionalContext']
        if name == 'PreToolUse' and specific.get('permissionDecision') in ('deny', 'ask'):
            filtered['permissionDecision'] = specific['permissionDecision']
            if isinstance(specific.get('permissionDecisionReason'), str):
                filtered['permissionDecisionReason'] = specific['permissionDecisionReason']
        result['hookSpecificOutput'] = filtered
    return result


def failure(name):
    reason = 'Mercury Jev adapter could not read the native event or canonical gate; no approval or completion proof inferred.'
    if name == 'PreToolUse':
        return {'hookSpecificOutput': {'hookEventName': name, 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}
    if name == 'Stop':
        return {'decision': 'block', 'reason': reason}
    return {'additionalContext': reason}


def handle(event, name):
    if not isinstance(event, dict):
        raise ValueError('Native event must be an object')
    root = repository(event.get('cwd') or os.environ.get('ZCODE_PROJECT_DIR') or os.getcwd())
    if name == 'SessionStart':
        instructions = INSTRUCTIONS if root else (
            'Use requirements-traceability before declaring an epic or sprint ready; keep exactly one final scenario verifier. '
            'Use jev-decision through the configured gateway; Jev never grants UAT or release approval. '
            'Use jev-retention only for explicit manual retention work; do not check requirements on every turn.')
        return {'hookSpecificOutput': {'hookEventName': name, 'additionalContext': instructions}}
    if root is None:
        return {}
    if name not in OPERATIONS:
        return {}
    completed = subprocess.run([sys.executable, str(root / 'scripts/mercury_test_gate.py'), OPERATIONS[name]],
                               input=json.dumps(normalize(event, name)), text=True,
                               capture_output=True, cwd=root)
    if completed.returncode:
        raise ValueError('Canonical gate failed')
    return recognized(json.loads(completed.stdout), name) if completed.stdout.strip() else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event', required=True, choices=['SessionStart', *OPERATIONS])
    args = parser.parse_args()
    event = {}
    try:
        event = json.load(sys.stdin)
        output = handle(event, args.event)
    except Exception:
        repeated_stop = (args.event == 'Stop' and isinstance(event, dict)
                         and (event.get('stopHookActive') or event.get('stop_hook_active')))
        output = {} if repeated_stop else failure(args.event)
    print(json.dumps(output))


if __name__ == '__main__':
    main()
