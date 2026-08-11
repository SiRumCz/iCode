import * as vscode from "vscode";

export interface ChatHandlers {
  onSend: (text: string) => void;
  onCancel: () => void;
  onApprove: (interactionId: string, approved: boolean) => void;
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
        }
      }
    );
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

  appendAssistant(text: string): void {
    // Reply starts → close the thinking stream bubble.
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

  private post(message: Record<string, unknown>): void {
    void this.view?.webview.postMessage(message);
  }

  private html(webview: vscode.Webview): string {
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
    .msg { padding: 8px 10px; border-radius: 6px; white-space: pre-wrap; word-break: break-word; line-height: 1.4; }
    .user { background: var(--vscode-inputValidation-infoBackground, rgba(0,120,212,.15)); }
    .assistant { background: var(--vscode-editor-inactiveSelectionBackground, rgba(128,128,128,.15)); }
    .system, .tool { opacity: 0.85; font-size: 0.9em; }
    .thought { opacity: 0.65; font-size: 0.85em; font-style: italic;
      border-left: 2px solid var(--vscode-descriptionForeground, #888); padding-left: 8px; }
    .thought .label { font-style: normal; opacity: 0.8; margin-bottom: 4px; display: block; }
    .permission { border: 1px solid var(--vscode-inputValidation-warningBorder, orange); padding: 8px; border-radius: 6px; }
    #composer { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
    textarea { width: 100%; min-height: 56px; resize: vertical; box-sizing: border-box;
      background: var(--vscode-input-background); color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border, transparent); border-radius: 4px; padding: 6px; }
    .row { display: flex; gap: 6px; }
    button { cursor: pointer; background: var(--vscode-button-background); color: var(--vscode-button-foreground);
      border: none; padding: 6px 10px; border-radius: 4px; }
    button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
    button:disabled { opacity: 0.5; }
  </style>
</head>
<body>
  <div id="log"></div>
  <div id="composer">
    <textarea id="input" placeholder="Message iCode…"></textarea>
    <div class="row">
      <button id="send">Send</button>
      <button id="cancel" class="secondary">Stop</button>
    </div>
  </div>
  <script>
    const vscode = acquireVsCodeApi();
    const log = document.getElementById('log');
    const input = document.getElementById('input');
    const sendBtn = document.getElementById('send');
    const cancelBtn = document.getElementById('cancel');
    let assistantEl = null;
    let thoughtBody = null;

    function add(cls, text) {
      const el = document.createElement('div');
      el.className = 'msg ' + cls;
      el.textContent = text;
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
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        sendBtn.click();
      }
    });

    window.addEventListener('message', (event) => {
      const msg = event.data || {};
      switch (msg.type) {
        case 'clear':
          log.innerHTML = '';
          assistantEl = null;
          thoughtBody = null;
          break;
        case 'user':
          assistantEl = null;
          thoughtBody = null;
          add('user', msg.text || '');
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
            // Late chunk without start — open a bubble.
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
          assistantEl = add('assistant', '');
          break;
        case 'assistantChunk':
          if (!assistantEl) assistantEl = add('assistant', '');
          assistantEl.textContent += msg.text || '';
          log.scrollTop = log.scrollHeight;
          break;
        case 'system':
          assistantEl = null;
          thoughtBody = null;
          add('system', msg.text || '');
          break;
        case 'tool':
          assistantEl = null;
          thoughtBody = null;
          add('tool', (msg.title || '') + (msg.detail ? '\\n' + msg.detail : ''));
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
