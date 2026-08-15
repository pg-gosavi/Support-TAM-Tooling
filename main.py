#!/usr/bin/env python3
"""
Single entry point: `python main.py`

Runs a live demo of Task 1 (ticket triage) and Task 2 (account brief)
against the provided mock dataset.
"""

from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

load_dotenv()

from app.account_brief.pipeline import generate_account_brief  # noqa: E402
from app.data_loader import load_accounts, load_tickets  # noqa: E402
from app.llm_client import get_client  # noqa: E402
from app.triage.pipeline import triage_ticket  # noqa: E402

SEP = "=" * 78


def _print_header(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def _print_provider_banner() -> None:
    client = get_client()
    if client.available:
        print(f"LLM provider: {client.provider} ({client.model})")
    else:
        print(
            "LLM provider: none configured — running in OFFLINE fallback mode "
            "(deterministic rule-based classification/summaries).\n"
            "  → Copy .env.example to .env and set GROQ_API_KEY to see real LLM output."
        )


def demo_task1() -> None:
    _print_header("TASK 1 — Ticket triage")
    tickets = load_tickets()

    real_ticket = tickets[0]
    print(f"\n--- Sample ticket (from dataset): {real_ticket['ticket_id']} ---")
    result = triage_ticket({"subject": real_ticket["subject"], "body": real_ticket["body"]})
    print(json.dumps(result.model_dump(), indent=2))

    print("\n--- Adversarial sample: deliberately ambiguous ticket ---")
    ambiguous = {
        "subject": "question",
        "body": "hi it's not working can someone help thanks",
    }
    result2 = triage_ticket(ambiguous)
    print(json.dumps(result2.model_dump(), indent=2))


def demo_task2() -> None:
    _print_header("TASK 2 — TAM account health brief")
    accounts = load_accounts()

    real_account_id = accounts[0]["account_id"]
    print(f"\n--- Sample account: {real_account_id} ({accounts[0]['company']}) ---")
    brief = generate_account_brief(real_account_id)
    print(json.dumps(brief.model_dump(), indent=2))

    print("\n--- Adversarial sample: unknown account_id ---")
    missing_brief = generate_account_brief("ACC-00000-DOES-NOT-EXIST")
    print(json.dumps(missing_brief.model_dump(), indent=2))


def main() -> int:
    print("Support & TAM Tooling — live demo (Task 1 + Task 2)")
    _print_provider_banner()
    demo_task1()
    demo_task2()

    print(f"\n{SEP}")
    print("Demo complete.")
    print(SEP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
