# VS Code ACP bring-up — protocol gaps

Validated against iCode `AcpServer` MVP (`icode acp --demo`) and the
Route 2 extension client. Community [ACP Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client)
can also spawn `icode acp` for handshake smoke.

## Working today

| Method / event | Status |
|----------------|--------|
| `initialize` / `agent/initialize` | OK — returns `protocolVersion`, `agentInfo`, capabilities |
| `session/new` | OK — `cwd` + `sessionId` |
| `session/prompt` | OK — text / content blocks; streams `agent_message_chunk` |
| `session/cancel` | OK — publishes `UserInterrupt` |
| `session/close` / `session/list` / `session/load` | OK |
| `shutdown` | OK |
| stdout discipline | OK — JSON-RPC only; logs on stderr |

## Gaps closed for Route 2 (this work)

| Gap | Resolution |
|-----|------------|
| Hard-coded `agentInfo.version` | Read from `openjiuwen_icode.__version__` |
| `serve_stdio` untested / hard to unit-test | Extract `serve_reader`; real coverage test |
| No tool / thinking / usage stream | `session/update` for tool_call, tool_result, agent_thought_chunk, usage |
| Always `auto_approve=True` | `icode acp --no-auto-approve`; `session/approve` |
| No mutation/diff for editor | `session/diff` returns recent file mutations |

## Remaining (post–Phase 2)

| Gap | Notes |
|-----|-------|
| Full ACP spec method naming drift | Keep aliases; track agentclientprotocol.com |
| Image / audio prompt parts | Capability flags stay false until needed |
| Multi-root workdirs over ACP | Extension picks primary; `/directories` later |
| Permission UX parity with TUI | Extension modal covers ApprovalRequest; AskUser TBD |
| Native VS Code Chat Participant | Optional Phase 3; ACP remains source of truth |

## Manual smoke

```bash
# Handshake + demo prompt (no API key)
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"/tmp"}}' \
  | uv run icode acp --demo
```

Or: `make acp-smoke`
