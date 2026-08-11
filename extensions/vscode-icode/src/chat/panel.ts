import * as vscode from "vscode";
import { readSubmitKeybinding, SubmitKeybinding } from "../config";

export interface ChatHandlers {
  onSend: (text: string) => void;
  onCancel: () => void;
  onApprove: (interactionId: string, approved: boolean) => void;
  onClearAttachment?: () => void;
}

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "icode.chatView";
  private view?: vscode.WebviewView;
  private assistantOpen = false;
  private thoughtOpen = false;

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
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };
    webviewView.webview.html = this.html(webviewView.webview);
    webviewView.webview.onDidReceiveMessage(
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
        }
      }
    );
    this.pushSettings();
  }

  /** Push current submit keybinding into the webview (call on config change). */
  pushSettings(): void {
    const mode = readSubmitKeybinding();
    this.post({ type: "settings", submitKeybinding: mode });
  }

  clear(): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "clear" });
  }

  postUser(text: string): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "user", text });
  }

  /** Render a complete assistant message (history / non-streaming). */
  postAssistant(text: string): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "assistant", text });
  }

  /** Replace the transcript with persisted session messages. */
  loadHistory(
    messages: Array<{ role?: string; content?: string }>
  ): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({
      type: "history",
      messages: messages.map((m) => ({
        role: String(m.role || ""),
        content: String(m.content || ""),
      })),
    });
  }

  appendAssistant(text: string): void {
    this.thoughtOpen = false;
    if (!this.assistantOpen) {
      this.post({ type: "assistantStart" });
      this.assistantOpen = true;
    }
    this.post({ type: "assistantChunk", text });
  }

  appendThought(text: string): void {
    if (!this.thoughtOpen) {
      this.post({ type: "thoughtStart" });
      this.thoughtOpen = true;
    }
    this.post({ type: "thoughtChunk", text });
  }

  postSystem(text: string): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "system", text });
  }

  postTool(title: string, detail: string): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "tool", title, detail });
  }

  postPermission(interactionId: string, message: string): void {
    this.assistantOpen = false;
    this.thoughtOpen = false;
    this.post({ type: "permission", interactionId, message });
  }

  setBusy(busy: boolean): void {
    this.post({ type: "busy", busy });
  }

  /** Show or clear the pending editor attachment chip above the composer. */
  setAttachment(label: string | undefined): void {
    this.post({ type: "attachment", label: label ?? "" });
  }

  private post(message: Record<string, unknown>): void {
    void this.view?.webview.postMessage(message);
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
  <style>
    :root { color-scheme: light dark; }
    body { font-family: var(--vscode-font-family); margin: 0; padding: 8px; color: var(--vscode-foreground); }
    #log { height: calc(100vh - 110px); overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
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
    .system, .tool { opacity: 0.85; font-size: 0.9em; }
    .thought { opacity: 0.65; font-size: 0.85em; font-style: italic;
      border-left: 2px solid var(--vscode-descriptionForeground, #888); padding-left: 8px; }
    .thought .label { font-style: normal; opacity: 0.8; margin-bottom: 4px; display: block; }
    .permission { border: 1px solid var(--vscode-inputValidation-warningBorder, orange); padding: 8px; border-radius: 6px; }
    #composer { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
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
  <script>
    const vscode = acquireVsCodeApi();
    const log = document.getElementById('log');
    const input = document.getElementById('input');
    const sendBtn = document.getElementById('send');
    const cancelBtn = document.getElementById('cancel');
    const hint = document.getElementById('hint');
    const attachEl = document.getElementById('attach');
    const attachLabel = document.getElementById('attachLabel');
    const attachClear = document.getElementById('attachClear');
    let assistantEl = null;
    let thoughtBody = null;
    let submitKeybinding = ${JSON.stringify(initial)};
    let imeComposing = false;
    let suppressEnterUntil = 0;

    if (typeof marked !== 'undefined' && marked.setOptions) {
      marked.setOptions({ gfm: true, breaks: true });
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
      scheduleMermaid(el);
    }

    function appendMarkdown(el, chunk) {
      setMarkdown(el, (el.dataset.raw || '') + (chunk || ''));
    }

    function add(cls, text, asMarkdown) {
      const el = document.createElement('div');
      el.className = 'msg ' + cls;
      if (asMarkdown) setMarkdown(el, text || '');
      else el.textContent = text || '';
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
      return el;
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
          showAttachment('');
          break;
        case 'attachment':
          showAttachment(msg.label || '');
          break;
        case 'history': {
          log.innerHTML = '';
          assistantEl = null;
          thoughtBody = null;
          showAttachment('');
          const items = Array.isArray(msg.messages) ? msg.messages : [];
          for (const m of items) {
            const role = (m.role || '').toLowerCase();
            const content = m.content || '';
            if (!content) continue;
            if (role === 'user') add('user', content, false);
            else if (role === 'assistant') add('assistant', content, true);
            else if (role === 'system') add('system', content, false);
            else add('system', content, false);
          }
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
          thoughtBody = null;
          assistantEl = add('assistant', '', true);
          break;
        case 'assistantChunk':
          if (!assistantEl) assistantEl = add('assistant', '', true);
          appendMarkdown(assistantEl, msg.text || '');
          log.scrollTop = log.scrollHeight;
          break;
        case 'system':
          assistantEl = null;
          thoughtBody = null;
          add('system', msg.text || '', false);
          break;
        case 'tool':
          assistantEl = null;
          thoughtBody = null;
          add('tool', (msg.title || '') + (msg.detail ? '\\n' + msg.detail : ''), false);
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
  </script>
</body>
</html>`;
  }
}
