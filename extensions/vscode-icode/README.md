# iCode VS Code Extension

Branded VS Code / Cursor / OpenVSX extension that talks to **`icode acp`** over stdio (Agent Client Protocol).

## Requirements

- VS Code 1.85+ (or compatible host)
- Node 18+ (to build)
- `icode` CLI on `PATH` (`uv sync` in the monorepo, or install `openjiuwen-icode`)

## Develop

```bash
cd extensions/vscode-icode
npm install
npm run compile
npm test
```

Then in VS Code: **Extensions: Install from VSIX…** after `npm run package`, or use **F5** with a launch config that opens this folder as an extension development host.

### Demo without API key

Settings:

```json
{
  "icode.args": ["acp", "--demo"],
  "icode.trace": true
}
```

### Production

1. Set **`icode.command`** to an absolute path if `icode` is not on the GUI PATH, e.g.  
   `/Users/you/gitcode/iCode/.venv/bin/icode`
2. Command Palette → **iCode: Set API Key**
3. Optionally set `icode.model` / `icode.apiBase` / `icode.provider`
4. Open a **workspace folder** → Activity Bar **iCode** → Chat
5. If the agent was already started with a bad path: **iCode: Restart Agent**

`icode.autoApprove` defaults to `false` so the extension can show Allow/Deny for tool confirms (`--no-auto-approve` on the server).

### Chat send shortcut

Setting **`icode.submitKeybinding`**:

| Value | Behavior |
|-------|----------|
| `modifierEnter` (default) | ⌘/Ctrl+Enter send · Enter newline |
| `enter` | Enter send · Shift+Enter newline |

Changes apply immediately to an open Chat panel (no reload required).

If Output shows `Read-only file system: '/logs'`, upgrade the CLI (log bootstrap) and ensure the extension sets workspace cwd when spawning ACP (fixed in recent builds).

## Commands

| Command | Action |
|---------|--------|
| iCode: Open Chat (Sidebar) | Focus the Activity Bar Chat view |
| iCode: Open Chat in Editor | Open chat as an editor tab (beside Explorer) |
| iCode: Pick Session… | QuickPick history (also **Sessions** button in Chat) |
| iCode: New Session | `session/new` |
| iCode: Restart Agent | Kill ACP child |
| iCode: Set API Key | SecretStorage |
| iCode: Attach Active File / Selection | Context for next prompt |
| Add Selection to Chat | Editor context menu (selection) → attach + focus chat |
| iCode: Show Latest Diff | `session/diff` → VS Code diff editors |
| iCode: Refresh Sessions | `session/list` |
| iCode: Delete Session(s) | Confirm then `session/delete` (multi-select + trash / context menu) |

Chat renders assistant Markdown (GFM tables, code with highlight.js, and \`\`\`mermaid fences as diagrams).

## Community ACP Client escape hatch

Before/without this extension, [ACP Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client) can spawn:

```text
icode acp
```

See also `docs/design/vscode-acp-gaps.md` in the iCode monorepo.

## Publish

```bash
npm run package   # → icode-0.1.0.vsix
# OpenVSX / Marketplace: vsce publish / ovsx publish (credentials required)
```

CI can attach the VSIX artifact from `npm run package`. Onboarding walkthrough is contributed as `icode.onboarding`.
