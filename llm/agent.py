"""Tool-calling chat analyst.

The SDK's tool runner drives the loop: it calls the model, executes whichever
tools in `llm/tools.py` the model asks for, and feeds the results back until the
model answers. This module wraps that loop in an event stream so the UI can show
each lookup as it happens.
"""

from config import (
    LLM_AGENT_EFFORT,
    LLM_MAX_TOKENS,
    LLM_MAX_TOOL_ROUNDS,
    LLM_MODEL,
)
from llm.client import get_client
from llm.prompts import SYSTEM_AGENT
from llm.tools import ALL_TOOLS

# Cap on how many times a paused server turn is resumed before giving up.
MAX_PAUSE_RESTARTS = 3


def _system_blocks():
    """Frozen system prompt, cached so only the conversation is billed fresh."""
    return [
        {
            "type": "text",
            "text": SYSTEM_AGENT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _text_of(message):
    return "".join(b.text for b in message.content if b.type == "text").strip()


def ask_stream(messages):
    """Answer the conversation in `messages`, yielding events as they happen.

    Events are dicts with a "type":
      - "tool_use": {"name", "input"}  — a lookup the analyst ran
      - "text":     {"text"}           — assistant prose from one turn
      - "done":     {"messages", "usage"} — final mirrored history and token use

    `messages` is a list of {"role", "content"} dicts; the returned history is
    the full mirrored conversation, suitable for passing back in on the next
    turn.
    """
    client = get_client()
    history = list(messages)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    rounds = 0

    for restart in range(MAX_PAUSE_RESTARTS + 1):
        runner = client.beta.messages.tool_runner(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=_system_blocks(),
            thinking={"type": "adaptive"},
            output_config={"effort": LLM_AGENT_EFFORT},
            tools=ALL_TOOLS,
            messages=history,
        )

        last = None
        for message in runner:
            last = message

            if message.usage:
                usage["input_tokens"] += message.usage.input_tokens or 0
                usage["output_tokens"] += message.usage.output_tokens or 0
                usage["cache_read_input_tokens"] += (
                    getattr(message.usage, "cache_read_input_tokens", 0) or 0
                )

            text = _text_of(message)
            if text:
                yield {"type": "text", "text": text}

            for block in message.content:
                if block.type == "tool_use":
                    yield {"type": "tool_use", "name": block.name,
                           "input": block.input}

            # Mirror the history: the runner keeps its own copy and does not
            # expose it, and we need ours to resume a paused turn.
            history.append({"role": "assistant", "content": message.content})
            tool_response = runner.generate_tool_call_response()
            if tool_response is None:
                continue

            history.append(tool_response)
            rounds += 1
            if rounds >= LLM_MAX_TOOL_ROUNDS:
                yield {
                    "type": "text",
                    "text": (
                        f"_Stopped after {rounds} lookups. Ask a narrower "
                        f"question and I'll pick it back up._"
                    ),
                }
                yield {"type": "done", "messages": history, "usage": usage}
                return

        if last is None or last.stop_reason != "pause_turn":
            break
        # A paused turn leaves `history` ending on the paused assistant message,
        # so a fresh runner resumes where this one stopped.

    yield {"type": "done", "messages": history, "usage": usage}


def ask(messages):
    """Blocking version of `ask_stream`: returns the finished answer.

    Returns a dict with "text", "tool_calls", "messages" and "usage".
    """
    parts = []
    tool_calls = []
    history = list(messages)
    usage = {}

    for event in ask_stream(messages):
        if event["type"] == "text":
            parts.append(event["text"])
        elif event["type"] == "tool_use":
            tool_calls.append({"name": event["name"], "input": event["input"]})
        elif event["type"] == "done":
            history = event["messages"]
            usage = event["usage"]

    return {
        "text": "\n\n".join(parts).strip(),
        "tool_calls": tool_calls,
        "messages": history,
        "usage": usage,
    }
