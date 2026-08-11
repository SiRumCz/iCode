import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import * as os from "os";
import * as vscode from "vscode";
import { IcodeConfig } from "../config";

export class AcpProcess {
  private child: ChildProcessWithoutNullStreams | undefined;
  private buffer = "";
  private readonly lineListeners = new Set<(line: string) => void>();

  constructor(
    private readonly config: IcodeConfig,
    private readonly apiKey: string,
    private readonly output: vscode.OutputChannel
  ) {}

  async start(): Promise<void> {
    if (this.child) {
      return;
    }
    const env = this.config.childEnv(this.apiKey);
    // Extension hosts often have cwd=/ ; SDK relative ./logs would become /logs.
    const cwd =
      vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      os.homedir();
    this.output.appendLine(
      `Spawning: ${this.config.command} ${this.config.args.join(" ")} (cwd=${cwd})`
    );
    this.child = spawn(this.config.command, this.config.args, {
      env,
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child.stdout.setEncoding("utf8");
    this.child.stderr.setEncoding("utf8");
    this.child.stdout.on("data", (chunk: string) => this.onStdout(chunk));
    this.child.stderr.on("data", (chunk: string) => {
      this.output.appendLine(`[stderr] ${chunk.trimEnd()}`);
    });
    this.child.on("exit", (code, signal) => {
      this.output.appendLine(
        `ACP process exited code=${code} signal=${signal}`
      );
      this.child = undefined;
    });
    this.child.on("error", (err) => {
      this.output.appendLine(`ACP process error: ${err.message}`);
      this.child = undefined;
    });
  }

  onLine(listener: (line: string) => void): () => void {
    this.lineListeners.add(listener);
    return () => this.lineListeners.delete(listener);
  }

  write(line: string): void {
    if (!this.child?.stdin.writable) {
      throw new Error("ACP process is not running");
    }
    this.child.stdin.write(line.endsWith("\n") ? line : `${line}\n`);
  }

  async stop(): Promise<void> {
    const child = this.child;
    this.child = undefined;
    if (!child) {
      return;
    }
    child.stdin.end();
    child.kill();
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk;
    let idx: number;
    while ((idx = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line) {
        continue;
      }
      for (const listener of this.lineListeners) {
        listener(line);
      }
    }
  }
}
