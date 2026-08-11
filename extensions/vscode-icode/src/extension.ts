import * as vscode from "vscode";
import { AcpClient, SessionUpdate } from "./acp/client";
import { AcpProcess } from "./acp/process";
import { ChatViewProvider } from "./chat/panel";
import { SessionsTreeProvider, SessionItem, sessionIdFromArg, collectSessionIds } from "./chat/sessions";
import { IcodeConfig, SECRET_API_KEY } from "./config";

let extContext: vscode.ExtensionContext;
let processHandle: AcpProcess | undefined;
let client: AcpClient | undefined;
let status: vscode.StatusBarItem;
let output: vscode.OutputChannel;
let chat: ChatViewProvider;
let sessions: SessionsTreeProvider;
let sessionsView: vscode.TreeView<SessionItem>;
let currentSessionId: string | undefined;
let attachedContext: string | undefined;
/** Skip selection→load while a delete confirmation/request is in flight. */
let suppressSessionLoad = false;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  extContext = context;
  output = vscode.window.createOutputChannel("iCode ACP");
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = "icode.openChat";
  status.text = "$(comment-discussion) iCode";
  status.tooltip = "Open iCode Chat";
  status.show();

  chat = new ChatViewProvider(context.extensionUri, {
    onSend: (text) => void sendPrompt(text),
    onCancel: () => void cancelPrompt(),
    onApprove: (interactionId, approved) =>
      void approvePermission(interactionId, approved),
    onClearAttachment: () => clearAttachment(),
  });

  sessions = new SessionsTreeProvider(() => listSessions());

  sessionsView = vscode.window.createTreeView("icode.sessionsView", {
    treeDataProvider: sessions,
    showCollapseAll: false,
    canSelectMany: true,
  });
  sessionsView.onDidChangeSelection((e) => {
    if (suppressSessionLoad) {
      return;
    }
    // Multi-select is for bulk delete — only auto-load a single click/selection.
    if (e.selection.length !== 1) {
      return;
    }
    const sessionId = sessionIdFromArg(e.selection[0]);
    if (sessionId) {
      void loadSession(sessionId);
    }
  });

  context.subscriptions.push(
    output,
    status,
    sessionsView,
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chat),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("icode.submitKeybinding")) {
        chat.pushSettings();
      }
    }),
    vscode.commands.registerCommand("icode.openChat", () =>
      vscode.commands.executeCommand("icode.chatView.focus")
    ),
    vscode.commands.registerCommand("icode.newSession", () => void newSession()),
    vscode.commands.registerCommand("icode.restartAgent", () => void restartAgent()),
    vscode.commands.registerCommand("icode.setApiKey", () => void setApiKey()),
    vscode.commands.registerCommand("icode.showDiff", () => void showDiff()),
    vscode.commands.registerCommand("icode.attachActiveFile", () =>
      void attachActiveFile()
    ),
    vscode.commands.registerCommand("icode.addSelectionToChat", () =>
      void addSelectionToChat()
    ),
    vscode.commands.registerCommand("icode.refreshSessions", () => sessions.refresh()),
    vscode.commands.registerCommand(
      "icode.loadSession",
      (arg?: unknown) => void loadSession(resolveSessionId(arg))
    ),
    vscode.commands.registerCommand(
      "icode.deleteSession",
      (arg?: unknown, selected?: unknown) => void deleteSession(arg, selected)
    )
  );
}

export async function deactivate(): Promise<void> {
  await disposeClient();
}

async function setApiKey(): Promise<void> {
  const value = await vscode.window.showInputBox({
    prompt: "iCode API key",
    password: true,
    ignoreFocusOut: true,
  });
  if (value === undefined) {
    return;
  }
  await extContext.secrets.store(SECRET_API_KEY, value.trim());
  vscode.window.showInformationMessage("iCode API key saved.");
  await restartAgent();
}

function clearAttachment(): void {
  attachedContext = undefined;
  chat.setAttachment(undefined);
}

function fenceLang(languageId: string): string {
  switch (languageId) {
    case "typescriptreact":
      return "tsx";
    case "javascriptreact":
      return "jsx";
    case "shellscript":
      return "bash";
    case "jsonc":
      return "json";
    default:
      return languageId || "";
  }
}

