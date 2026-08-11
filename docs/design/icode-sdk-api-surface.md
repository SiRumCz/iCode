# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""OpenJiuWen iCode → agent-core (openjiuwen) SDK dependency surface.

iCode is the product shell (CLI / TUI / EventBus / SessionHost / ACP).
It depends on the ``openjiuwen`` SDK for the agent runtime. Do not vendor
``openjiuwen.core`` or non-CLI ``openjiuwen.harness`` into the iCode repo.

## Public / supported imports (prefer these)

| Area | Modules | Notes |
|------|---------|-------|
| DeepAgent factory | ``openjiuwen.harness`` (``DeepAgent``, ``create_deep_agent``, ``DeepAgentConfig``, ``Workspace``) | Primary agent API |
| Config schema | ``openjiuwen.harness.schema.config`` | ``DeepAgentConfig``, subagent configs |
| Rails | ``openjiuwen.harness.rails`` (+ ``base``, ``context_engineer``, ``memory.memory_rail``, ``sys_operation_rail``) | Agent middleware |
| Prompts | ``openjiuwen.harness.prompts`` | Shared prompt builders |
| Tools | ``openjiuwen.harness.tools``, ``tools.base_tool``, ``tools.subagent.*`` | Tool registration / subagent control |
| Subagents | ``openjiuwen.harness.subagents.*`` | explore/plan/research/browser + concurrency |
| Workspace | ``openjiuwen.harness.workspace.workspace`` | Workspace paths |
| Session | ``openjiuwen.core.session``, ``session.agent``, ``session.interaction.interactive_input``, ``session.stream.base`` | HITL + streaming |
| Runner | ``openjiuwen.core.runner`` | Process-global resource mgr |
| LLM | ``openjiuwen.core.foundation.llm`` (+ model/schema) | Model clients |
| Cards / rails base | ``openjiuwen.core.single_agent.schema.agent_card``, ``rail.base``, ``prompts.builder`` | Agent identity + rails |
| Sys op cwd | ``openjiuwen.core.sys_operation.cwd`` | Workdir ContextVar |
| Logging | ``openjiuwen.core.common.logging`` | Structured logging |
| Tools base | ``openjiuwen.core.foundation.tool`` | Tool types |

## Optional / feature extras

| Area | Modules | Extra |
|------|---------|-------|
| Auto-harness | ``openjiuwen.auto_harness.*`` | Keep as optional; commands that need it should degrade if missing |
| Embeddings | ``openjiuwen.core.memory.lite.embeddings``, ``foundation.store.base_embedding`` | Memory-related CLI paths |

## Must stay in agent-core (SDK fixes)

- ``openjiuwen.core.session.with_session`` ContextVar cross-context reset
- Any DeepAgent / tool / rail behavior changes

## Must NOT be imported long-term from outside harness public API

Prefer expanding ``openjiuwen.harness.__all__`` over reaching into private
task_loop / internal modules from iCode. Today iCode mostly uses the
surfaces above; tighten further when adding features.
"""
