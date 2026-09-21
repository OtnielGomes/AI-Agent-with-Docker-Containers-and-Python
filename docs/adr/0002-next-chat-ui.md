---
status: accepted
---

# Replace Streamlit with a Next chat UI

The chat UI is Streamlit today. We will replace it with Next.js (App Router, TypeScript, Tailwind, port 3000) under `web/`, talking to the assistant over `BACKEND_URL`. The first Next cut is strict parity with Streamlit: session chat, health check, Pinned recipient vs default inbox, example Chat messages, clear chat — same `POST /api/chats/` contract, no Draft cards yet.

Parity ships in the same cut as ADR-0001. Visual restyle is allowed; new product behavior is not.

## Considered Options

- Keep Streamlit — rejected: we want a web app we can extend (Draft cards in ADR-0003) without rewriting twice.
- Ship Next with Draft review in the same cut — rejected: mixing a UI rewrite with a new send contract hides what broke.
