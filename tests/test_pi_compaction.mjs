/** Synthetic protocol tests using the installed Pi loader and a local mock gateway. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import { fileURLToPath, pathToFileURL } from "node:url";
import { test } from "node:test";

test("native Pi loader, protected content, normalization, fallback, and abort", async () => {
  const cli = realpathSync(execFileSync("which", ["pi"], { encoding: "utf8" }).trim());
  const { loadExtensions } = await import(new URL("./core/extensions/loader.js", pathToFileURL(cli)));
  const extensionPath = fileURLToPath(new URL("../integrations/pi/jev-compaction.ts", import.meta.url));
  const temp = mkdtempSync(join(tmpdir(), "jev-pi-loader-"));
  const linkedExtension = join(temp, "jev-compaction.ts");
  symlinkSync(extensionPath, linkedExtension);
  const loaded = await loadExtensions([linkedExtension], fileURLToPath(new URL("..", import.meta.url)));
  rmSync(temp, { recursive: true });
  assert.deepEqual(loaded.errors, []);
  const [handler] = loaded.extensions[0].handlers.get("session_before_compact");
  let requests = 0;
  let onRequest;
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const payload = JSON.parse(Buffer.concat(chunks).toString());
    const serialized = JSON.stringify(payload);
    for (const privateValue of ["PRIVATE_THINKING", "PRIVATE_SIGNATURE", "PRIVATE_PROVIDER_METADATA", "RUNTIME_SYSTEM_DIRECTIVE", "RUNTIME_DEVELOPER_DIRECTIVE", "fixture-secret-123"]) assert.ok(!serialized.includes(privateValue));
    requests++;
    onRequest?.();
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ results: payload.contexts.map(() => ({ decision: { retention: "keep", reason: "required" } })) }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const oldBase = process.env.JEV_BASE_URL;
  process.env.JEV_BASE_URL = `http://127.0.0.1:${server.address().port}`;
  try {
    const warnings = [];
    const ctx = { model: { contextWindow: 10000, maxTokens: 4096 }, ui: { notify(message) { warnings.push(message); } } };
    const preparation = {
      firstKeptEntryId: "native-boundary", tokensBefore: 4000, isSplitTurn: false,
      previousSummary: "Existing protected summary.",
      fileOps: { read: new Set(["/read.ts"]), written: new Set(), edited: new Set(["/edit.ts"]) },
      settings: { reserveTokens: 1000, keepRecentTokens: 2000 },
      messagesToSummarize: [
        { role: "user", content: "Owner directive." },
        { role: "system", content: "RUNTIME_SYSTEM_DIRECTIVE" },
        { role: "developer", content: "RUNTIME_DEVELOPER_DIRECTIVE" },
        { role: "assistant", providerMetadata: "PRIVATE_PROVIDER_METADATA", content: [
          { type: "thinking", thinking: "PRIVATE_THINKING", thinkingSignature: "PRIVATE_SIGNATURE" },
          { type: "text", text: "Public discussion.", textSignature: "PRIVATE_SIGNATURE" },
        ] },
        { role: "toolResult", toolCallId: "tool-id", toolName: "read", isError: false, content: [{ type: "text", text: '{"password":"fixture-secret-123"}' }] },
      ], turnPrefixMessages: [],
    };
    const event = { preparation, customInstructions: "Protect instructions.", signal: new AbortController().signal };
    const result = await handler(event, ctx);
    assert.equal(result.compaction.firstKeptEntryId, "native-boundary");
    assert.equal(result.compaction.tokensBefore, 4000);
    for (const text of ["Owner directive.", "Existing protected summary.", "Protect instructions.", "/read.ts", "/edit.ts", "Public discussion."]) assert.ok(result.compaction.summary.includes(text));
    for (const text of ["PRIVATE_THINKING", "PRIVATE_SIGNATURE", "PRIVATE_PROVIDER_METADATA", "RUNTIME_SYSTEM_DIRECTIVE", "RUNTIME_DEVELOPER_DIRECTIVE"]) assert.ok(!result.compaction.summary.includes(text));
    assert.equal(requests, 1);
    assert.ok(result.compaction.summary.includes('fixture-secret-123'), "local extractive summary preserves original content");
    assert.ok(result.compaction.summary.includes('tool-id'));
    assert.deepEqual(result.compaction.details.fileOps.read, ["/read.ts"]);
    assert.equal(await handler({ ...event, preparation: { ...preparation, settings: { ...preparation.settings, reserveTokens: 1 } } }, ctx), undefined);
    assert.equal(await handler({ ...event, preparation: { ...preparation, messagesToSummarize: [{ role: "user", content: [{ type: "image", data: "OPAQUE_BINARY" }] }] } }, ctx), undefined);
    assert.equal(requests, 2, "binary fallback must not call the gateway");
    const aborted = new AbortController(); aborted.abort();
    assert.equal(await handler({ ...event, signal: aborted.signal }, ctx), undefined);
    const activeAbort = new AbortController();
    onRequest = () => activeAbort.abort();
    assert.equal(await handler({ ...event, signal: activeAbort.signal }, ctx), undefined);
    assert.equal(requests, 3);
    assert.equal(warnings.length, 2);
  } finally {
    if (oldBase === undefined) delete process.env.JEV_BASE_URL; else process.env.JEV_BASE_URL = oldBase;
    await new Promise((resolve) => server.close(resolve));
  }
});
