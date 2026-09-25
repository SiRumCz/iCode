import { AcpProcess } from "./process";

export type JsonRpcId = number | string;

export interface SessionUpdate {
  sessionUpdate?: string;
  content?: unknown;
  title?: string;
  rawInput?: unknown;
  status?: string;
  toolCallId?: string;
  interactionId?: string;
  toolName?: string;
  toolArgs?: unknown;
  message?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  modelCalls?: number;
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
}

export class AcpClient {
  private nextId = 1;
  private readonly pending = new Map<JsonRpcId, Pending>();
  private readonly unsubscribe: () => void;

  constructor(
    private readonly process: AcpProcess,
    private readonly opts: {
      trace: boolean;
      onLog: (line: string) => void;
      onNotification: (method: string, params: unknown) => void;
    }
  ) {
    this.unsubscribe = process.onLine((line) => this.onLine(line));
  }

  dispose(): void {
    this.unsubscribe();
    for (const [, p] of this.pending) {
      p.reject(new Error("ACP client disposed"));
    }
    this.pending.clear();
  }

  request(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextId++;
    const payload = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };
    const line = JSON.stringify(payload);
    if (this.opts.trace) {
      this.opts.onLog(`→ ${line}`);
    }
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.process.write(line);
      } catch (err) {
        this.pending.delete(id);
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    });
  }

  private onLine(line: string): void {
    if (this.opts.trace) {
      this.opts.onLog(`← ${line}`);
    }
    let msg: {
      id?: JsonRpcId;
      method?: string;
      params?: unknown;
      result?: unknown;
      error?: { code?: number; message?: string };
    };
    try {
      msg = JSON.parse(line) as typeof msg;
    } catch {
      this.opts.onLog(`Invalid JSON from ACP: ${line}`);
      return;
    }
    if (msg.id !== undefined && (msg.result !== undefined || msg.error)) {
      const pending = this.pending.get(msg.id);
      if (!pending) {
        return;
      }
      this.pending.delete(msg.id);
      if (msg.error) {
        pending.reject(
          new Error(msg.error.message ?? `ACP error ${msg.error.code}`)
        );
      } else {
        pending.resolve(msg.result);
      }
      return;
    }
    if (msg.method) {
      this.opts.onNotification(msg.method, msg.params ?? {});
    }
  }
}
