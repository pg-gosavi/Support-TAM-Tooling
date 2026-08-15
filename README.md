# Support & TAM Tooling

Two internal LLM-powered tools for a Technical Support / TAM team:

1. **Task 1 — Ticket triage** (`app/triage/`): classifies a raw ticket into
   product area, issue category, and urgency, surfaces a matching
   knowledge-base doc if one exists, and drafts a first-response message.
2. **Task 2 — Account health brief** (`app/account_brief/`): turns an
   account_id into a 3-section brief a TAM can use to prep for a QBR, with
   deterministic, quote-backed churn/escalation flagging.

Design rationale (failure modes, latency/quality trade-offs, data
sensitivity, scaling) is in **[DESIGN.md](DESIGN.md)**.

---

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and set GROQ_API_KEY (free, no card — https://console.groq.com/keys)
```

If no API key is configured, both pipelines fall back to a deterministic,
rule-based mode instead of failing, which keeps `python main.py` runnable
out of the box. Check `provider` in any output (`"groq"` / `"gemini"` /
`"offline"`) to see which path actually ran.

## Run it — single entry point

```bash
python main.py
```

Runs a live demo of Task 1 and Task 2 against the provided mock dataset.
Sample output from a live run:

### Task 1 sample run

```json
{
  "product_area": {
    "value": "Data Ingestion",
    "reasoning": "The ticket explicitly mentions the Data Ingestion module within DataBridge Pro, clearly indicating the specific product area in question."
  },
  "issue_category": {
    "value": "Feature Request",
    "reasoning": "The customer is requesting new functionality — bulk archive operations — which is not currently available in the Data Ingestion module."
  },
  "urgency_tier": {
    "value": "P2",
    "reasoning": "The lack of bulk operations forces a manual, one-by-one workflow that doesn't scale for 116 users, but a workaround exists."
  },
  "matched_kb_doc": {
    "doc_path": "troubleshooting/performance-and-integrations.md",
    "section": "Troubleshooting: Performance Issues > Error Reference",
    "score": 20.559
  },
  "recommended_team": "Product Management",
  "draft_first_response": "Thank you for reaching out about the need for bulk archive operations in the Data Ingestion module. We understand the impact this has on your workflow given the number of users involved. We'll review your request and explore adding bulk operations in a future update, and will follow up as we make progress.",
  "warnings": [],
  "provider": "groq"
}
```

### Task 2 sample run

```json
{
  "account_id": "ACC-3336",
  "found": true,
  "company": "Omni Consumer Products",
  "executive_summary": "Omni Consumer Products, a Business-tier customer with $500,000 ARR, is currently at risk due to an inactive usage trend and a high churn risk level. The account has an open escalation note indicating the decision maker is evaluating a competing vendor. The most pressing issue is the potential loss of the account to a competitor.",
  "open_risks": [
    {
      "ticket_id": "(account escalation note)",
      "signal_type": "escalation_note",
      "reason": "Escalation note contains a churn-risk signal ('competing vendor').",
      "quote": "Decision maker considering competing vendor evaluation"
    },
    {
      "ticket_id": "TKT-10293",
      "signal_type": "high_urgency_ticket",
      "reason": "P2 ticket in the last 90 days: \"DataBridge Pro running extremely slowly for our team\".",
      "quote": "Hi Support, We've noticed significant performance degradation in DataBridge Pro over the past 12 days. Page loads are taking 119+ seconds and API operations are"
    }
  ],
  "talking_points": [
    "Address the performance degradation reported in TKT-10293 and confirm resolution status.",
    "Discuss the competing-vendor evaluation directly and confirm next steps to retain the account.",
    "Confirm renewal timeline and stakeholder alignment ahead of 2026-08-19."
  ],
  "churn_risk_level": "High",
  "churn_risk_reasoning": "Score=5 → High. Contributing signals: health_status=At Risk, usage_trend=Inactive",
  "tickets_considered": 1,
  "as_of_date": "2026-05-22",
  "provider": "groq",
  "error": null
}
```

And the missing-account case, handled without an exception:

```json
{
  "account_id": "ACC-00000-DOES-NOT-EXIST",
  "found": false,
  "error": "No account on file for account_id='ACC-00000-DOES-NOT-EXIST'.",
  "...": "(remaining fields null/empty)"
}
```

## Other entry points

```bash
uvicorn app.api:app --reload          # REST API — POST /triage, GET /account-brief/{id}
streamlit run ui/streamlit_app.py     # Bonus: thin UI for a non-technical agent/TAM
```

## Evaluation harness

```bash
python evals/run_evals.py
```

Runs 13 test cases (7 for Task 1, 6 for Task 2), each suite including
adversarial cases — an ambiguous ticket and a malformed ticket for Task 1;
an account with no recent tickets/empty escalation notes and a nonexistent
account_id for Task 2. Applies rule-based checks (schema validity, enum
values, verbatim-quote verification for Task 2 flags) plus LLM-as-judge
scoring for qualitative fields. Writes **`eval_report.json`**
(machine-readable) and **`eval_report.md`** (human-readable table), both
committed to this repo.

## Project layout

```
├── main.py                  # single entry point — Task 1 & 2 demo
├── app/
│   ├── api.py                 # FastAPI routes (thin wrappers over the same functions)
│   ├── llm_client.py           # Groq/Gemini abstraction, JSON-mode + retry
│   ├── data_loader.py           # tickets.json/accounts.json loading + the 90-day join
│   ├── triage/                   # Task 1
│   ├── account_brief/             # Task 2
│   └── retrieval/                  # KB chunking + BM25 search
├── evals/                    # Task 3 — harness + test cases
├── eval_report.json / .md    # Task 3 output (committed)
├── prompts/                  # versioned prompt templates (bonus)
├── ui/streamlit_app.py       # bonus UI
└── data/, knowledge-base/, DATA_SCHEMA.md   # unchanged mock dataset
```

## Design note

See **[DESIGN.md](DESIGN.md)** — failure modes, latency/quality trade-off,
data sensitivity, and scaling.
