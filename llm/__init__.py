"""LLM layer: natural-language analysis on top of the model and database.

Everything here is additive. `llm_available()` is the gate: when no API key is
configured the app runs exactly as it did before the LLM layer existed.
"""

from llm.client import llm_available, describe_error, LLMError

__all__ = ["llm_available", "describe_error", "LLMError"]