function setEditorAttachment(
  doc: vscode.TextDocument,
  selection: vscode.Selection | undefined,
  text: string,
  selectionOnly: boolean
): void {
  const clipped = text.length > 60_000 ? `${text.slice(0, 60_000)}\n…` : text;
  const path = vscode.workspace.asRelativePath(doc.uri);
  const hasSelection = Boolean(selection && !selection.isEmpty);
  let range = "";
  if (hasSelection && selection) {
    const start = selection.start.line + 1;
    const end = selection.end.line + 1;
    range = start === end ? `:${start}` : `:${start}-${end}`;
  }
  const lang = fenceLang(doc.languageId);
  attachedContext = `[Attached: ${path}${range}]\n\`\`\`${lang}\n${clipped}\n\`\`\``;
  const label = hasSelection
    ? `${path}${range} (selection)`
    : `${path} (file)`;
  chat.setAttachment(label);
  if (!selectionOnly) {
    chat.postSystem(`Attached ${label}.`);
  }
}

async function focusChat(): Promise<void> {
  await vscode.commands.executeCommand("icode.chatView.focus");
}

async function addSelectionToChat(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    vscode.window.showWarningMessage("Select text in the editor first.");
    return;
  }
  const text = editor.document.getText(editor.selection);
  if (!text.trim()) {
    vscode.window.showWarningMessage("Selection is empty.");
    return;
  }
  setEditorAttachment(editor.document, editor.selection, text, true);
  await focusChat();
}

async function attachActiveFile(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("No active editor to attach.");
    return;
  }
  const selection = editor.selection;
  const text =
    selection && !selection.isEmpty
      ? editor.document.getText(selection)
      : editor.document.getText();
  setEditorAttachment(editor.document, selection, text, false);
  await focusChat();
}

async function ensureClient(): Promise<AcpClient> {
  if (client) {
    return client;
  }
  const cfg = IcodeConfig.fromWorkspace();
  const apiKey = (await extContext.secrets.get(SECRET_API_KEY)) ?? "";
  processHandle = new AcpProcess(cfg, apiKey, output);
  await processHandle.start();
  client = new AcpClient(processHandle, {
    trace: cfg.trace,
    onLog: (line) => output.appendLine(line),
    onNotification: (method, params) => {
      if (method === "session/update") {
        handleSessionUpdate(
          params as { sessionId?: string; update?: SessionUpdate }
        );
      }
    },
  });
  const init = await client.request("initialize", {});
  const info = (
    init as { agentInfo?: { name?: string; version?: string } }
  ).agentInfo;
  status.text = `$(comment-discussion) iCode ${info?.version ?? ""}`.trim();
  status.tooltip = `${info?.name ?? "iCode"} connected`;
  output.appendLine(`Initialized ${JSON.stringify(info)}`);
  return client;
}

async function disposeClient(): Promise<void> {
  try {
    if (client && currentSessionId) {
      await client.request("session/close", { sessionId: currentSessionId });
    }
    if (client) {
      await client.request("shutdown", {});
    }
  } catch {
    /* ignore */
  }
  client = undefined;
  currentSessionId = undefined;
  await processHandle?.stop();
  processHandle = undefined;
  status.text = "$(comment-discussion) iCode";
  status.tooltip = "iCode disconnected";
}

async function restartAgent(): Promise<void> {
  await disposeClient();
  chat.postSystem("Agent stopped. Send a message to reconnect.");
  vscode.window.showInformationMessage(
    "iCode agent stopped. Send a message to reconnect."
  );
}

async function workspaceCwd(): Promise<string> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    throw new Error("Open a workspace folder to use iCode.");
  }
  return folder.uri.fsPath;
}

async function ensureSession(): Promise<{
  client: AcpClient;
  sessionId: string;
}> {
  const c = await ensureClient();
  if (!currentSessionId) {
    const cwd = await workspaceCwd();
    const result = (await c.request("session/new", { cwd })) as {
      sessionId: string;
    };
    currentSessionId = result.sessionId;
    chat.postSystem(`Session ${currentSessionId}`);
    sessions.refresh();
  }
  return { client: c, sessionId: currentSessionId };
}

