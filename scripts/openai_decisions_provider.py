"""Native Decisions using JEV's own ChatGPT OAuth grant; no fallback route."""
from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai_chatgpt_provider import access_token

ENDPOINT = 'https://api.openai.com/v1/decisions'
MODEL = 'gpt-6-luna'


def _text(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise RuntimeError('Decisions input must be JSON serializable') from None


def native_questions(questions):
    """Translate named TypeSafe questions into the documented Decisions schema."""
    if not isinstance(questions, dict) or not questions:
        raise RuntimeError('Decisions requires named System One questions')
    result = []
    for name, question in questions.items():
        if not isinstance(name, str) or not name or not isinstance(question, dict):
            raise RuntimeError('Invalid System One question')
        kind, criteria = question.get('type'), question.get('criteria')
        instructions = _text(question.get('instructions', ''))
        native = {'name': name, 'type': kind, 'instructions': instructions}
        if kind == 'choice':
            if not isinstance(criteria, dict) or not criteria or not all(isinstance(key, str) for key in criteria):
                raise RuntimeError('Choice questions require named criteria')
            native['choices'] = [{'value': label, 'description': _text(description)}
                                 for label, description in criteria.items()]
        elif kind == 'score':
            if not isinstance(criteria, list) or len(criteria) < 2:
                raise RuntimeError('Score questions require ordered criteria')
            native['levels'] = [{'label': str(index), 'description': _text(description)}
                                for index, description in enumerate(criteria)]
        elif kind == 'noul':
            if criteria is not None and (not isinstance(criteria, dict) or set(criteria) - {'true', 'false'}):
                raise RuntimeError('Noul criteria must describe true and false')
            native['type'] = 'predicate'
            if criteria is not None:
                native['instructions'] += '\nPredicate criteria (true and false): ' + _text(criteria)
        else:
            raise RuntimeError('Unsupported System One question type')
        result.append(native)
    return result


def _number(value, maximum=1):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= maximum):
        raise RuntimeError('Decisions returned an invalid numeric answer')
    return value


def _distribution(answer, labels, score=False):
    entries = answer.get('probabilities')
    if not isinstance(entries, list) or len(entries) != len(labels):
        raise RuntimeError('Decisions returned an incomplete probability distribution')
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError('Decisions returned an invalid probability distribution')
        value = entry.get('value')
        if score:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(labels):
                raise RuntimeError('Decisions returned an invalid score level')
            label = str(value)
            if entry.get('label') != label:
                raise RuntimeError('Decisions returned a mismatched score label')
        else:
            label = value
            if not isinstance(label, str):
                raise RuntimeError('Decisions returned an invalid choice value')
        if label not in labels or label in result:
            raise RuntimeError('Decisions returned an unknown or repeated option')
        result[label] = _number(entry.get('probability'))
    if not math.isclose(sum(result.values()), 1.0, abs_tol=0.01):
        raise RuntimeError('Decisions returned an incomplete probability distribution')
    return result


def _normalize(result, questions):
    if not isinstance(result, dict) or not isinstance(result.get('answers'), list):
        raise RuntimeError('Decisions returned an invalid answer structure')
    if len(result['answers']) != len(questions):
        raise RuntimeError('Decisions returned an incomplete answer set')
    answers = {}
    for (name, question), answer in zip(questions.items(), result['answers']):
        if not isinstance(answer, dict) or answer.get('name') != name:
            raise RuntimeError('Decisions returned mismatched answer names or order')
        if answer.get('type') == 'refusal':
            raise RuntimeError('Decisions refused a System One question')
        kind = question['type']
        if answer.get('type') != ('predicate' if kind == 'noul' else kind):
            raise RuntimeError('Decisions returned a mismatched answer type')
        normalized = {'type': kind}
        if kind == 'noul':
            normalized['noul'] = _number(answer.get('probability'))
        else:
            labels = (list(question['criteria']) if kind == 'choice'
                      else [str(index) for index in range(len(question['criteria']))])
            normalized['probabilities'] = _distribution(answer, labels, score=kind == 'score')
            normalized['confidence'] = _number(answer.get('confidence'))
            if kind == 'choice':
                selected = answer.get('choice')
                if not isinstance(selected, str) or selected not in labels:
                    raise RuntimeError('Decisions returned an unknown choice')
                normalized['choice'] = selected
            else:
                normalized['score'] = _number(answer.get('score'), len(labels) - 1)
        answers[name] = normalized
    usage = result.get('usage', {})
    if not isinstance(usage, dict):
        raise RuntimeError('Decisions returned invalid usage')
    return {'answers': answers, 'usage': usage}


def call(config, state, questions, *, transport=None, timeout=180):
    """Call only /v1/decisions. Preserve HTTPError, including OAuth rejection.

    Native Decisions has no reasoning effort, store or streaming parameters.
    No API key or Responses fallback is attempted.
    """
    if config.get('endpoint', ENDPOINT) != ENDPOINT:
        raise RuntimeError('Decisions requires the official Decisions endpoint')
    if config.get('model', MODEL) != MODEL:
        raise RuntimeError('Decisions currently requires gpt-6-luna')
    body = {'model': MODEL, 'input': _text(state), 'questions': native_questions(questions)}
    if not config.get('credentials_path'):
        raise RuntimeError('JEV ChatGPT credential path is required')
    token = access_token(config['credentials_path'])
    request = Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with (transport or urlopen)(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError:
        raise
    except (URLError, OSError):
        raise RuntimeError('Decisions inference connection failed') from None
    except (ValueError, UnicodeError):
        raise RuntimeError('Decisions returned unreadable answers') from None
    return _normalize(result, questions)
