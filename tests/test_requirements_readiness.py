"""One overarching scenario-verification suite for requirements handoff."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import requirements_readiness as gate
import install_requirements_skill as installer

class HandoffScenarios(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.cwd = Path(self.area.name)
        self.text = "Preserve the draft across restart and reconnect."
        (self.cwd / "discussion.md").write_text("Owner final decision: " + self.text)
        (self.cwd / "spec.md").write_text(self.text)
        (self.cwd / "AGENTS.md").write_text("One final scenario verification after implementation before Dev UAT.")
        self.packet = {
            "version": 1,
            "tracker": {"provider": "gitlab", "project": "example/project", "scope": {"kind": "issue_children", "id": 10}},
            "documents": ["spec.md"], "policies": ["AGENTS.md"],
            "discussion": [{"id": "D1", "state": "agreed", "quote": self.text, "source": "discussion.md"}],
            "requirements": [{"id": "R1", "text": self.text, "source": "spec.md", "decision_ids": ["D1"], "task_ids": [11, 12], "scenario_ids": ["S1"]}],
            "tasks": [
                {"id": 11, "kind": "implementation", "requirement_ids": ["R1"], "scenario_ids": ["S1"]},
                {"id": 12, "kind": "verification", "requirement_ids": ["R1"], "scenario_ids": ["S1"], "after": [11], "before_dev_uat": True}],
            "scenarios": [{"id": "S1", "text": self.text, "requirement_ids": ["R1"], "implementation_task_ids": [11]}]}
        self.live = {"11": {"id": "11", "title": "Persist draft", "body": self.text},
                     "12": {"id": "12", "title": "Final verification", "body": self.text + " After #11, before Dev UAT; all restart and reconnect scenarios."}}
        self.parent = {"title": "Epic", "description": "- [ ] #11\n- [ ] #12\n" + self.text}

    def response(self, url, body, timeout):
        if "status" in body["schema"]:
            return {"complete": True, "results": [{"decision": {"status": "ready"}}]}
        return {"complete": True, "results": [{"decision": {"coverage": "accounted"}} for _ in body["contexts"]]}

    def evaluate(self, packet=None, responder=None, live=None, cached=None):
        with patch.object(gate, "tracker_read", return_value=(self.live if live is None else live, self.parent)), \
             patch.object(gate, "post_json", side_effect=responder or self.response):
            return gate.evaluate(self.packet if packet is None else packet, self.cwd, cached)

    def test_ready_and_single_verification_failures(self):
        ready = self.evaluate()
        self.assertEqual((ready["gate"], ready["single_verification"]), ("PASS", "PASS"))
        mutations = {}
        absent = copy.deepcopy(self.packet)
        absent["tasks"][1]["kind"] = "implementation"
        mutations["absent"] = absent
        duplicate = copy.deepcopy(self.packet)
        second = copy.deepcopy(duplicate["tasks"][1])
        second["id"] = 13
        duplicate["tasks"].append(second)
        duplicate["requirements"][0]["task_ids"].append(13)
        mutations["duplicate"] = duplicate
        for name, field, value in [("uncovered", "scenario_ids", []), ("wrong_order", "after", []), ("no_uat_order", "before_dev_uat", False)]:
            packet = copy.deepcopy(self.packet)
            packet["tasks"][1][field] = value
            mutations[name] = packet
        for name, packet in mutations.items():
            with self.subTest(name=name):
                live = {str(task["id"]): self.live.get(str(task["id"]), self.live["12"]) for task in packet["tasks"]}
                result = self.evaluate(packet, live=live)
                self.assertEqual(result["gate"], "FAIL")
                self.assertEqual(result["single_verification"], "FAIL")

    def test_missing_ticket_and_agreed_commitment(self):
        missing = self.evaluate(live={"11": self.live["11"]})
        self.assertEqual(missing["gate"], "FAIL")
        packet = copy.deepcopy(self.packet)
        packet["discussion"].append({"id": "D2", "state": "agreed", "quote": self.text, "source": "discussion.md"})
        self.assertEqual(self.evaluate(packet)["gate"], "FAIL")
        packet["discussion"][-1]["state"] = "brainstorm"
        self.assertEqual(self.evaluate(packet)["gate"], "PASS")

    def test_semantic_gaps_unaccepted_deferral_and_incomplete_responses(self):
        for label in ("partial", "missing", "ambiguous", "deferred", "abstain"):
            def responder(url, body, timeout, label=label):
                result = self.response(url, body, timeout)
                result["results"][-1]["decision"]["coverage"] = label
                return result
            result = self.evaluate(responder=responder)
            self.assertNotEqual(result["gate"], "PASS")
        for change in ({"complete": False}, {"failed_work": [{"error": "capacity"}]}, {"results": []}):
            def responder(url, body, timeout, change=change):
                return {**self.response(url, body, timeout), **change}
            self.assertEqual(self.evaluate(responder=responder)["gate"], "ABSTAIN")
        def unavailable(*args):
            raise OSError("synthetic outage")
        ready = self.evaluate()
        self.assertEqual(self.evaluate(responder=unavailable, cached=ready)["gate"], "ABSTAIN")

    def test_sources_and_cache_are_current(self):
        ready = self.evaluate()
        self.assertTrue(self.evaluate(cached=ready)["cache_reused"])
        self.live["11"]["body"] += " Updated acceptance."
        changed = self.evaluate(cached=ready)
        self.assertNotEqual(changed["fingerprint"], ready["fingerprint"])
        (self.cwd / "spec.md").write_text("Superseded wording.")
        with self.assertRaises(ValueError):
            self.evaluate()
        self.assertNotIn("token=secret", gate.redact("token=secret"))

    def test_live_parent_inventory_includes_additions_not_prose_dependencies(self):
        responses = {
            "10": {"iid": 10, "description": "- [ ] #11\nOther epic #99.\nLater additions:\n- [x] #12"},
            "11": {"iid": 11, "description": self.text},
            "12": {"iid": 12, "description": self.text}}
        def run(args, **kwargs):
            self.assertEqual(args[:2], ["glab", "api"])
            self.assertNotIn("--method", args)
            ident = args[-1].split("/")[-1]
            return subprocess.CompletedProcess(args, 0, json.dumps(responses[ident]), "")
        with patch.object(gate.subprocess, "run", side_effect=run):
            tasks, parent = gate.tracker_read(self.packet["tracker"])
        self.assertEqual(set(tasks), {"11", "12"})

    def test_shared_install_backup_collision_and_private_output(self):
        codex, pi = self.cwd / "codex", self.cwd / "pi"
        old = codex / "skills/requirements-traceability"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_text("---\nname: requirements-traceability\n---\nOriginal")
        (old / "local-note.txt").write_text("Preserve")
        initial = installer.install(codex, pi)
        self.assertTrue(all(row["changed"] for row in initial["installations"]))
        backup = Path(initial["installations"][0]["backup"])
        self.assertEqual((backup / "local-note.txt").read_text(), "Preserve")
        self.assertFalse(any(row["changed"] for row in installer.install(codex, pi)["installations"]))
        self.assertEqual((pi / "skills/requirements-traceability").resolve(), (codex / "skills/requirements-traceability").resolve())
        foreign = self.cwd / "foreign/skills/requirements-traceability"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("---\nname: another-skill\n---")
        with self.assertRaises(ValueError):
            installer.install(self.cwd / "empty", self.cwd / "foreign")
        self.assertFalse((self.cwd / "empty/skills").exists())
        output = self.cwd / "result.json"
        gate.write_private(output, self.evaluate())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(output.read_text())["gate"], "PASS")

if __name__ == "__main__":
    unittest.main()
