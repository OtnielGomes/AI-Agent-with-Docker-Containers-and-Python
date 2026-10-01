## Agent skills

### Issue tracker

Issues live in GitHub Issues for this repo (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Commit messages

Conventional `type: summary` when creating a git commit. See `.cursor/rules/commit-conventions.mdc`.

### Code map

- Inbound email plain text: `api/src/api/inbound_mail.py`, shown in `web/components/InboundMail.tsx`
- Draft and Confirm: `api/src/api/drafts.py`, shown in `web/components/DraftReviewCard.tsx`
- Screenshots: `images/`. The English README uses `*-en.png`.

### Checks

`scripts/check.sh` runs the API tests, the web lint, and the README image check.