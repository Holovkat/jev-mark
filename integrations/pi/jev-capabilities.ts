/** Advisory per-turn capability routing. Native discovery remains authoritative. */
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

type Skill = { name: string; description: string; filePath: string };
type Event = { prompt: string; systemPrompt: string; systemPromptOptions?: { skills?: Skill[] }; signal?: AbortSignal };
type Context = { cwd: string; sessionManager?: { getSessionId(): string }; signal?: AbortSignal };
type API = {
  on(event: "before_agent_start", callback: (event: Event, ctx: Context) => Promise<{ systemPrompt: string } | undefined>): void;
  getAllTools(): { name: string; description: string }[];
  getActiveTools(): string[];
  exec(command: string, args: string[], options: { signal?: AbortSignal; timeout: number }): Promise<{ stdout: string; code: number; killed: boolean }>;
};
const sourceURL = pathToFileURL(realpathSync(fileURLToPath(import.meta.url)));
const hook = fileURLToPath(new URL("../capabilities/hook.py", sourceURL));

export default function (pi: API) {
  pi.on("before_agent_start", async (event, ctx) => {
    let directory: string | undefined;
    try {
      directory = await mkdtemp(join(tmpdir(), "jev-capabilities-"));
      const packetPath = join(directory, "packet.json");
      const active = new Set(pi.getActiveTools());
      const loaded = event.systemPromptOptions?.skills;
      const packet = {
        prompt: event.prompt, cwd: ctx.cwd,
        session_id: ctx.sessionManager?.getSessionId() ?? "unknown",
        ...(loaded ? { skills: loaded.map(s => ({ id: s.name, name: s.name, description: s.description, path: s.filePath })) } : {}),
        catalogue_complete: loaded !== undefined,
        tools: pi.getAllTools().map(t => ({ id: t.name, name: t.name, description: t.description, available: active.has(t.name) })),
      };
      // pi.exec has no stdin option. Keep request data out of process arguments;
      // this adapter-owned 0600 sidecar is deleted on every completion path.
      await writeFile(packetPath, JSON.stringify(packet), { mode: 0o600 });
      const result = await pi.exec("python3", [hook, "--harness", "pi", "--input-file", packetPath, "--timeout", "180"], {
        signal: event.signal ?? ctx.signal, timeout: 180000,
      });
      if (result.code !== 0 || result.killed) return;
      const parsed = JSON.parse(result.stdout);
      const context = parsed.hookSpecificOutput?.additionalContext ?? parsed.additionalContext;
      if (typeof context !== "string" || !context.trim()) return;
      return { systemPrompt: `${event.systemPrompt}\n\n${context}` };
    } catch {
      return; // Outage preserves normal native discovery and the original prompt.
    } finally {
      if (directory) await rm(directory, { recursive: true, force: true });
    }
  });
}
