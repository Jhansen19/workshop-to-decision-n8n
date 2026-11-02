Write a one-page decision memo for a senior steering committee, based ONLY on the JSON below.
Structure (Markdown):
# <Workshop title>: Decision Memo
**Date | Markets | Run ID**
## Bottom line (3 sentences max: what was decided, what needs sign-off, biggest risk)
## Decisions made (table: Decision | Scope | Owner)
## Decisions requiring your sign-off (numbered, each with a clear recommendation)
## Open issues for escalation (options discussed + recommended next step)
## Key risks & dependencies (top 3 only)
## Next steps (table: Action | Owner | Due)
## Governance flags
Tone: crisp, neutral, no jargon, no filler. Write in English. Do not add facts not present in the JSON.

JSON: {{ JSON.stringify($json) }}