async function newSession(): Promise<void> {
  const c = await ensureClient();
  if (currentSessionId) {
    try {
      await c.request("session/close", { sessionId: currentSessionId });
    } catch {
      /* ignore */
    }
  }
  const cwd = await workspaceCwd();
  const result = (await c.request("session/new", { cwd })) as {
    sessionId: string;
  };
  currentSessionId = result.sessionId;
  chat.clear();
  chat.postSystem(`New session ${currentSessionId}`);
  sessions.refresh();
}

function resolveSessionId(arg?: unknown): string | undefined {
  const fromArg = sessionIdFromArg(arg);
  if (fromArg) {
    return fromArg;
  }
  return sessionIdFromArg(sessionsView?.selection?.[0]);
}

async function loadSession(sessionId?: string): Promise<void> {
  if (!sessionId) {
    return;
  }
  const c = await ensureClient();
  const result = (await c.request("session/load", { sessionId })) as {
    sessionId?: string;
    title?: string;
    model?: string;
    messages?: Array<{ role?: string; content?: string }>;
  };
  currentSessionId = result.sessionId || sessionId;
  const messages = result.messages ?? [];
  chat.loadHistory(messages);
  const title = result.title || currentSessionId;
  chat.postSystem(
    messages.length
      ? `Loaded “${title}” (${messages.length} messages)`
      : `Loaded “${title}” (no messages yet)`
  );
}

async function deleteSession(arg?: unknown, selected?: unknown): Promise<void> {
  const sessionIds = collectSessionIds(arg, selected, sessionsView?.selection);
  if (sessionIds.length === 0) {
    vscode.window.showWarningMessage(
      "No session selected to delete. Select one or more sessions first."
    );
    return;
  }
  const summary =
    sessionIds.length === 1
      ? `Delete session “${sessionIds[0]}”?`
      : `Delete ${sessionIds.length} sessions?`;
  const detail =
    sessionIds.length <= 5
      ? sessionIds.join("\n")
      : `${sessionIds.slice(0, 5).join("\n")}\n…and ${sessionIds.length - 5} more`;
  suppressSessionLoad = true;
  try {
    const choice = await vscode.window.showWarningMessage(
      `${summary}\n${detail}\nThis cannot be undone.`,
      { modal: true },
      "Delete"
    );
    if (choice !== "Delete") {
      return;
    }
    const c = await ensureClient();
    const failed: string[] = [];
    let clearedCurrent = false;
    for (const sessionId of sessionIds) {
      try {
        await c.request("session/delete", { sessionId });
        sessions.markDeleted(sessionId);
        if (currentSessionId === sessionId) {
          currentSessionId = undefined;
          clearedCurrent = true;
        }
      } catch (err) {
        failed.push(sessionId);
        output.appendLine(`delete ${sessionId}: ${err}`);
      }
    }
    if (clearedCurrent) {
      chat.clear();
      chat.postSystem(
        sessionIds.length === 1
          ? `Deleted session ${sessionIds[0]}`
          : `Deleted ${sessionIds.length - failed.length} sessions`
      );
    }
    const deleted = sessionIds.length - failed.length;
    if (failed.length === 0) {
      vscode.window.showInformationMessage(
        deleted === 1 ? "Deleted 1 session." : `Deleted ${deleted} sessions.`
      );
    } else {
      vscode.window.showWarningMessage(
        `Deleted ${deleted}, failed ${failed.length}. See “iCode ACP” output.`
      );
    }
    sessions.refresh();
  } finally {
    suppressSessionLoad = false;
  }
}

async function listSessions(): Promise<
  Array<{
    sessionId: string;
    title?: string;
    updatedAt?: string;
    model?: string;
  }>
> {
  try {
    const c = await ensureClient();
    const result = (await c.request("session/list", {})) as {
      sessions?: Array<{
        sessionId: string;
        title?: string;
        updatedAt?: string;
        model?: string;
      }>;
    };
    return result.sessions ?? [];
  } catch (err) {
    output.appendLine(`session/list failed: ${err}`);
    return [];
  }
}

