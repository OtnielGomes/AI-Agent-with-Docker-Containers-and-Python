---
status: accepted
---

# Top-level `api/` and `web/` directories

The repo today splits FastAPI under `backend/` and Streamlit under `frontend/`, with a Python package already named `api` inside `backend/src/`. We will rename those trees to `api/` and `web/` so directory names match the HTTP assistant and the chat UI, keep `src/` inside `api/` (no flatten), and keep the Python package name `api` so imports stay `from api...`. Compose services follow the same names: `api` and `web`.

This cut happens after the Outbound email body and Recipient deepenings, in the same change as the Next chat UI, so we do not move files twice.

## Considered Options

- Keep `backend/` / `frontend/` — rejected: the names hide what each tree is for.
- Flatten `api/src/` into `api/` in the same cut — rejected: extra import and Docker churn with no locality gain.
