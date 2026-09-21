---
status: accepted
---

# Outbound email is a Draft until Confirm

The assistant currently sends via SMTP inside `send_me_email` and is told never to ask before sending. After the Next cut, every send path creates a Draft (UUID, Postgres, states `open` | `sent` | `discarded`) instead. The human may edit subject, Outbound email body, and Recipient, then Confirm (always posting all three fields) or Discard. Confirm re-applies body and Recipient rules before SMTP. The chat turn returns structured Drafts plus text; the UI hydrates open Drafts with GET; there is no TTL and no “send now” bypass.

Gmail’s draft folder is not used: it would add an IMAP seam we do not own. The UI never talks to SMTP.

## Considered Options

- Store the Draft only in the browser session — rejected: refresh loses review.
- Save to Gmail Drafts — rejected: extra IMAP seam and a second source of truth.
- Optional “send now” beside review — rejected: two send paths split locality.

## Consequences

Until this is implemented, SMTP still runs in the send tool. Do not add Draft UI to Streamlit; this lands on the Next chat UI after ADR-0001 and ADR-0002.