async function sendPrompt(text: string): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) {
    return;
  }
  chat.postUser(trimmed);
  chat.setBusy(true);
  try {
    const { client: c, sessionId } = await ensureSession();
    const promptBlocks: Array<Record<string, unknown>> = [
      { type: "text", text: trimmed },
    ];
    if (attachedContext) {
      promptBlocks.unshift({ type: "text", text: attachedContext });
      clearAttachment();
    }
    const cwd = await workspaceCwd();
    const result = (await c.request("session/prompt", {
      sessionId,
      cwd,
      prompt: promptBlocks,
    })) as {
      ok?: boolean;
      error?: string;
      diff?: {
        files?: Array<{ path: string; kind: string }>;
      };
    };
    if (result.ok === false) {
      chat.postSystem(`Error: ${result.error ?? "turn failed"}`);
    }
    if (result.diff?.files?.length) {
      chat.postSystem(
        `Mutations: ${result.diff.files.map((f) => f.path).join(", ")} — run iCode: Show Latest Diff`
      );
    }
  } catch (err) {
    chat.postSystem(`Failed: ${err}`);
    output.appendLine(String(err));
  } finally {
    chat.setBusy(false);
    sessions.refresh();
  }
}

async function cancelPrompt(): Promise<void> {
  if (!client || !currentSessionId) {
    return;
  }
  await client.request("session/cancel", { sessionId: currentSessionId });
  chat.postSystem("Cancel requested.");
}

async function approvePermission(
  interactionId: string,
  approved: boolean
): Promise<void> {
  if (!client || !currentSessionId) {
    return;
  }
  await client.request("session/approve", {
    sessionId: currentSessionId,
    interactionId,
    approved,
  });
  chat.postSystem(approved ? "Approved." : "Denied.");
}

async function showDiff(): Promise<void> {
  if (!client || !currentSessionId) {
    vscode.window.showWarningMessage("No active iCode session.");
    return;
  }
  const result = (await client.request("session/diff", {
    sessionId: currentSessionId,
  })) as {
    files?: Array<{
      path: string;
      kind: string;
      before?: string;
      after?: string;
    }>;
    summary?: string;
  };
  const files = result.files ?? [];
  if (!files.length) {
    vscode.window.showInformationMessage("No recorded mutations.");
    if (result.summary) {
      output.appendLine(result.summary);
    }
    return;
  }
  for (const file of files.slice(-5)) {
    const left = await vscode.workspace.openTextDocument({
      content: file.before ?? "",
      language: "plaintext",
    });
    const right = await vscode.workspace.openTextDocument({
      content: file.after ?? `(${file.kind}) ${file.path}`,
      language: "plaintext",
    });
    await vscode.commands.executeCommand(
      "vscode.diff",
      left.uri,
      right.uri,
      `iCode: ${file.path}`
    );
  }
}

function handleSessionUpdate(params: {
  sessionId?: string;
  update?: SessionUpdate;
}): void {
  const update = params.update;
  if (!update) {
    return;
  }
  switch (update.sessionUpdate) {
    case "agent_message_chunk": {
      const text = extractText(update.content);
      if (text) {
        chat.appendAssistant(text);
      }
      break;
    }
    case "agent_thought_chunk": {
      const text = extractText(update.content);
      if (text) {
        chat.appendThought(text);
      }
      break;
    }
    case "tool_call":
      chat.postTool(
        `▶ ${update.title ?? "tool"}`,
        typeof update.rawInput === "string"
          ? update.rawInput
          : JSON.stringify(update.rawInput ?? {})
      );
      break;
    case "tool_call_update":
      chat.postTool(`■ tool ${update.status ?? "done"}`, "");
      break;
    case "usage_update":
      chat.postSystem(
        `Tokens in=${update.inputTokens ?? 0} out=${update.outputTokens ?? 0}`
      );
      break;
    case "request_permission": {
      const interactionId = String(update.interactionId ?? "");
      const message = String(
        update.message ?? `Approve ${update.toolName ?? "tool"}?`
      );
      chat.postPermission(interactionId, message);
      void vscode.window
        .showInformationMessage(message, "Allow", "Deny")
        .then((choice) => {
          if (choice === "Allow") {
            void approvePermission(interactionId, true);
          } else if (choice === "Deny") {
            void approvePermission(interactionId, false);
          }
        });
      break;
    }
    default:
      break;
  }
}

function extractText(content: unknown): string {
  if (!content) {
    return "";
  }
  if (typeof content === "string") {
    return content;
  }
  if (typeof content === "object" && content !== null && "text" in content) {
    return String((content as { text: unknown }).text ?? "");
  }
  return "";
}
