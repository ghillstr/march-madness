"""Anthropic client construction and error handling."""

import functools
import os


class LLMError(Exception):
    """Raised for any failure reaching or using the Claude API."""


def llm_available():
    """True when an API key is configured and the SDK is importable."""
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


UNAVAILABLE_MESSAGE = (
    "AI analysis is off. Set `ANTHROPIC_API_KEY` in your environment "
    "(and `pip install anthropic`) to turn it on."
)


@functools.lru_cache(maxsize=1)
def get_client():
    """Return a memoized Anthropic client.

    The SDK resolves credentials from the environment (ANTHROPIC_API_KEY, then
    ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile), so no key is
    passed explicitly.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError(
            "The `anthropic` package is not installed. Run `pip install anthropic`."
        ) from exc

    if not llm_available():
        raise LLMError(UNAVAILABLE_MESSAGE)

    return anthropic.Anthropic()


def describe_error(exc):
    """Turn an SDK exception into a short line to show in the UI."""
    if isinstance(exc, LLMError):
        return str(exc)

    try:
        import anthropic
    except ImportError:
        return f"AI analysis failed: {exc}"

    # Most specific first.
    if isinstance(exc, anthropic.AuthenticationError):
        return "AI analysis failed: the API key was rejected."
    if isinstance(exc, anthropic.NotFoundError):
        return "AI analysis failed: the configured model was not found."
    if isinstance(exc, anthropic.RateLimitError):
        return "AI analysis is rate limited right now — try again in a moment."
    if isinstance(exc, anthropic.BadRequestError):
        return f"AI analysis failed (bad request): {exc}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"AI analysis failed (HTTP {exc.status_code})."
    if isinstance(exc, anthropic.APITimeoutError):
        return "AI analysis timed out — try again."
    if isinstance(exc, anthropic.APIConnectionError):
        return "AI analysis could not reach the API — check your connection."
    return f"AI analysis failed: {exc}"
