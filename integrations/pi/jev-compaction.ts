/** Jev extractive compaction adapter for Pi 0.84.2. Load with pi -e <this file>. */
import { spawn } from "node:child_process";
import { realpathSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

type Block = { id: string; role: string; text: string; protected?: boolean };
type Message = { role: string; content?: unknown; [key: string]: unknown };
type Preparation = {
  firstKeptEntryId: string;
  messagesToSummarize: Message[];
  turnPrefixMessages: Message[];
  previousSummary?: string;
  isSplitTurn?: boolean;
  tokensBefore: number;
  fileOps: unknown;
  settings: { reserveTokens: number; keepRecentTokens: number };
};
type Event = { preparation: Preparation; customInstructions?: string; signal: AbortSignal };
type Context = {
  model?: { contextWindow: number; maxTokens?: number };
  ui: { notify(message: string, level: "warning"): void };
};
type Result = {
  status: "classified" | "fallback";
  blocks: { id: string; retention: string; reason: string }[];
  retained_text: string;
  elapsed_ms: number;
};
type Compaction = {
  summary: string;
  firstKeptEntryId: string;
  tokensBefore: number;
  details: unknown;
};
type ExtensionAPI = {
  on(name: "session_before_compact", handler: (event: Event, ctx: Context) => Promise<{ compaction: Compaction } | undefined>): void;
};

// Pi's loader can preserve the global symlink URL; resolve its actual source
// before locating the shared core beside the integration directory.
const sourceURL = pathToFileURL(realpathSync(fileURLToPath(import.meta.url)));
const corePath = fileURLToPath(new URL("../../scripts/compaction_retention.py", sourceURL));
const serialize = (value: unknown): string => JSON.stringify(value, (_key, item) => item instanceof Set ? [...item] : item);

// Export discussion content only. Private reasoning, signatures, provider usage,
// and runtime system/developer instructions do not belong in classification.
function normalize(message: Message, id: string): Block | undefined {
  if (message.role === "system" || message.role === "developer") return;
  const knownRole = ["user", "assistant", "toolResult"].includes(message.role);
  if (!knownRole) throw new Error("unsupported message role");
  const content = typeof message.content === "string" ? message.content : Array.isArray(message.content) ? message.content.flatMap<Record<string, unknown>>((part) => {
    if (!part || typeof part !== "object") throw new Error("unsupported message content");
    if (part.type === "thinking") return [];
    if (part.type === "text" && typeof part.text === "string") return [{ type: "text", text: part.text }];
    if (part.type === "toolCall" && typeof part.id === "string" && typeof part.name === "string" && part.arguments && typeof part.arguments === "object") return [{ type: "toolCall", id: part.id, name: part.name, arguments: part.arguments }];
    throw new Error("unsupported message content");
  }) : (() => { throw new Error("unsupported message content"); })();
  const discussion = { role: message.role, content, ...(message.role === "toolResult" ? {
    toolCallId: message.toolCallId, toolName: message.toolName, isError: message.isError,
  } : {}) };
  return {
    id,
    role: message.role === "toolResult" ? "tool" : knownRole ? message.role : "system",
    text: serialize(discussion),
    protected: message.role === "user",
  };
}

function classify(blocks: Block[], objective: string | undefined, signal: AbortSignal): Promise<Result> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new Error("aborted")); return; }
    // stdin avoids shell interpolation and temporary copies of session content.
    // Credentials remain in the shared core's local configuration, not argv/output.
    const child = spawn("python3", [corePath], { stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    const abort = () => child.kill("SIGKILL");
    signal.addEventListener("abort", abort, { once: true });
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => { stdout += chunk; });
    // Consume stderr without exposing provider errors or private session data.
    child.stderr.resume();
    child.stdin.on("error", () => {});
    child.on("error", (error) => { signal.removeEventListener("abort", abort); reject(error); });
    child.on("close", (code) => {
      signal.removeEventListener("abort", abort);
      if (signal.aborted || code !== 0) { reject(new Error("classifier unavailable")); return; }
      try { resolve(JSON.parse(stdout)); } catch { reject(new Error("invalid classifier response")); }
    });
    child.stdin.end(JSON.stringify({ blocks, objective }));
  });
}

export default function jevCompaction(pi: ExtensionAPI) {
  pi.on("session_before_compact", async (event, ctx) => {
    const preparation = event.preparation;
    try {
      const blocks: Block[] = [];
      if (preparation.previousSummary) blocks.push({ id: "previous-summary", role: "system", text: preparation.previousSummary, protected: true });
      if (event.customInstructions) blocks.push({ id: "custom-instructions", role: "user", text: event.customInstructions, protected: true });
      const fileOps = JSON.parse(serialize(preparation.fileOps));
      blocks.push({ id: "file-operations", role: "system", text: serialize(fileOps), protected: true });
      preparation.messagesToSummarize.forEach((message, index) => { const block = normalize(message, `history-${index}`); if (block) blocks.push(block); });
      preparation.turnPrefixMessages.forEach((message, index) => { const block = normalize(message, `turn-prefix-${index}`); if (block) blocks.push(block); });
      const result = await classify(blocks, event.customInstructions, event.signal);
      if (event.signal.aborted) return;
      if (result.status !== "classified" || !Array.isArray(result.blocks) || typeof result.retained_text !== "string" || !result.retained_text.trim()) throw new Error("fallback");
      const ids = new Set(result.blocks.map((block) => block.id));
      if (result.blocks.length !== blocks.length || ids.size !== blocks.length || blocks.some((block) => !ids.has(block.id))) throw new Error("invalid classification coverage");
      // Even a malformed classifier response cannot silently remove protected text.
      if (blocks.some((block) => block.protected && !result.retained_text.includes(block.text))) throw new Error("protected content missing");

      // Pi exposes no tokenizer in ExtensionContext. Match its native chars/4
      // summary estimate, bounded by native settings and model headroom. This is
      // an estimate, not a provider-token guarantee; native overflow recovery remains.
      const estimatedSummaryTokens = Math.ceil(result.retained_text.length / 4);
      const { reserveTokens, keepRecentTokens } = preparation.settings;
      const contextWindow = ctx.model?.contextWindow;
      // Installed Pi compaction.js:461 uses 0.8*reserveTokens for history;
      // :625 uses 0.5*reserveTokens for a split-turn prefix, each model-capped.
      const modelCap = ctx.model?.maxTokens && ctx.model.maxTokens > 0 ? ctx.model.maxTokens : Infinity;
      const summaryBudget = Math.min(Math.floor(0.8 * reserveTokens), modelCap) +
        (preparation.isSplitTurn ? Math.min(Math.floor(0.5 * reserveTokens), modelCap) : 0);
      if (!contextWindow || !Number.isFinite(reserveTokens) || !Number.isFinite(keepRecentTokens) || reserveTokens <= 0 || keepRecentTokens < 0 ||
          estimatedSummaryTokens > summaryBudget || estimatedSummaryTokens + keepRecentTokens + reserveTokens > contextWindow) throw new Error("summary exceeds native budget");
      return { compaction: {
        summary: result.retained_text,
        firstKeptEntryId: preparation.firstKeptEntryId,
        tokensBefore: preparation.tokensBefore,
        details: { source: "jev-extractive", fileOps, elapsed_ms: result.elapsed_ms, classification: result.blocks },
      } };
    } catch {
      if (!event.signal.aborted) ctx.ui.notify("Jev compaction unavailable or outside the native budget; using Pi compaction.", "warning");
      return;
    }
  });
}
