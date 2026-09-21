# Email assistant

A chat assistant that researches content, reads the inbox, and sends outbound email on the user's behalf.

## Language

**Chat message**:
A user or assistant utterance in the conversation that drives research, inbox reading, or sending.
_Avoid_: request, prompt, contents

**Recipient**:
The address that receives an outbound email. Precedence is pinned, then named, then the default inbox.
_Avoid_: to_email, destination, target

**Pinned recipient**:
The Recipient chosen in the chat UI for this request.
_Avoid_: UI email, selected email, to_email

**Named recipient**:
A Recipient stated in the Chat message and passed into the send tool.
_Avoid_: tool email, explicit to_email

**Default inbox**:
The user's own inbox address, used when neither pinned nor named.
_Avoid_: EMAIL_ADDRESS, from_email, primary email

**Outbound email**:
An email to a Recipient, with a subject and a body. Unsent, it is a Draft; SMTP runs only after Confirm.
_Avoid_: message (that is a Chat message)

**Draft**:
An unsent Outbound email stored by the assistant for human review. The human may edit subject, Outbound email body, and Recipient before Confirm.
_Avoid_: Gmail draft, rascunho, pending send

**Confirm**:
The human action that sends a Draft via SMTP, after optional edits.
_Avoid_: approve, OK, send now

**Discard**:
The human action that abandons a Draft so it cannot be Confirmed.
_Avoid_: delete, cancel, reject

**Outbound email body**:
The send-ready plain-text body of an Outbound email, after placeholder and signature policy.
_Avoid_: contents, signature, body text
