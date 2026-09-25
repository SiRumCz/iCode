/**
 * Lightweight unit test for ACP client framing (no VS Code runtime).
 * Run: npm test
 */
import assert from "assert";
import { EventEmitter } from "events";

class FakeProcess {
  private readonly emitter = new EventEmitter();
  public writes: string[] = [];

  onLine(listener: (line: string) => void): () => void {
    this.emitter.on("line", listener);
    return () => this.emitter.off("line", listener);
  }

  write(line: string): void {
    this.writes.push(line);
  }

  emitLine(line: string): void {
    this.emitter.emit("line", line);
  }
}

// Inline minimal client logic mirror for Node without vscode import.
class MiniClient {
  private nextId = 1;
  private pending = new Map<
    number,
    { resolve: (v: unknown) => void; reject: (e: Error) => void }
  >();
  constructor(private readonly proc: FakeProcess) {
    proc.onLine((line) => this.onLine(line));
  }
  request(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextId++;
    this.proc.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }
  private onLine(line: string): void {
    const msg = JSON.parse(line) as {
      id?: number;
      result?: unknown;
      error?: { message?: string };
      method?: string;
    };
    if (msg.id !== undefined && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      if (msg.error) {
        p.reject(new Error(msg.error.message ?? "error"));
      } else {
        p.resolve(msg.result);
      }
    }
  }
}

async function main(): Promise<void> {
  const proc = new FakeProcess();
  const client = new MiniClient(proc);
  const p = client.request("initialize", {});
  assert.equal(proc.writes.length, 1);
  const sent = JSON.parse(proc.writes[0]) as { id: number; method: string };
  assert.equal(sent.method, "initialize");
  proc.emitLine(
    JSON.stringify({
      jsonrpc: "2.0",
      id: sent.id,
      result: { protocolVersion: 1, agentInfo: { name: "iCode", version: "0.1.0" } },
    })
  );
  const result = (await p) as { agentInfo: { name: string } };
  assert.equal(result.agentInfo.name, "iCode");
  console.log("acpClient.test OK");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
