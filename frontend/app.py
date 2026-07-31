"""Streamlit chat UI for the AI Agent backend."""

from __future__ import annotations

import re

import streamlit as st

from api_client import ApiClientError, check_health, get_backend_url, send_message

EXAMPLE_PROMPTS = [
    "Summarize my last 3 emails.",
    "Write me an email about artificial intelligence applied to business.",
    "Help me write an email to schedule a meeting for this week.",
]

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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

if "send_to_self" not in st.session_state:
    st.session_state.send_to_self = True

if "other_recipient_email" not in st.session_state:
    st.session_state.other_recipient_email = ""


def is_valid_email(address: str) -> bool:
    """Return True if the string looks like a valid email address."""
    if not address or not address.strip():
        return False
    return bool(_EMAIL_PATTERN.match(address.strip()))


def get_selected_recipient() -> str | None:
    """Return explicit recipient when 'Outro email' is selected, else None."""
    if st.session_state.send_to_self:
        return None
    email = st.session_state.other_recipient_email.strip()
    return email or None


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
            online = check_health(st.session_state.backend_url)
            st.session_state.api_online = online
            if online:
                st.success("API is online")
            else:
                st.error("API is offline or unreachable")

        st.divider()
        st.subheader("Email recipient")

        def _sync_recipient_mode() -> None:
            if st.session_state.recipient_other_email:
                st.session_state.send_to_self = False
            else:
                st.session_state.send_to_self = True

        st.checkbox(
            "Send an email to myself",
            value=st.session_state.send_to_self,
            on_change=_sync_recipient_mode,
            key="recipient_send_to_self",
            help="Uses the primary email address configured by the wizard.",
        )
        st.checkbox(
            "Other email",
            value=not st.session_state.send_to_self,
            on_change=_sync_recipient_mode,
            key="recipient_other_email",
            help="Enter a different recipient below.",
        )

        if (
            st.session_state.recipient_send_to_self
            and st.session_state.recipient_other_email
        ):
            st.session_state.send_to_self = False

        if st.session_state.send_to_self:
            st.caption("The emails will be sent to the primary email address configured in the app.")
        else:
            st.session_state.other_recipient_email = st.text_input(
                "Recipient's email",
                value=st.session_state.other_recipient_email,
                placeholder="name@exemple.com",
            )
            if st.session_state.other_recipient_email and not is_valid_email(
                st.session_state.other_recipient_email
            ):
                st.error("Enter a valid email address..")

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
        if "api_online" not in st.session_state:
            st.session_state.api_online = check_health(st.session_state.backend_url)
        if st.session_state.api_online:
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
    to_email = get_selected_recipient()
    if not st.session_state.send_to_self:
        if not to_email:
            st.error("Enter the recipient's email in the sidebar..")
            return
        if not is_valid_email(to_email):
            st.error("Invalid recipient email.")
            return

    st.session_state.messages.append({"role": "user", "content": user_text})

    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Agent is working... This may take up to a few minutes."):
            try:
                reply = send_message(
                    st.session_state.backend_url,
                    user_text,
                    to_email=to_email,
                )
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
