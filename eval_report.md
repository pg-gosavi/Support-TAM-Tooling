# Eval Report

**Overall pass rate:** 100% (13/13 cases)
**Average quality score:** 0.90
**LLM-as-judge mode:** llm (groq)

## Task 1 — Triage

Pass rate: 100% (7/7) · Avg quality: 0.91

| Case | Adversarial | Passed | Quality | Judge method | Notes |
|---|---|---|---|---|---|
| `triage-01-clear-bug` |  | ✅ | 0.95 | llm | The response is directly relevant, maintains a professional tone, and asks for f… |
| `triage-02-billing` |  | ✅ | 0.85 | llm | The response is relevant, polite and professional, and mostly grounded, though i… |
| `triage-03-sso-auth` |  | ✅ | 0.95 | llm | The draft is highly relevant, maintains a professional tone, and provides accura… |
| `triage-04-feature-request` |  | ✅ | 0.95 | llm | The draft is relevant to the request, professionally worded, and contains no inv… |
| `triage-05-onboarding` |  | ✅ | 0.90 | llm | The reply is on-topic, courteous, and provides concrete guidance without fabrica… |
| `triage-06-adversarial-ambiguous` | ✓ | ✅ | 0.90 | llm | The response is relevant, professional, and contains no invented information, th… |
| `triage-07-adversarial-malformed` | ✓ | ✅ | 0.90 | llm | The draft is on-topic, courteous, and asks for needed details without making uns… |

## Task 2 — Account Brief

Pass rate: 100% (6/6) · Avg quality: 0.89

| Case | Adversarial | Passed | Quality | Judge method | Notes |
|---|---|---|---|---|---|
| `brief-01-has-ticket-and-notes` |  | ✅ | 0.90 | llm | The executive summary and talking points are highly relevant, professionally phr… |
| `brief-02-at-risk-with-ticket` |  | ✅ | 0.90 | llm | The executive summary and talking points are directly relevant, professionally p… |
| `brief-03-healthy-low-risk` |  | ✅ | 0.95 | llm | The executive summary and talking points are directly relevant, professionally w… |
| `brief-04-churning-high-risk` |  | ✅ | 0.90 | llm | The text is highly relevant, professionally written, and stays grounded in the p… |
| `brief-05-adversarial-incomplete-data` | ✓ | ✅ | 0.70 | llm | The response is relevant and professional but includes invented details (e.g., f… |
| `brief-06-adversarial-missing-account` | ✓ | ✅ | 1.00 | rule-based | Graceful not-found handling. |
