# iCode ↔ agent-core (`icode` branch) compatibility

Pinned against forked **agent-core** `icode` branch (package `openjiuwen==0.1.16`).

## agent-core (minimal)

Only SDK fix required for stable streaming/HITL cleanup:

- `openjiuwen.core.session.with_session` — tolerate ContextVar `reset` across Contexts

Do **not** port newer harness modules (`tools.subagent.awaiting|control|lifecycle`,
`subagents.concurrency`) into this branch unless product needs them.

## iCode adaptations

| Gap on 0.1.16 | Handling |
|---------------|----------|
| `SkillUseRail(inline_skills=…, script_timeout=…)` | `sdk_compat.call_with_supported_kwargs` drops unknown kwargs |
| `subagents.concurrency` | Local config dataclass; skip limiter when missing |
| `tools.subagent.awaiting` | Emit `SubAgentsIdle`; no-op marker |
| `tools.subagent.control/lifecycle` | Abort/retry commands report unavailable |

## Develop

```bash
# siblings
cd iCode && uv sync   # uses [tool.uv.sources] → ../agent-core
make smoke
```
