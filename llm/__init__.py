"""LLM access: provider clients, key rotation, and usage accounting.

Public surface (T15): :class:`LLMClient` (rotation + fallback over
OpenAI-compatible endpoints), :class:`LLMResponse` / :class:`LLMError` /
:class:`LLMDeadlineExceeded` (the call result and its failure modes),
:class:`KeyRing` (per-provider key rotation), and
:func:`sanity_check_usage` (reported-vs-visible token sanity). The wire
format and the models_json schema are documented in :mod:`llm.client`.
"""

from llm.client import (
    LLMClient,
    LLMDeadlineExceeded,
    LLMError,
    LLMResponse,
)
from llm.keys import KeyRing
from llm.usage import sanity_check_usage

__all__ = [
    "KeyRing",
    "LLMClient",
    "LLMDeadlineExceeded",
    "LLMError",
    "LLMResponse",
    "sanity_check_usage",
]
