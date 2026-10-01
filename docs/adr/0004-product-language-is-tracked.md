# Product language is tracked; agent skills stay local

CONTEXT.md, docs/, and the root AGENTS.md are the product language, so Git tracks them. .agents/, .cursor/, skills-lock.json, and web/AGENTS.md stay on this machine. Next regenerates web/AGENTS.md.

## Considered Options

- Keep the whole agent tree local — rejected: a clone cannot read the glossary or the ADRs.
- Track skills and cursor rules too — rejected: those are this environment, not the product language.
