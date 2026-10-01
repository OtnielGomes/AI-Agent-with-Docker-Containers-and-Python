---
status: accepted
---

# Evaluation uses synthetic cases only

An Experiment judges chat turns with LangSmith. A live Session reads the real inbox, so tracing the running app would upload that mail. Experiments run Evaluation cases kept in git. The running app sends nothing to LangSmith. Inbox tools during an Experiment return that case's synthetic Inbound emails. Drafts the case creates are gone when the case ends.

## Considered Options

- Trace live Sessions — rejected: Inbound emails and Drafts would leave the machine.
- Author cases in the LangSmith UI — rejected: git stays the reviewable source.
