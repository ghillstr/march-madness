"""One-shot report generation grounded in a context pack.

Each report is a pure function of its pack, so results are cached on disk and a
re-render of a page costs nothing.
"""

import json

from config import LLM_EFFORT, LLM_MAX_TOKENS, LLM_MODEL
from llm import cache
from llm.client import get_client
from llm.prompts import (
    BRACKET_NARRATIVE,
    MATCHUP_REPORT,
    SYSTEM_ANALYST,
    TEAM_SCOUTING_REPORT,
    UPSET_WATCH,
    user_message,
)

# Report kind -> task instruction.
REPORTS = {
    "matchup": MATCHUP_REPORT,
    "team": TEAM_SCOUTING_REPORT,
    "bracket": BRACKET_NARRATIVE,
    "upsets": UPSET_WATCH,
}


def _request_kwargs(pack, instruction):
    """Build the request. Stable content first so the prefix stays cached."""
    return {
        "model": LLM_MODEL,
        "max_tokens": LLM_MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_ANALYST,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": LLM_EFFORT},
        "messages": [
            {
                "role": "user",
                "content": user_message(
                    instruction, json.dumps(pack, sort_keys=True, default=str)
                ),
            }
        ],
    }


def report(kind, pack, use_cache=True):
    """Generate (or return cached) report text for `kind` grounded in `pack`."""
    instruction = REPORTS[kind]
    key = cache.cache_key(kind, pack)

    if use_cache:
        hit = cache.load(key)
        if hit is not None:
            return hit

    client = get_client()
    # Streaming even for the blocking call: it keeps long reports well clear of
    # the SDK's request timeout.
    with client.messages.stream(**_request_kwargs(pack, instruction)) as stream:
        message = stream.get_final_message()

    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if use_cache and text:
        cache.store(key, text)
    return text


def report_stream(kind, pack, use_cache=True):
    """Yield report text incrementally; store the finished text in the cache.

    A cache hit yields the stored text in one chunk, so callers can always treat
    this as a stream.
    """
    instruction = REPORTS[kind]
    key = cache.cache_key(kind, pack)

    if use_cache:
        hit = cache.load(key)
        if hit is not None:
            yield hit
            return

    client = get_client()
    chunks = []
    with client.messages.stream(**_request_kwargs(pack, instruction)) as stream:
        for chunk in stream.text_stream:
            chunks.append(chunk)
            yield chunk

    text = "".join(chunks).strip()
    if use_cache and text:
        cache.store(key, text)


# Convenience wrappers, one per report kind.
def matchup_report(pack, **kwargs):
    """Scouting report on a single head-to-head matchup."""
    return report("matchup", pack, **kwargs)


def matchup_report_stream(pack, **kwargs):
    return report_stream("matchup", pack, **kwargs)


def team_scouting_report(pack, **kwargs):
    """Scouting report on one team's season profile."""
    return report("team", pack, **kwargs)


def team_scouting_report_stream(pack, **kwargs):
    return report_stream("team", pack, **kwargs)


def bracket_narrative(pack, **kwargs):
    """Walkthrough of a simulated bracket and its championship odds."""
    return report("bracket", pack, **kwargs)


def bracket_narrative_stream(pack, **kwargs):
    return report_stream("bracket", pack, **kwargs)


def upset_watch(pack, **kwargs):
    """The upsets and coin-flip games worth watching in a bracket."""
    return report("upsets", pack, **kwargs)


def upset_watch_stream(pack, **kwargs):
    return report_stream("upsets", pack, **kwargs)
