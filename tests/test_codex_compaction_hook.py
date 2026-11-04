import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("jev_codex_hook", Path(__file__).parents[1] / "integrations/codex/jev_compaction_hook.py")
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


def record(kind, payload):
    return (json.dumps({"type": kind, "payload": payload}) + "\n").encode()


class CodexHookTests(unittest.TestCase):
    def test_prior_compaction_replaces_old_selection(self):
        data = record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "old"}]})
        data += record("compacted", {"message": "Current goal and unfinished work"})
        data += record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "new correction"}]})
        blocks = hook.read_blocks(data)
        self.assertEqual([b["text"] for b in blocks], ["Current goal and unfinished work", "new correction"])
        self.assertTrue(blocks[0]["protected"])

    def test_unknown_content_rejects_custom_retention(self):
        with self.assertRaises(ValueError):
            hook.read_blocks(record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_image"}]}))

    def test_capture_restore_scoping_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"JEV_COMPACTION_STATE_DIR": directory}):
            transcript = Path(directory) / "rollout.jsonl"
            transcript.write_bytes(record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Keep my unfinished objective"}]}))
            event = {"session_id": "one", "cwd": directory, "transcript_path": str(transcript), "hook_event_name": "PreCompact"}
            result = {"status": "classified", "retained_text": "[user] Keep my unfinished objective", "blocks": []}
            with patch.object(hook, "classify", return_value=result):
                self.assertEqual(hook.handle(event), {})
            self.assertEqual(hook.state_path(event).stat().st_mode & 0o777, 0o600)
            start = {**event, "hook_event_name": "SessionStart", "source": "compact"}
            self.assertIn("systemMessage", hook.handle(start))
            with transcript.open("ab") as target:
                target.write(record("compacted", {"message": "native summary"}))
            self.assertEqual(hook.handle({**start, "session_id": "other"}), {})
            output = hook.handle(start)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "SessionStart")
            self.assertIn("unfinished objective", output["additionalContext"])
            self.assertEqual(hook.handle(start), {})

    def test_failure_invalidates_older_packet(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"JEV_COMPACTION_STATE_DIR": directory}):
            transcript = Path(directory) / "rollout.jsonl"
            transcript.write_bytes(record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "goal"}]}))
            event = {"session_id": "one", "cwd": directory, "transcript_path": str(transcript), "hook_event_name": "PreCompact"}
            hook.save(hook.state_path(event), {"stale": True})
            with patch.object(hook, "classify", return_value={"status": "fallback"}):
                self.assertIn("systemMessage", hook.handle(event))
            self.assertFalse(hook.state_path(event).exists())

    def test_changed_transcript_never_restores_stale_packet(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"JEV_COMPACTION_STATE_DIR": directory}):
            transcript = Path(directory) / "rollout.jsonl"
            transcript.write_bytes(record("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "original"}]}))
            event = {"session_id": "one", "cwd": directory, "transcript_path": str(transcript), "hook_event_name": "PreCompact"}
            with patch.object(hook, "classify", return_value={"status": "classified", "retained_text": "original"}):
                hook.handle(event)
            transcript.write_bytes(record("compacted", {"message": "different branch"}))
            result = hook.handle({**event, "hook_event_name": "SessionStart", "source": "compact"})
            self.assertNotIn("hookSpecificOutput", result)


if __name__ == "__main__":
    unittest.main()
