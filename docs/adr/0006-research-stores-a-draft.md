---
status: accepted
---

# Research stores a Draft when the send tool did not

A Chat message that asks for research and an Outbound email stores one Draft from that research's subject and body when the turn stored no other Draft. The Recipient is the Pinned recipient, then a Named recipient, then the Default inbox. With no Pinned recipient, two Named recipients or an invalid address ask instead of storing. The Assistant reply is not the source of that Draft.

## Considered Options

- Fail the turn whenever the send tool did not run — rejected: the research already has a subject and a body.
- Copy the Assistant reply into the Draft — rejected: that prose is not an Outbound email body.
