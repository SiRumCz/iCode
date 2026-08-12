import * as vscode from "vscode";
import { readSubmitKeybinding, SubmitKeybinding } from "../config";

export interface ChatHandlers {
  onSend: (text: string) => void;
  onCancel: () => void;
  onApprove: (interactionId: string, approved: boolean) => void;
  onClearAttachment?: () => void;
  onPickSession?: () => void;
  onNewSession?: () => void;
}

interface TranscriptLine {
  role: "user" | "assistant" | "system" | "tool" | "thought";
  content: string;
  title?: string;
}

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "icode.chatView";
  public static readonly editorViewType = "icode.chatEditor";

  private view?: vscode.WebviewView;
  private editorPanel?: vscode.WebviewPanel;
  private readonly targets = new Set<vscode.Webview>();
  private assistantOpen = false;
  private thoughtOpen = false;
  private wiredView = false;
  /** Survives webview recreation when the sidebar is hidden/shown. */
  private transcript: TranscriptLine[] = [];
  private openAssistant?: TranscriptLine;
  private openThought?: TranscriptLine;
  private attachmentLabel = "";
  private sessionTitle = "";

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly handlers: ChatHandlers
  ) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this.view = webviewView;
    // Keep DOM/JS state when switching Activity Bar views (Explorer ↔ iCode).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (webviewView as any).retainContextWhenHidden = true;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    if (!this.wiredView) {
      this.wiredView = true;
      webviewView.webview.html = this.html(webviewView.webview);
      this.attachWebview(webviewView.webview);
      webviewView.onDidDispose(() => {
        this.wiredView = false;
        this.detachWebview(webviewView.webview);
        this.view = undefined;
      });
    } else {
      this.pushSettings();
      this.restoreTranscriptTo(webviewView.webview);
    }
  }

  /** Open (or reveal) chat as a tab in the active editor group. */
  openInEditor(column: vscode.ViewColumn = vscode.ViewColumn.Active): void {
    if (this.editorPanel) {
      this.editorPanel.reveal(column, false);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      ChatViewProvider.editorViewType,
      "iCode Chat",
      { viewColumn: column, preserveFocus: false },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [this.extensionUri],
      }
    );
    this.editorPanel = panel;
    panel.webview.html = this.html(panel.webview);
    this.attachWebview(panel.webview);
    panel.onDidDispose(() => {
      this.detachWebview(panel.webview);
      if (this.editorPanel === panel) {
        this.editorPanel = undefined;
      }
    });
  }

  private attachWebview(webview: vscode.Webview): void {
    this.targets.add(webview);
    webview.onDidReceiveMessage(
      (msg: {
        type?: string;
        text?: string;
        interactionId?: string;
        approved?: boolean;
      }) => {
        if (msg.type === "send" && msg.text) {
          this.assistantOpen = false;
          this.thoughtOpen = false;
          this.handlers.onSend(msg.text);
        } else if (msg.type === "cancel") {
          this.handlers.onCancel();
        } else if (msg.type === "approve" && msg.interactionId) {
          this.handlers.onApprove(msg.interactionId, Boolean(msg.approved));
        } else if (msg.type === "clearAttachment") {
          this.handlers.onClearAttachment?.();
        } else if (msg.type === "pickSession") {
          this.handlers.onPickSession?.();
        } else if (msg.type === "newSession") {
          this.handlers.onNewSession?.();
        } else if (msg.type === "ready") {
          this.pushSettingsTo(webview);
          this.restoreTranscriptTo(webview);
          this.pushSessionInfoTo(webview);
        }
      }
    );
  }

  private detachWebview(webview: vscode.Webview): void {
    this.targets.delete(webview);
  }

  /** Push current submit keybinding into all chat surfaces. */
  pushSettings(): void {
    const mode = readSubmitKeybinding();
    this.post({ type: "settings", submitKeybinding: mode });
  }

  private pushSettingsTo(webview: vscode.Webview): void {
    const mode = readSubmitKeybinding();
    void webview.postMessage({
      type: "settings",
      submitKeybinding: mode,
    });
  }

  private finalizeOpenBubbles(): void {
    this.openAssistant = undefined;
    this.openThought = undefined;
    this.assistantOpen = false;
    this.thoughtOpen = false;
  }

  private historyPayload(): Record<string, unknown> {
    return {
      type: "history",
      messages: this.transcript.map((line) => ({
        role: line.role,
        content: line.content,
        title: line.title || "",
      })),
    };
  }

  private restoreTranscriptTo(webview: vscode.Webview): void {
    if (this.transcript.length) {
      void webview.postMessage(this.historyPayload());
    }
    if (this.attachmentLabel) {
      void webview.postMessage({
        type: "attachment",
        label: this.attachmentLabel,
      });
    }
  }

  clear(): void {
    this.finalizeOpenBubbles();
    this.transcript = [];
    this.sessionTitle = "";
    this.post({ type: "clear" });
    this.pushSessionInfo();
  }

  /** Update the session label shown above the composer. */
  setSessionInfo(title: string | undefined): void {
    this.sessionTitle = (title || "").trim();
    this.pushSessionInfo();
  }

  private pushSessionInfo(): void {
    this.post({
      type: "sessionInfo",
      title: this.sessionTitle,
    });
  }

  private pushSessionInfoTo(webview: vscode.Webview): void {
    void webview.postMessage({
      type: "sessionInfo",
      title: this.sessionTitle,
    });
  }

  postUser(text: string): void {
    this.finalizeOpenBubbles();
    this.transcript.push({ role: "user", content: text });
    this.post({ type: "user", text });
  }

  /** Render a complete assistant message (history / non-streaming). */
  postAssistant(text: string): void {
    this.finalizeOpenBubbles();
    this.transcript.push({ role: "assistant", content: text });
    this.post({ type: "assistant", text });
  }

  /** Replace the transcript by replaying the same live UI events. */
  loadHistory(
    messages: Array<{ role?: string; content?: string; title?: string }>
  ): void {
    this.finalizeOpenBubbles();
    this.transcript = [];
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "clear" });
    for (const m of messages) {
      const role = String(m.role || "").toLowerCase();
      const content = String(m.content || "");
      const title = m.title != null ? String(m.title) : "";
      if (role === "user") {
        if (!content) {
          continue;
        }
        this.postUser(content);
      } else if (role === "assistant") {
        if (!content) {
          continue;
        }
        this.appendAssistant(content);
        this.finalizeOpenBubbles();
      } else if (role === "thought" || role === "thinking") {
        if (!content) {
          continue;
        }
        this.appendThought(content);
        this.finalizeOpenBubbles();
      } else if (role === "tool") {
        this.postTool(title || "tool", content);
      } else if (role === "system") {
        if (!content) {
          continue;
        }
        this.postSystem(content);
      } else if (content) {
        this.postSystem(content);
      }
    }
  }

  appendAssistant(text: string): void {
    this.thoughtOpen = false;
    this.openThought = undefined;
    if (!this.assistantOpen || !this.openAssistant) {
      this.openAssistant = { role: "assistant", content: "" };
      this.transcript.push(this.openAssistant);
      this.post({ type: "assistantStart" });
      this.assistantOpen = true;
    }
    this.openAssistant.content += text;
    this.post({ type: "assistantChunk", text });
  }

  appendThought(text: string): void {
    if (!this.thoughtOpen || !this.openThought) {
      this.openThought = { role: "thought", content: "" };
      this.transcript.push(this.openThought);
      this.post({ type: "thoughtStart" });
      this.thoughtOpen = true;
    }
    this.openThought.content += text;
    this.post({ type: "thoughtChunk", text });
  }

  postSystem(text: string): void {
    this.finalizeOpenBubbles();
    this.transcript.push({ role: "system", content: text });
    this.post({ type: "system", text });
  }

  postTool(title: string, detail: string, toolCallId?: string): void {
    this.finalizeOpenBubbles();
    this.transcript.push({
      role: "tool",
      title,
      content: detail || "",
    });
    this.post({
      type: "tool",
      title,
      detail,
      toolCallId: toolCallId || "",
    });
  }

  postPermission(interactionId: string, message: string): void {
    this.finalizeOpenBubbles();
    this.post({ type: "permission", interactionId, message });
  }

  setBusy(busy: boolean): void {
    this.post({ type: "busy", busy });
  }

  /** Show or clear the pending editor attachment chip above the composer. */
  setAttachment(label: string | undefined): void {
    this.attachmentLabel = label ?? "";
    this.post({ type: "attachment", label: this.attachmentLabel });
  }

  private post(message: Record<string, unknown>): void {
    for (const webview of this.targets) {
      void webview.postMessage(message);
    }
  }

  private html(webview: vscode.Webview): string {
    const initial: SubmitKeybinding = readSubmitKeybinding();
    const markedUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "marked.umd.js")
    );
    const purifyUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "purify.min.js")
    );
    const mermaidUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "mermaid.tiny.min.js")
    );
    const hljsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "highlight.min.js")
    );
    const hljsLightUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "hljs-github.min.css")
    );
    const hljsDarkUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "hljs-github-dark.min.css")
    );
    const csp = [
      "default-src 'none'",
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `script-src ${webview.cspSource} 'unsafe-inline'`,
    ].join("; ");
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>iCode</title>
  <link rel="stylesheet" href="${hljsLightUri}" class="hljs-theme" data-scheme="light" />
  <link rel="stylesheet" href="${hljsDarkUri}" class="hljs-theme" data-scheme="dark" disabled />
  <style>
    :root { color-scheme: light dark; }
    #log { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
    body { font-family: var(--vscode-font-family); margin: 0; padding: 8px; color: var(--vscode-foreground);
      height: 100vh; box-sizing: border-box; display: flex; flex-direction: column; }
    .msg { padding: 8px 10px; border-radius: 6px; white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
    .user { background: var(--vscode-inputValidation-infoBackground, rgba(0,120,212,.15)); }
    .assistant { background: var(--vscode-editor-inactiveSelectionBackground, rgba(128,128,128,.15)); }
    .msg.md { white-space: normal; }
    .msg.md > :first-child { margin-top: 0; }
    .msg.md > :last-child { margin-bottom: 0; }
    .msg.md p, .msg.md ul, .msg.md ol, .msg.md pre, .msg.md blockquote, .msg.md table { margin: 0.55em 0; }
    .msg.md h1, .msg.md h2, .msg.md h3, .msg.md h4 { margin: 0.7em 0 0.35em; line-height: 1.25; font-weight: 600; }
    .msg.md h1 { font-size: 1.25em; }
    .msg.md h2 { font-size: 1.15em; }
    .msg.md h3 { font-size: 1.05em; }
    .msg.md ul, .msg.md ol { padding-left: 1.4em; }
    .msg.md a { color: var(--vscode-textLink-foreground); }
    .msg.md code {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 0.92em;
      background: var(--vscode-textCodeBlock-background, rgba(127,127,127,.2));
      padding: 0.1em 0.35em; border-radius: 3px;
    }
    .msg.md pre {
      overflow-x: auto; padding: 8px 10px; border-radius: 4px;
      background: var(--vscode-textCodeBlock-background, rgba(127,127,127,.2));
    }
    .msg.md pre code { background: transparent; padding: 0; font-size: 0.88em; }
    .msg.md pre code.hljs { background: transparent; padding: 0; }
    .msg.md blockquote {
      margin-left: 0; padding-left: 0.8em;
      border-left: 3px solid var(--vscode-descriptionForeground, #888);
      opacity: 0.9;
    }
    .msg.md table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }
    .msg.md th, .msg.md td {
      border: 1px solid var(--vscode-panel-border, rgba(128,128,128,.45));
      padding: 4px 8px; text-align: left;
    }
    .msg.md th { background: var(--vscode-editor-inactiveSelectionBackground, rgba(128,128,128,.2)); font-weight: 600; }
    .msg.md hr { border: none; border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,.45)); margin: 0.8em 0; }
    .msg.md .mermaid {
      overflow-x: auto; text-align: center; background: transparent;
      padding: 6px 0; margin: 0.55em 0;
    }
    .msg.md .mermaid svg { max-width: 100%; height: auto; }
    .msg.md .mermaid-error {
      opacity: 0.85; font-size: 0.85em; white-space: pre-wrap;
      border-left: 2px solid var(--vscode-inputValidation-errorBorder, #f14c4c);
      padding-left: 8px;
    }
    .system { opacity: 0.85; font-size: 0.9em; }
    .tool-group {
      opacity: 0.95; font-size: 0.9em;
      background: var(--vscode-editor-inactiveSelectionBackground, rgba(128,128,128,.12));
      border-radius: 6px; padding: 0;
    }
    .tool-group > summary,
    .tool-item > summary {
      cursor: pointer; list-style: none; padding: 8px 10px;
      display: flex; align-items: center; gap: 6px;
      user-select: none;
    }
    .tool-group > summary::-webkit-details-marker,
    .tool-item > summary::-webkit-details-marker { display: none; }
    .tool-group > summary::before,
    .tool-item > summary::before {
      content: '▸'; flex-shrink: 0; opacity: 0.7;
    }
    .tool-group[open] > summary::before,
    .tool-item[open] > summary::before { content: '▾'; }
    .tool-group-title, .tool-item-title {
      flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .tool-group-body { padding: 0 6px 6px 6px; display: flex; flex-direction: column; gap: 4px; }
    .tool-item {
      background: var(--vscode-input-background, rgba(0,0,0,.15));
      border-radius: 4px;
    }
    .tool-item > summary { padding: 6px 8px; font-size: 0.95em; }
    .tool-item .tool-detail {
      margin: 0; padding: 0 8px 8px 20px; white-space: pre-wrap; word-break: break-word;
      font-family: var(--vscode-editor-font-family, monospace); font-size: 0.85em;
      opacity: 0.9; max-height: 220px; overflow: auto;
      border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,.3));
      padding-top: 6px;
    }
    .tool-status { opacity: 0.7; font-size: 0.85em; flex-shrink: 0; }
    .thought { opacity: 0.65; font-size: 0.85em; font-style: italic;
      border-left: 2px solid var(--vscode-descriptionForeground, #888); padding-left: 8px; }
    .thought .label { font-style: normal; opacity: 0.8; margin-bottom: 4px; display: block; }
    .permission { border: 1px solid var(--vscode-inputValidation-warningBorder, orange); padding: 8px; border-radius: 6px; }
    #composer { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; flex-shrink: 0; }
    #toolbar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    #sessionInfo {
      flex: 1; min-width: 0; font-size: 0.85em; opacity: 0.85;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    #attach {
      display: none; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 4px;
      background: var(--vscode-badge-background, rgba(128,128,128,.25));
      color: var(--vscode-badge-foreground, inherit); font-size: 0.85em;
    }
    #attach.visible { display: flex; }
    #attachLabel { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #attachClear { padding: 2px 8px; min-width: auto; }
    #hint { font-size: 0.8em; opacity: 0.7; }
    textarea { width: 100%; min-height: 56px; resize: vertical; box-sizing: border-box;
      background: var(--vscode-input-background); color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border, transparent); border-radius: 4px; padding: 6px; }
    .row { display: flex; gap: 6px; align-items: center; }
    button { cursor: pointer; background: var(--vscode-button-background); color: var(--vscode-button-foreground);
      border: none; padding: 6px 10px; border-radius: 4px; }
    button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
    button:disabled { opacity: 0.5; }
  </style>
