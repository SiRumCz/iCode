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

1. Command Palette → **iCode: Set API Key**
2. Optionally set `icode.model` / `icode.apiBase` / `icode.provider`
3. Open a workspace folder → Activity Bar **iCode** → Chat

`icode.autoApprove` defaults to `false` so the extension can show Allow/Deny for tool confirms (`--no-auto-approve` on the server).

## Commands

| Command | Action |
|---------|--------|
| iCode: Open Chat | Focus chat webview |
| iCode: New Session | `session/new` |
| iCode: Restart Agent | Kill ACP child |
| iCode: Set API Key | SecretStorage |
| iCode: Attach Active File / Selection | Context for next prompt |
| iCode: Show Latest Diff | `session/diff` → VS Code diff editors |
| iCode: Refresh Sessions | `session/list` |

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
