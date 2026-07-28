"""Streamlit chat UI for the AI Agent backend."""

from __future__ import annotations

import streamlit as st

from api_client import ApiClientError, check_health, get_backend_url, send_message

EXAMPLE_PROMPTS = [
    "Summarize my last 3 emails.",
    "Write me an email about artificial intelligence applied to business.",
    "Help me write an email to schedule a meeting for this week.",
]

st.set_page_config(
    page_title="AI Agent Chat",
    page_icon="🤖",
    layout="wide",
)

if "messages" not in st.session_state:
    st.session_state.messages: list[dict[str, str]] = []

if "backend_url" not in st.session_state:
    st.session_state.backend_url = get_backend_url()

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt: str | None = None


def render_sidebar() -> None:
    """Render sidebar controls and example prompts."""
    with st.sidebar:
        st.header("Settings")
        st.session_state.backend_url = st.text_input(
            "Backend URL",
            value=st.session_state.backend_url,
            help="FastAPI base URL (e.g. http://localhost:8080)",
        ).rstrip("/")

        if st.button("Test connection", use_container_width=True):
            if check_health(st.session_state.backend_url):
                st.success("API is online")
            else:
                st.error("API is offline or unreachable")

        st.divider()
        st.subheader("Example prompts")
        for prompt in EXAMPLE_PROMPTS:
            if st.button(prompt, use_container_width=True, key=f"example_{prompt[:20]}"):
                st.session_state.pending_prompt = prompt

        st.divider()
        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


def render_header() -> None:
    """Render page title and API status badge."""
    col_title, col_status = st.columns([3, 1])
    with col_title:
        st.title("AI Agent Chat")
        st.caption(
            "Research and email assistant powered by LangGraph. "
            "History is kept for this session only."
        )
    with col_status:
        online = check_health(st.session_state.backend_url)
        if online:
            st.success("API online")
        else:
            st.error("API offline")


def render_chat_history() -> None:
    """Render stored chat messages."""
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


def handle_user_message(user_text: str) -> None:
    """Append user message, call API, append assistant reply."""
    st.session_state.messages.append({"role": "user", "content": user_text})

    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Agent is working... This may take up to a few minutes."):
            try:
                reply = send_message(st.session_state.backend_url, user_text)
            except ApiClientError as exc:
                reply = f"**Error:** {exc}"
            st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})


def main() -> None:
    """Run the Streamlit app."""
    render_sidebar()
    render_header()
    render_chat_history()

    prompt = st.session_state.pending_prompt
    if prompt:
        st.session_state.pending_prompt = None
        handle_user_message(prompt)
        st.rerun()

    if user_input := st.chat_input("Ask the agent..."):
        handle_user_message(user_input)
        st.rerun()


if __name__ == "__main__":
    main()
