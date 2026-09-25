# SDK fixes retained in agent-core (iCode split)

These belong to the ``openjiuwen`` SDK and stay in this repository
when iCode moves to ``openjiuwen-icode``. They are already on
``icode_porting`` (package version **0.1.23**).

| Fix | Location | Why SDK |
|-----|----------|---------|
| ``with_session`` ContextVar cross-context reset | [`openjiuwen/core/session/__init__.py`](../../openjiuwen/core/session/__init__.py) | Used by ReAct stream / HITL resume |
| Skill manager tweaks (if any on branch) | [`openjiuwen/core/single_agent/skills/`](../../openjiuwen/core/single_agent/skills/) | Core skill loading |

**Release note:** publish agent-core ``>=0.1.23`` before cutting an
``iCode`` / ``openjiuwen-icode`` release that pins ``openjiuwen>=0.1.23``.

iCode product code (EventBus, TUI, SessionHost, PyApp) must not fork
these modules — depend on the published SDK instead.

See also [icode-sdk-api-surface.md](icode-sdk-api-surface.md).
