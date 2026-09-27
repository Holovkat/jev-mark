import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(here, "..", "Resources", "Web", "index.html"), "utf8");
const startMarker = "// LOGIC-SCORING-CORE-START";
const endMarker = "// LOGIC-SCORING-CORE-END";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "scoring markers not found in index.html");
const context = vm.createContext({ Math });
vm.runInContext(
  `${html.slice(start + startMarker.length, end)}\n;globalThis.__s = { scoreOutcome, outcomeSummary };`,
  context,
);
const { scoreOutcome, outcomeSummary } = context.__s;

const definite = { kind: "definite", hedge: "It can't be determined" };
const judgment = { kind: "judgment", reasonable: ["Open the red box"] };

test("definite questions score exact match and flag the hedge as over-caution", () => {
  assert.equal(scoreOutcome("10", "10", definite), "correct");
  assert.equal(scoreOutcome("It can't be determined", "10", definite), "overcaution");
  assert.equal(scoreOutcome("9", "10", definite), "wrong");
  assert.equal(scoreOutcome("9", "10", { kind: "definite", hedge: null }), "wrong");
});

test("judgment questions separate clarify, reasonable and unjustified commits", () => {
  assert.equal(scoreOutcome("Ask which box", "Ask which box", judgment), "clarify");
  assert.equal(scoreOutcome("Open the red box", "Ask which box", judgment), "reasonable");
  assert.equal(scoreOutcome("Open all three boxes", "Ask which box", judgment), "unjustified");
});

test("unscored inputs stay unscored so old report rows keep their exact-match display", () => {
  assert.equal(scoreOutcome("x", "x", undefined), null);
  assert.equal(scoreOutcome(undefined, "x", definite), null);
  assert.equal(outcomeSummary([{ match: true }]), null);
});

test("summary reports acceptable, definite with over-caution, and judgment profile", () => {
  const summary = outcomeSummary([
    { outcome: "correct", hedgeOffered: true },
    { outcome: "overcaution", hedgeOffered: true },
    { outcome: "wrong", hedgeOffered: false },
    { outcome: "clarify" },
    { outcome: "reasonable" },
    { outcome: "unjustified" },
  ]);
  assert.equal(summary, [
    "Acceptable 3/6 (50%)",
    "Definite 1/3 (33%) · over-caution 1/2",
    "Judgment 3: clarify 1 · reasonable 1 · unjustified 1",
  ].join("\n"));
});
