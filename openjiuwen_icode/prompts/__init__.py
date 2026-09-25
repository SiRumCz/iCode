"""Prompt construction for the CLI agent."""

from openjiuwen_icode.prompts.builder import (
    build_system_prompt,
)
from openjiuwen_icode.prompts.code_profile import (
    is_code_profile,
)

__all__ = [
    "build_system_prompt",
    "is_code_profile",
]
