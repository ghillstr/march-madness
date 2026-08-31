"""Streamlit helpers for rendering AI sections.

Every AI section on every page goes through here, so the guard behavior is
identical: no API key means a notice and nothing else, an API error means a
warning next to the charts that already rendered, and a report that has been
generated once is served from cache instead of being re-billed.

Streamlit is imported lazily so the rest of the `llm` package stays usable from
scripts and tests.
"""

from llm import cache
from llm.client import UNAVAILABLE_MESSAGE, describe_error, llm_available

NO_DATA_MESSAGE = "Not enough data here for an AI breakdown."


def available(show_notice=True):
    """True when AI sections can run; otherwise optionally show the notice."""
    if llm_available():
        return True
    if show_notice:
        import streamlit as st

        st.info(UNAVAILABLE_MESSAGE, icon="\U0001f512")
    return False


def render_report(kind, pack, label="Generate AI analysis",
                  spinner="Reading the numbers...", show_notice=True):
    """Render one AI report section.

    Generation is button-gated on a cache miss so a page load never spends
    tokens on its own; once generated, the report is served from disk on every
    later render.
    """
    import streamlit as st

    if not available(show_notice=show_notice):
        return
    if not pack:
        st.caption(NO_DATA_MESSAGE)
        return

    from llm import analysis

    key = cache.cache_key(kind, pack)
    cached = cache.load(key)

    if cached:
        st.markdown(cached)
        if st.button("Regenerate", key=f"regen-{key}", help="Discard this "
                     "analysis and write a new one"):
            cache.invalidate(key)
            st.rerun()
        return

    if not st.button(label, key=f"gen-{key}", type="secondary"):
        st.caption("Not generated yet.")
        return

    try:
        with st.spinner(spinner):
            st.write_stream(analysis.report_stream(kind, pack))
    except Exception as exc:  # surfaced next to the charts, never fatal
        st.warning(describe_error(exc))
