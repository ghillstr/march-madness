"""Ask the Analyst — chat grounded in the database and the trained model."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import streamlit as st

from config import CURRENT_SEASON, LLM_MODEL, MODEL_DIR
from llm import ui as llm_ui
from llm.client import describe_error

st.set_page_config(page_title="AI Analyst", page_icon="\U0001f3c0", layout="wide")
st.title("\U0001f9e0 Ask the Analyst")
st.caption(
    "Answers come from the same database the pages read and the same network "
    "the bracket runs — the analyst looks things up rather than recalling them."
)

if not llm_ui.available():
    st.stop()

# Imported after the guard so a missing `anthropic` package degrades to the
# notice above rather than an import error.
from llm import agent  # noqa: E402

if not os.path.exists(os.path.join(MODEL_DIR, "best_model.pt")):
    st.warning(
        "No trained model found, so matchup predictions and championship odds "
        "are unavailable. Stat and history questions still work."
    )

SUGGESTIONS = [
    "Who does the model favor between Duke and Houston, and why?",
    "Which team has the best defense in the field this season?",
    "Give me a 12-seed with a real shot at an upset.",
    "How has Gonzaga been seeded over the last few tournaments?",
]

if "analyst_display" not in st.session_state:
    st.session_state.analyst_display = []
if "analyst_messages" not in st.session_state:
    st.session_state.analyst_messages = []

with st.sidebar:
    st.header("Analyst")
    st.caption(f"Model: `{LLM_MODEL}`")
    st.caption(f"Season: {CURRENT_SEASON}")
    st.markdown("**Tools it can call**")
    st.caption(
        "- search teams\n- team season stats\n- compare two teams\n"
        "- run the prediction model\n- tournament history\n- injury report\n"
        "- Monte Carlo championship odds"
    )
    if st.button("Clear conversation"):
        st.session_state.analyst_display = []
        st.session_state.analyst_messages = []
        st.rerun()


def _format_args(payload):
    """Compact one-line rendering of a tool call's arguments."""
    if not isinstance(payload, dict):
        return json.dumps(payload, default=str)[:120]
    return ", ".join(f"{k}={v!r}" for k, v in sorted(payload.items()))


def _render_tools(tools):
    for call in tools:
        st.caption(f"\U0001f50e `{call['name']}`({_format_args(call['input'])})")


# Replay the conversation so far.
for entry in st.session_state.analyst_display:
    with st.chat_message(entry["role"]):
        if entry.get("tools"):
            _render_tools(entry["tools"])
        st.markdown(entry["text"])
        if entry.get("usage"):
            st.caption(entry["usage"])

if not st.session_state.analyst_display:
    st.markdown("**Try one of these:**")
    columns = st.columns(2)
    for i, suggestion in enumerate(SUGGESTIONS):
        if columns[i % 2].button(suggestion, key=f"suggest-{i}",
                                 use_container_width=True):
            st.session_state.pending_question = suggestion
            st.rerun()

question = st.chat_input("Ask about a matchup, a team, or the bracket")
if not question:
    question = st.session_state.pop("pending_question", None)

if question:
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.analyst_display.append({"role": "user", "text": question})
    st.session_state.analyst_messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        parts = []
        tools_used = []
        usage_note = ""
        try:
            with st.spinner("Looking it up..."):
                for event in agent.ask_stream(st.session_state.analyst_messages):
                    if event["type"] == "tool_use":
                        call = {"name": event["name"], "input": event["input"]}
                        tools_used.append(call)
                        _render_tools([call])
                    elif event["type"] == "text":
                        parts.append(event["text"])
                        st.markdown(event["text"])
                    elif event["type"] == "done":
                        st.session_state.analyst_messages = event["messages"]
                        usage = event["usage"]
                        usage_note = (
                            f"{usage['input_tokens']:,} in / "
                            f"{usage['output_tokens']:,} out tokens"
                        )
                        if usage.get("cache_read_input_tokens"):
                            usage_note += (
                                f" ({usage['cache_read_input_tokens']:,} cached)"
                            )
        except Exception as exc:
            message = describe_error(exc)
            st.warning(message)
            # Drop the unanswered turn so the next question starts clean.
            if st.session_state.analyst_messages:
                st.session_state.analyst_messages.pop()
            st.session_state.analyst_display.append(
                {"role": "assistant", "text": message}
            )
        else:
            if usage_note:
                st.caption(usage_note)
            st.session_state.analyst_display.append({
                "role": "assistant",
                "text": "\n\n".join(parts).strip() or "_No answer returned._",
                "tools": tools_used,
                "usage": usage_note,
            })
