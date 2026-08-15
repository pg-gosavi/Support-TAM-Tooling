# Prompt changelog

Each prompt is versioned in its filename (`_v1`, `_v2`, ...) and carries an
HTML comment header (`prompt_id`, `version`) so a given run's output can be
traced back to the prompt that produced it. `app/triage/pipeline.py` and
`app/account_brief/pipeline.py` load these files from disk at runtime rather
than embedding the text inline, so a prompt edit doesn't require a code
change.

## triage_v2.md — v2

1. **Bug vs. How-To boundary.** Eval results showed inconsistent
   classification on tickets that name a specific error and describe broken
   behavior — the model would occasionally classify these as How-To instead
   of Bug/Integration. Added an explicit rule: anything describing broken or
   unexpected behavior is never How-To, regardless of phrasing.
2. **Low-confidence KB matches.** On vague, one-line tickets, the draft
   response sometimes referenced a KB excerpt that only weakly matched
   (near the retriever's score floor). Added an instruction to treat weak
   matches as coincidental on vague tickets rather than building the
   response around them.

## triage_v1.md — v1 (superseded by v2)
- Narrow scope: the model decides `product_area`, `issue_category`,
  `urgency_tier` (with reasoning) and `draft_first_response`. KB matching
  and team routing are handled by deterministic code, not the model.
- Explicit instruction not to default to P1/P2 on tone alone, and not to
  invent KB content that wasn't supplied in context.

## account_brief_v1.md — v1
- Narrow scope: the model writes `executive_summary` and `talking_points`
  from a pre-computed JSON fact sheet (account metrics plus already-flagged
  risks with their quotes). Instructed not to invent facts, tickets, or
  quotes, and to state plainly when a data section (tickets, escalation
  notes) is empty rather than gloss over it.

## Planned for v3
- Few-shot examples per issue_category to reduce category confusion between
  adjacent categories (e.g. Integration vs. Bug for SSO errors).
- A shorter prompt variant for P1 tickets that skips reasoning verbosity in
  favor of latency.
