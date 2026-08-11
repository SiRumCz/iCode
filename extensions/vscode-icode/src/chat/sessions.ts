import * as vscode from "vscode";

export interface SessionRow {
  sessionId: string;
  title?: string;
  updatedAt?: string;
  model?: string;
}

export class SessionItem extends vscode.TreeItem {
  constructor(public readonly sessionId: string, title: string, model?: string) {
    super(title || sessionId, vscode.TreeItemCollapsibleState.None);
    // TreeItem.id survives Cursor/VS Code context-menu serialization;
    // custom fields like sessionId may not.
    this.id = sessionId;
    const short = sessionId.length > 8 ? sessionId.slice(-8) : sessionId;
    this.description = model ? `${model} · ${short}` : short;
    this.contextValue = "icodeSession";
    this.tooltip = `${title || sessionId}\n${sessionId}\nClick to load`;
    // Do NOT set TreeItem.command — Cursor/VS Code may wrap it as a
    // transient `__vsc…` command that breaks after reload/reinstall.
    // Loading is handled via TreeView.onDidChangeSelection instead.
    this.iconPath = new vscode.ThemeIcon("comment-discussion");
  }
}

export class SessionsTreeProvider
  implements vscode.TreeDataProvider<SessionItem>
{
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<
    SessionItem | undefined | null | void
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  /** Hide ids immediately after a successful delete until list catches up. */
  private readonly pendingDeletes = new Set<string>();

  constructor(private readonly loader: () => Promise<SessionRow[]>) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  /** Optimistically hide a session row, then refresh from the server. */
  markDeleted(sessionId: string): void {
    this.pendingDeletes.add(sessionId);
    this.refresh();
  }

  getTreeItem(element: SessionItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<SessionItem[]> {
    const rows = await this.loader();
    for (const id of [...this.pendingDeletes]) {
      if (!rows.some((r) => r.sessionId === id)) {
        this.pendingDeletes.delete(id);
      }
    }
    return rows
      .filter((r) => r.sessionId && !this.pendingDeletes.has(r.sessionId))
      .map(
        (r) => new SessionItem(r.sessionId, r.title || r.sessionId, r.model)
      );
  }
}

/** Resolve a session id from TreeItem args (live instance or serialized). */
export function sessionIdFromArg(arg?: unknown): string | undefined {
  if (!arg) {
    return undefined;
  }
  if (typeof arg === "string") {
    const s = arg.trim();
    return s || undefined;
  }
  if (typeof arg !== "object") {
    return undefined;
  }
  const obj = arg as {
    sessionId?: unknown;
    id?: unknown;
  };
  if (typeof obj.sessionId === "string" && obj.sessionId.trim()) {
    return obj.sessionId.trim();
  }
  if (typeof obj.id === "string" && obj.id.trim()) {
    return obj.id.trim();
  }
  return undefined;
}
