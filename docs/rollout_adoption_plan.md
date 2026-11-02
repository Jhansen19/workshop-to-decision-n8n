# Rollout & Adoption Plan: Workshop-to-Decision Pipeline

*Illustrative plan for a fictional Nordic retail group (Aurora Beauty Group). It shows how the tool would be introduced as a new way of working, not just installed.*

## 1. Purpose
Cut the time from "workshop ends" to "decisions, owners and risks are agreed in writing" from days to hours, while keeping accountability with leaders. **AI drafts, people decide.**

## 2. Scope
| In scope (pilot) | Out of scope (for now) |
|---|---|
| Cross-functional transformation workshops in one workstream | HR, legal or other confidential meetings |
| Notes or transcripts in English and Nordic languages | Automatic recording of meetings |
| Decision memo, action tracker, risk log | Replacing the steering committee or PMO reporting |

## 3. Roles and decision rights
| Step | Facilitator | Decision owner (workshop sponsor) | Transformation PMO | Group IT / Data Protection |
|---|---|---|---|---|
| Submit notes after the workshop | **R/A** | I | I | |
| Review and approve the AI memo | C | **R/A** | I | |
| Publish actions to the tracker | | A | **R** | |
| Chase overdue actions | C | I | **R/A** | |
| Prompt and model changes | C | I | **A** | **R** |
| Data protection and access rules | | I | C | **R/A** |

*R = Responsible, A = Accountable, C = Consulted, I = Informed*

## 4. Governance rules
1. **No memo is shared without the decision owner's approval.** The approval step can't be skipped.
2. The memo shows which model drafted it and lists any governance flags (unowned actions, unmitigated high risks, open issues).
3. Only approved notes and transcripts are processed; no personal or HR-sensitive content.
4. Any change to the prompts or model is re-scored against the same answer keys before it goes live.
5. Before real data is used: a data-processing agreement with the LLM provider, an EU data-residency check and a GDPR review.

## 5. Rollout plan
| Phase | Timing | What happens | Exit criterion |
|---|---|---|---|
| 0. Prepare | Weeks 1–2 | Data-protection review, set up access, 30-min training for facilitators | Approved by Group IT/DPO |
| 1. Pilot | Weeks 3–8 | One workstream (e.g. supply chain integration), 2 facilitators, all its workshops | Targets in §6 met for 6 weeks |
| 2. Extend | Weeks 9–16 | All transformation workstreams, all four markets, local-language notes | Adoption ≥ 70% of workshops |
| 3. Embed | From week 17 | Part of the standard transformation playbook; the PMO owns it day to day | Included in the playbook and onboarding |

## 6. Success measures
| Measure | Baseline (pilot start) | Pilot target |
|---|---|---|
| Time from workshop to approved memo | Measured in week 1 | Under 24 hours |
| Facilitator time spent on write-up | Measured manually (see `eval/time_baseline.csv`) | At least 50% less |
| Actions with a named owner within 48 h | Measured in week 1 | Over 90% |
| Action closure on time | Measured in week 1 | +20 percentage points |
| Memos approved without major edits | n/a | Over 80% |
| Model scorecard (`eval/score_models.py`) | Current result | No drop after any change |

## 7. Change management
- **Start with willing users:** two facilitators who already struggle with follow-up become the champions.
- **Show, don't mandate:** demo it in the first pilot steering committee using that week's real workshop.
- **Keep the human visible:** the memo is signed off by the sponsor, not "by the AI".
- **Feedback loop:** a 15-minute monthly review of rejected memos; fixes go into the prompt and are re-scored.
- **Group consistency, local fit:** one workflow and memo format for the Group; notes accepted in any Nordic language; market shown on every item.

## 8. Key risks and mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Leaders trust the AI summary too much | Wrong decisions recorded | Mandatory approval; governance flags; monthly review of edits |
| Sensitive data sent to an external model | Compliance breach | Scope rules (§2), DPA and EU data residency, no HR/legal meetings |
| Facilitators see it as extra work | Low adoption | One-step form; measure and share time saved |
| Model quality changes after a provider update | Silent quality drop | Re-run the scorecard monthly and after any change; automatic fallback model |
| Actions go into the tracker but nobody chases them | No real improvement | PMO owns chasing; overdue report to sponsors weekly |