</head>
<body>
  <div id="log"></div>
  <div id="composer">
    <div id="toolbar">
      <button id="sessions" class="secondary" title="Load a past session">Sessions</button>
      <button id="newSession" class="secondary" title="Start a new session">New</button>
      <span id="sessionInfo"></span>
    </div>
    <div id="attach">
      <span id="attachLabel"></span>
      <button id="attachClear" class="secondary" title="Remove attachment">×</button>
    </div>
    <textarea id="input" placeholder="Message iCode…"></textarea>
    <div class="row">
      <button id="send">Send</button>
      <button id="cancel" class="secondary">Stop</button>
      <span id="hint"></span>
    </div>
  </div>
  <script src="${markedUri}"></script>
  <script src="${purifyUri}"></script>
  <script src="${mermaidUri}"></script>
  <script src="${hljsUri}"></script>
  <script>
    const vscode = acquireVsCodeApi();
    const log = document.getElementById('log');
    const input = document.getElementById('input');
    const sendBtn = document.getElementById('send');
    const cancelBtn = document.getElementById('cancel');
    const sessionsBtn = document.getElementById('sessions');
    const newSessionBtn = document.getElementById('newSession');
    const sessionInfo = document.getElementById('sessionInfo');
    const hint = document.getElementById('hint');
    const attachEl = document.getElementById('attach');
    const attachLabel = document.getElementById('attachLabel');
    const attachClear = document.getElementById('attachClear');
    let assistantEl = null;
    let thoughtBody = null;
    let toolGroupEl = null;
    let toolGroupBody = null;
    let toolGroupTitleEl = null;
    let toolItemCount = 0;
    const pendingToolItems = new Map(); // name -> [detailsEl, ...]
    let submitKeybinding = ${JSON.stringify(initial)};
    let imeComposing = false;
    let suppressEnterUntil = 0;

    if (typeof marked !== 'undefined' && marked.setOptions) {
      marked.setOptions({ gfm: true, breaks: true });
    }

    function showSessionInfo(title) {
      if (!sessionInfo) return;
      sessionInfo.textContent = title ? ('Session: ' + title) : '';
      sessionInfo.title = title || '';
    }

    function showAttachment(label) {
      if (!attachEl || !attachLabel) return;
      if (label) {
        attachLabel.textContent = 'Attached: ' + label;
        attachEl.classList.add('visible');
      } else {
        attachLabel.textContent = '';
        attachEl.classList.remove('visible');
      }
    }
    attachClear.addEventListener('click', () => {
      showAttachment('');
      vscode.postMessage({ type: 'clearAttachment' });
    });
    sessionsBtn.addEventListener('click', () => vscode.postMessage({ type: 'pickSession' }));
    newSessionBtn.addEventListener('click', () => vscode.postMessage({ type: 'newSession' }));

    function isMac() {
      return navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    }

    function updateHint() {
      if (submitKeybinding === 'enter') {
        hint.textContent = 'Enter to send · Shift+Enter newline';
      } else {
        hint.textContent = isMac()
          ? '⌘⏎ to send · Enter newline'
          : 'Ctrl+Enter to send · Enter newline';
      }
    }
    updateHint();

    function isImeEnter(e) {
      // Chinese/Japanese IME: Enter confirms a candidate, must not send.
      // keyCode 229 = "Processing" during composition on many engines.
      if (imeComposing || e.isComposing || e.keyCode === 229) return true;
      if (Date.now() < suppressEnterUntil) return true;
      return false;
    }

    input.addEventListener('compositionstart', () => {
      imeComposing = true;
    });
    input.addEventListener('compositionend', () => {
      imeComposing = false;
      // Same Enter that commits the candidate may fire after compositionend
      // with isComposing=false — ignore it briefly.
      suppressEnterUntil = Date.now() + 200;
    });

    function renderMd(text) {
      const raw = text || '';
      try {
        if (typeof marked === 'undefined') return escapeHtml(raw);
        const parse = marked.parse || marked;
        const html = parse(raw, { async: false });
        if (typeof DOMPurify !== 'undefined') {
          return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
        }
        return html;
      } catch (err) {
        return escapeHtml(raw);
      }
    }

    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function applyHljsTheme() {
      const dark =
        document.body.classList.contains('vscode-dark') ||
        document.body.classList.contains('vscode-high-contrast');
      document.querySelectorAll('link.hljs-theme').forEach((link) => {
        const scheme = link.getAttribute('data-scheme');
        link.disabled = dark ? scheme !== 'dark' : scheme !== 'light';
      });
    }
    applyHljsTheme();
    new MutationObserver(applyHljsTheme).observe(document.body, {
      attributes: true,
      attributeFilter: ['class'],
    });

    function highlightCode(root) {
      if (typeof hljs === 'undefined') return;
      root.querySelectorAll('pre > code').forEach((block) => {
        if (/language-mermaid\\b/.test(block.className || '')) return;
        if (block.dataset.highlighted === 'yes') return;
        try {
          hljs.highlightElement(block);
        } catch (err) {
          /* ignore unknown languages */
        }
      });
    }

    let mermaidReady = false;
    const mermaidTimers = new WeakMap();

    function initMermaid() {
      if (mermaidReady || typeof mermaid === 'undefined') return mermaidReady;
      try {
        const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: dark ? 'dark' : 'default',
          fontFamily: 'var(--vscode-font-family)',
        });
        mermaidReady = true;
      } catch (err) {
        mermaidReady = false;
      }
      return mermaidReady;
    }

    function promoteMermaidBlocks(root) {
      root.querySelectorAll('pre > code.language-mermaid').forEach((code) => {
        const pre = code.parentElement;
        if (!pre) return;
        const wrap = document.createElement('pre');
        wrap.className = 'mermaid';
        wrap.textContent = code.textContent || '';
        pre.replaceWith(wrap);
      });
    }

    async function runMermaid(root) {
      if (!initMermaid()) return;
      promoteMermaidBlocks(root);
      const nodes = Array.from(root.querySelectorAll('pre.mermaid:not([data-processed])'));
      if (!nodes.length) return;
      for (const node of nodes) {
        const source = node.textContent || '';
        try {
          await mermaid.run({ nodes: [node], suppressErrors: true });
          if (!node.querySelector('svg')) {
            node.removeAttribute('data-processed');
            node.className = 'mermaid-error';
            node.textContent = source;
          }
        } catch (err) {
          node.removeAttribute('data-processed');
          node.className = 'mermaid-error';
          node.textContent = source;
        }
      }
    }

    function scheduleMermaid(root) {
      const prev = mermaidTimers.get(root);
      if (prev) clearTimeout(prev);
      const t = setTimeout(() => {
        mermaidTimers.delete(root);
        void runMermaid(root);
      }, 280);
      mermaidTimers.set(root, t);
    }

    function setMarkdown(el, text) {
      el.dataset.raw = text || '';
      el.classList.add('md');
      el.innerHTML = renderMd(el.dataset.raw);
      highlightCode(el);
      scheduleMermaid(el);
    }

    function appendMarkdown(el, chunk) {
      setMarkdown(el, (el.dataset.raw || '') + (chunk || ''));
    }

    function closeToolGroup() {
      toolGroupEl = null;
      toolGroupBody = null;
      toolGroupTitleEl = null;
      toolItemCount = 0;
      pendingToolItems.clear();
    }

    function updateToolGroupTitle() {
      if (!toolGroupTitleEl) return;
      const n = toolItemCount;
      toolGroupTitleEl.textContent = n === 1 ? '1 tool call' : (n + ' tool calls');
    }

    function ensureToolGroup() {
      if (toolGroupEl && toolGroupBody) return;
      assistantEl = null;
      thoughtBody = null;
      const details = document.createElement('details');
      details.className = 'msg tool-group';
      const summary = document.createElement('summary');
      const titleEl = document.createElement('span');
      titleEl.className = 'tool-group-title';
      titleEl.textContent = 'Tool calls';
      summary.appendChild(titleEl);
      const body = document.createElement('div');
      body.className = 'tool-group-body';
      details.appendChild(summary);
      details.appendChild(body);
      log.appendChild(details);
      toolGroupEl = details;
      toolGroupBody = body;
      toolGroupTitleEl = titleEl;
      toolItemCount = 0;
    }

    function parseToolTitle(title) {
      const head = (title || 'tool').trim();
      const start = head.match(/^▶\\s*(.+)$/);
      if (start) {
        return { kind: 'start', name: start[1].trim(), status: 'running', label: start[1].trim() };
      }
      const done = head.match(/^■\\s*(.+?)\\s+(completed|failed|done|cancelled|canceled|error)$/i);
      if (done) {
        return {
          kind: 'result',
          name: done[1].trim(),
          status: done[2].toLowerCase(),
          label: done[1].trim(),
        };
      }
      const doneBare = head.match(/^■\\s*(.+)$/);
      if (doneBare) {
        return {
          kind: 'result',
          name: doneBare[1].trim(),
          status: 'done',
          label: doneBare[1].trim(),
        };
      }
      return { kind: 'info', name: head, status: '', label: head };
    }

    function setToolItemSummary(item, name, status) {
      const titleEl = item.querySelector('.tool-item-title');
      const statusEl = item.querySelector('.tool-status');
      if (titleEl) titleEl.textContent = name;
      if (statusEl) statusEl.textContent = status || '';
    }

    function appendToolDetail(item, heading, text) {
      if (!text) return;
      let pre = item.querySelector('.tool-detail');
      if (!pre) {
        pre = document.createElement('pre');
        pre.className = 'tool-detail';
        item.appendChild(pre);
      }
      const block = heading + '\\n' + text;
      pre.textContent = pre.textContent ? (pre.textContent + '\\n\\n' + block) : block;
    }

    function createToolItem(name, status, detailHeading, detailText, toolCallId) {
      ensureToolGroup();
      const item = document.createElement('details');
      item.className = 'tool-item';
      if (toolCallId) item.dataset.toolCallId = toolCallId;
      item.dataset.toolName = name;
      const summary = document.createElement('summary');
      const titleEl = document.createElement('span');
      titleEl.className = 'tool-item-title';
      titleEl.textContent = name;
      const statusEl = document.createElement('span');
      statusEl.className = 'tool-status';
      statusEl.textContent = status || '';
      summary.appendChild(titleEl);
      summary.appendChild(statusEl);
      item.appendChild(summary);
      if (detailText) {
        appendToolDetail(item, detailHeading || 'Detail', detailText);
      }
      toolGroupBody.appendChild(item);
      toolItemCount += 1;
      updateToolGroupTitle();
      return item;
    }

    function renderTool(title, detail, toolCallId) {
      assistantEl = null;
      thoughtBody = null;
      const parsed = parseToolTitle(title);
      const body = (detail || '').trim();
      const id = (toolCallId || '').trim();

      if (parsed.kind === 'start') {
        const item = createToolItem(parsed.name, 'running', 'Args', body, id);
        const queue = pendingToolItems.get(parsed.name) || [];
        queue.push(item);
        pendingToolItems.set(parsed.name, queue);
        if (id) pendingToolItems.set('id:' + id, [item]);
        log.scrollTop = log.scrollHeight;
        return;
      }

      if (parsed.kind === 'result') {
        let item = null;
        if (id && pendingToolItems.has('id:' + id)) {
          item = pendingToolItems.get('id:' + id).shift();
          if (!pendingToolItems.get('id:' + id).length) pendingToolItems.delete('id:' + id);
        }
        if (!item) {
          const queue = pendingToolItems.get(parsed.name) || [];
          item = queue.shift();
          if (queue.length) pendingToolItems.set(parsed.name, queue);
          else pendingToolItems.delete(parsed.name);
        }
        if (item) {
          // Drop the same node from the name queue if we matched by id.
          const nameQueue = pendingToolItems.get(parsed.name) || [];
          const idx = nameQueue.indexOf(item);
          if (idx >= 0) {
            nameQueue.splice(idx, 1);
            if (nameQueue.length) pendingToolItems.set(parsed.name, nameQueue);
            else pendingToolItems.delete(parsed.name);
          }
          setToolItemSummary(item, parsed.name, parsed.status || 'completed');
          appendToolDetail(item, 'Result', body);
        } else {
          createToolItem(parsed.name, parsed.status || 'completed', 'Result', body, id);
        }
        log.scrollTop = log.scrollHeight;
        return;
      }

      createToolItem(parsed.label, parsed.status, 'Detail', body, id);
      log.scrollTop = log.scrollHeight;
    }

    function renderThought(text) {
      closeToolGroup();
      assistantEl = null;
      const wrap = document.createElement('div');
      wrap.className = 'msg thought';
      const label = document.createElement('span');
      label.className = 'label';
      label.textContent = 'Thinking';
      thoughtBody = document.createElement('div');
      thoughtBody.textContent = text || '';
      wrap.appendChild(label);
      wrap.appendChild(thoughtBody);
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
      thoughtBody = null;
    }

    function add(cls, text, asMarkdown) {
      closeToolGroup();
      const el = document.createElement('div');
      el.className = 'msg ' + cls;
      if (asMarkdown) setMarkdown(el, text || '');
      else el.textContent = text || '';
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
      return el;
    }

    function renderHistoryItem(m) {
      const role = (m.role || '').toLowerCase();
      const content = m.content || '';
      const title = m.title || '';
      if (role === 'user') {
        if (!content) return;
        assistantEl = null;
        thoughtBody = null;
        add('user', content, false);
      } else if (role === 'assistant') {
        if (!content) return;
        thoughtBody = null;
        closeToolGroup();
        assistantEl = add('assistant', content, true);
        assistantEl = null;
      } else if (role === 'thought' || role === 'thinking') {
        if (!content) return;
        renderThought(content);
      } else if (role === 'tool') {
        renderTool(title || 'tool', content, '');
      } else if (content) {
        assistantEl = null;
        thoughtBody = null;
        add('system', content, false);
      }
    }

    sendBtn.addEventListener('click', () => {
      const text = input.value;
      if (!text.trim()) return;
      vscode.postMessage({ type: 'send', text });
      input.value = '';
    });
    cancelBtn.addEventListener('click', () => vscode.postMessage({ type: 'cancel' }));
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      if (isImeEnter(e)) return;
      if (submitKeybinding === 'enter') {
        if (e.shiftKey) return;
        e.preventDefault();
        sendBtn.click();
        return;
      }
      if (e.metaKey || e.ctrlKey) {
        e.preventDefault();
        sendBtn.click();
      }
    });

    window.addEventListener('message', (event) => {
      const msg = event.data || {};
      switch (msg.type) {
        case 'settings':
          if (msg.submitKeybinding === 'enter' || msg.submitKeybinding === 'modifierEnter') {
            submitKeybinding = msg.submitKeybinding;
            updateHint();
          }
          break;
        case 'clear':
          log.innerHTML = '';
          assistantEl = null;
          thoughtBody = null;
          closeToolGroup();
          showAttachment('');
          showSessionInfo('');
          break;
        case 'attachment':
          showAttachment(msg.label || '');
          break;
        case 'sessionInfo':
          showSessionInfo(msg.title || '');
          break;
        case 'history': {
          log.innerHTML = '';
          assistantEl = null;
          thoughtBody = null;
          closeToolGroup();
          showAttachment('');
          const items = Array.isArray(msg.messages) ? msg.messages : [];
          for (const m of items) {
            renderHistoryItem(m);
          }
          closeToolGroup();
          log.scrollTop = log.scrollHeight;
          break;
        }
        case 'user':
          assistantEl = null;
          thoughtBody = null;
          add('user', msg.text || '', false);
          break;
        case 'assistant':
          assistantEl = null;
          thoughtBody = null;
          add('assistant', msg.text || '', true);
          break;
        case 'thoughtStart': {
          closeToolGroup();
          assistantEl = null;
          const wrap = document.createElement('div');
          wrap.className = 'msg thought';
          const label = document.createElement('span');
          label.className = 'label';
          label.textContent = 'Thinking';
          thoughtBody = document.createElement('div');
          wrap.appendChild(label);
          wrap.appendChild(thoughtBody);
          log.appendChild(wrap);
          log.scrollTop = log.scrollHeight;
          break;
        }
        case 'thoughtChunk':
          if (!thoughtBody) {
            closeToolGroup();
            assistantEl = null;
            const wrap = document.createElement('div');
            wrap.className = 'msg thought';
            const label = document.createElement('span');
            label.className = 'label';
            label.textContent = 'Thinking';
            thoughtBody = document.createElement('div');
            wrap.appendChild(label);
            wrap.appendChild(thoughtBody);
            log.appendChild(wrap);
          }
          thoughtBody.textContent += msg.text || '';
          log.scrollTop = log.scrollHeight;
          break;
        case 'assistantStart':
          closeToolGroup();
          thoughtBody = null;
          assistantEl = add('assistant', '', true);
          break;
        case 'assistantChunk':
          if (!assistantEl) {
            closeToolGroup();
            assistantEl = add('assistant', '', true);
          }
          appendMarkdown(assistantEl, msg.text || '');
          log.scrollTop = log.scrollHeight;
          break;
        case 'system':
          assistantEl = null;
          thoughtBody = null;
          add('system', msg.text || '', false);
          break;
        case 'tool':
          renderTool(msg.title || '', msg.detail || '', msg.toolCallId || '');
          break;
        case 'permission': {
          assistantEl = null;
          thoughtBody = null;
          const wrap = document.createElement('div');
          wrap.className = 'permission';
          wrap.textContent = msg.message || 'Permission required';
          const row = document.createElement('div');
          row.className = 'row';
          row.style.marginTop = '6px';
          const allow = document.createElement('button');
          allow.textContent = 'Allow';
          allow.onclick = () => vscode.postMessage({ type: 'approve', interactionId: msg.interactionId, approved: true });
          const deny = document.createElement('button');
          deny.className = 'secondary';
          deny.textContent = 'Deny';
          deny.onclick = () => vscode.postMessage({ type: 'approve', interactionId: msg.interactionId, approved: false });
          row.appendChild(allow); row.appendChild(deny);
          wrap.appendChild(row);
          log.appendChild(wrap);
          log.scrollTop = log.scrollHeight;
          break;
        }
        case 'busy':
          sendBtn.disabled = !!msg.busy;
          break;
      }
    });

    vscode.postMessage({ type: 'ready' });
  </script>
</body>
</html>`;
  }
}
