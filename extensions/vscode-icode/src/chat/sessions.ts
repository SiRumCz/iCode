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
    this.description = model ?? "";
    this.contextValue = "icodeSession";
    this.tooltip = `${title || sessionId}\n${sessionId}`;
    this.command = {
      command: "icode.loadSession",
      title: "Load Session",
      // Must be JSON-serializable — passing `this` breaks as `__vsc…` commands.
      arguments: [sessionId],
    };
    this.iconPath = new vscode.ThemeIcon("comment-discussion");
  }
}

export class SessionsTreeProvider
  implements vscode.TreeDataProvider<SessionItem>
{
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<
    SessionItem | undefined | void
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private readonly loader: () => Promise<SessionRow[]>) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: SessionItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<SessionItem[]> {
    const rows = await this.loader();
    return rows.map(
      (r) =>
        new SessionItem(
          r.sessionId,
          r.title || r.sessionId,
          r.model
        )
    );
  }
}
