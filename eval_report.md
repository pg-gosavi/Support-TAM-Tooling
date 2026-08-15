# Eval Report

**Overall pass rate:** 92% (12/13 cases)
**Average quality score:** 0.82
**LLM-as-judge mode:** llm (groq)

## Task 1 — Triage

Pass rate: 86% (6/7) · Avg quality: 0.81

| Case | Adversarial | Passed | Quality | Judge method | Notes |
|---|---|---|---|---|---|
| `triage-01-clear-bug` |  | ✅ | 0.90 | llm | The draft is on-topic, courteous, and references existing documentation without … |
| `triage-02-billing` |  | ✅ | 0.90 | llm | The response is relevant, professional, and stays factual without introducing un… |
| `triage-03-sso-auth` |  | ❌ | 0.90 | llm | The reply is relevant, professional, and provides a plausible, fact-based troubl… |
| `triage-04-feature-request` |  | ✅ | 0.90 | llm | The draft is relevant, professional, and grounded without adding unsupported cla… |
| `triage-05-onboarding` |  | ✅ | 0.90 | llm | The response is relevant, professional, and provides concrete onboarding steps w… |
| `triage-06-adversarial-ambiguous` | ✓ | ✅ | 0.30 | llm | The reply assumes a specific SSO issue not indicated in the vague ticket, making… |
| `triage-07-adversarial-malformed` | ✓ | ✅ | 0.90 | llm | The draft is on-topic, courteous, and asks for needed details without making uns… |

## Task 2 — Account Brief

Pass rate: 100% (6/6) · Avg quality: 0.83

| Case | Adversarial | Passed | Quality | Judge method | Notes |
|---|---|---|---|---|---|
| `brief-01-has-ticket-and-notes` |  | ✅ | 0.95 | llm | The content is highly relevant, professionally written, and stays factual withou… |
| `brief-02-at-risk-with-ticket` |  | ✅ | 0.90 | llm | The content is highly relevant, professionally phrased, and stays within the pro… |
| `brief-03-healthy-low-risk` |  | ✅ | 0.60 | llm | The response is relevant and professional but includes unverified details that c… |
| `brief-04-churning-high-risk` |  | ✅ | 0.90 | llm | The content is highly relevant, professionally phrased, and stays within the pro… |
| `brief-05-adversarial-incomplete-data` | ✓ | ✅ | 0.60 | llm | The response is relevant and professional but contains inconsistencies with the … |
| `brief-06-adversarial-missing-account` | ✓ | ✅ | 1.00 | rule-based | Graceful not-found handling. |
