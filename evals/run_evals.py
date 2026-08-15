#!/usr/bin/env python3
"""
Task 3 — Evaluation harness. Runnable standalone: `python evals/run_evals.py`

For each test case (Task 1: evals/cases_triage.json, Task 2:
evals/cases_account_brief.json) this:
  1. Runs the real pipeline function (no mocking of the system under test).
  2. Applies rule-based checks: schema validity, required fields present,
     correct enum values, and — for Task 2 — a "quote is verbatim from its
     source" check (whitespace-normalized substring match against the
     ticket body or escalation note the flag claims to quote).
  3. Applies a lightweight LLM-as-judge score (0-1) for the qualitative
     fields (draft_first_response for Task 1; executive_summary +
     talking_points for Task 2). If no LLM provider is configured, this
     falls back to a clearly-labelled heuristic proxy score instead of
     failing the whole harness — see `_heuristic_quality_score`.
  4. Writes eval_report.json (machine-readable) and eval_report.md
     (human-readable) with per-case pass/fail + quality score, and an
     overall pass rate.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.account_brief.pipeline import generate_account_brief  # noqa: E402
from app.llm_client import LLMOutputError, LLMUnavailableError, get_client  # noqa: E402
from app.triage.pipeline import triage_ticket  # noqa: E402
from pydantic import BaseModel  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class JudgeScore(BaseModel):
    score: float
    reasoning: str


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _quote_is_verbatim(quote: str, source: str) -> bool:
    return _normalize_ws(quote) in _normalize_ws(source)


def _heuristic_quality_score(text: str) -> tuple[float, str]:
    """Non-LLM proxy used only when no LLM provider is configured. This is
    intentionally crude (word-count sanity check) — it exists so the harness
    still produces *a* quality signal offline, not as a substitute for real
    LLM-as-judge scoring. `judge_method` in the report always says which one
    ran."""
    words = text.split()
    if not words:
        return 0.0, "Empty output."
    if 8 <= len(words) <= 250:
        return 0.7, "Heuristic proxy: length is in a plausible range (no LLM judge available)."
    return 0.4, "Heuristic proxy: unusually short or long output (no LLM judge available)."


def _llm_judge(prompt: str) -> tuple[float, str, str]:
    """Returns (score, reasoning, method) where method is 'llm' or 'heuristic'."""
    client = get_client()
    if not client.available:
        score, reasoning = _heuristic_quality_score(prompt)
        return score, reasoning, "heuristic"
    try:
        result = client.complete_json(
            system_prompt=(
                "You are a strict QA judge for an internal support/TAM tool. "
                "Score the given text 0.0-1.0 on relevance, professionalism, and "
                "groundedness (no invented facts). Respond with ONLY JSON: "
                '{"score": <float 0-1>, "reasoning": "<one sentence>"}.'
            ),
            user_prompt=prompt,
            schema=JudgeScore,
            temperature=0.0,
        )
        return max(0.0, min(1.0, result.score)), result.reasoning, "llm"
    except (LLMUnavailableError, LLMOutputError) as exc:
        score, reasoning = _heuristic_quality_score(prompt)
        return score, f"{reasoning} (LLM judge call failed: {exc})", "heuristic"
    finally:
        # Groq's free tier is capped per-minute (30 req/min at time of writing),
        # and this harness fires ~2 LLM calls per case (classify/summarise +
        # judge) back-to-back. A small pause between calls keeps us comfortably
        # under that ceiling instead of bursting into 429s. Harmless no-op in
        # offline/heuristic mode since we still want consistent pacing if a key
        # gets added mid-run.
        if client.available:
            time.sleep(2.2)


def run_triage_cases(cases: list[dict]) -> list[dict]:
    results = []
    for case in cases:
        rule_checks: dict[str, bool] = {}
        try:
            result = triage_ticket(case["input"])
            rule_checks["did_not_crash"] = True
            if get_client().available:
                time.sleep(2.2)  # pace pipeline LLM call under Groq's per-minute cap
        except Exception as exc:  # noqa: BLE001 - eval harness must capture, not propagate
            results.append(
                {
                    "id": case["id"],
                    "adversarial": case.get("adversarial", False),
                    "passed": False,
                    "quality_score": 0.0,
                    "judge_method": "n/a",
                    "rule_checks": {"did_not_crash": False},
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        accept = case["acceptance"]
        if "issue_category_in" in accept:
            rule_checks["issue_category_valid"] = result.issue_category.value in accept["issue_category_in"]
        if "urgency_tier_in" in accept:
            rule_checks["urgency_tier_valid"] = result.urgency_tier.value in accept["urgency_tier_in"]
        if accept.get("kb_match_required"):
            rule_checks["kb_match_present"] = result.matched_kb_doc is not None
        if "min_draft_response_words" in accept:
            n_words = len(result.draft_first_response.split())
            rule_checks["draft_response_length_ok"] = n_words >= accept["min_draft_response_words"]
        rule_checks["schema_valid"] = True  # reaching here means Pydantic validation already passed

        judge_prompt = (
            f"Ticket subject: {case['input'].get('subject', '')}\n"
            f"Ticket body: {case['input'].get('body', '')}\n\n"
            f"Draft first response to grade:\n{result.draft_first_response}"
        )
        score, reasoning, method = _llm_judge(judge_prompt)

        passed = all(rule_checks.values())
        results.append(
            {
                "id": case["id"],
                "adversarial": case.get("adversarial", False),
                "passed": passed,
                "quality_score": round(score, 3),
                "judge_method": method,
                "judge_reasoning": reasoning,
                "rule_checks": rule_checks,
                "output_summary": {
                    "issue_category": result.issue_category.value,
                    "urgency_tier": result.urgency_tier.value,
                    "matched_kb_doc": result.matched_kb_doc.doc_path if result.matched_kb_doc else None,
                    "provider": result.provider,
                },
            }
        )
    return results


def run_account_brief_cases(cases: list[dict]) -> list[dict]:
    results = []
    for case in cases:
        rule_checks: dict[str, bool] = {}
        try:
            brief = generate_account_brief(case["input"]["account_id"], use_cache=True)
            rule_checks["did_not_crash"] = True
            if get_client().available:
                time.sleep(2.2)  # pace pipeline LLM call under Groq's per-minute cap
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "id": case["id"],
                    "adversarial": case.get("adversarial", False),
                    "passed": False,
                    "quality_score": 0.0,
                    "judge_method": "n/a",
                    "rule_checks": {"did_not_crash": False},
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        accept = case["acceptance"]
        if "found" in accept:
            rule_checks["found_matches_expected"] = brief.found == accept["found"]
        if accept.get("error_present"):
            rule_checks["error_present"] = bool(brief.error)
        if "min_open_risks" in accept:
            rule_checks["min_open_risks_met"] = len(brief.open_risks) >= accept["min_open_risks"]
        if "churn_risk_level_in" in accept and brief.found:
            rule_checks["churn_risk_level_valid"] = brief.churn_risk_level in accept["churn_risk_level_in"]
        if "tickets_considered_equals" in accept:
            rule_checks["tickets_considered_matches"] = brief.tickets_considered == accept["tickets_considered_equals"]

        # Quote-is-verbatim check, only meaningful when the account was found.
        if brief.found and brief.open_risks:
            from app.data_loader import load_tickets

            tickets_by_id = {t["ticket_id"]: t for t in load_tickets()}
            account = None
            from app.data_loader import account_map

            account = account_map().get(brief.account_id)
            escalation_notes = account.get("escalation_notes", []) if account else []

            all_verbatim = True
            for flag in brief.open_risks:
                if flag.ticket_id == "(account escalation note)":
                    ok = any(_quote_is_verbatim(flag.quote, note) for note in escalation_notes)
                else:
                    ticket = tickets_by_id.get(flag.ticket_id)
                    ok = bool(ticket) and _quote_is_verbatim(flag.quote, ticket["body"])
                all_verbatim = all_verbatim and ok
            rule_checks["all_quotes_verbatim"] = all_verbatim

        if brief.found:
            judge_prompt = (
                f"Account facts: churn_risk_level={brief.churn_risk_level}, "
                f"tickets_considered={brief.tickets_considered}, "
                f"num_open_risks={len(brief.open_risks)}\n\n"
                f"Executive summary to grade:\n{brief.executive_summary}\n\n"
                f"Talking points to grade:\n" + "\n".join(f"- {p}" for p in brief.talking_points)
            )
            score, reasoning, method = _llm_judge(judge_prompt)
        else:
            score, reasoning, method = (1.0 if brief.error else 0.0), "Graceful not-found handling.", "rule-based"

        passed = all(rule_checks.values()) if rule_checks else False
        results.append(
            {
                "id": case["id"],
                "adversarial": case.get("adversarial", False),
                "passed": passed,
                "quality_score": round(score, 3),
                "judge_method": method,
                "judge_reasoning": reasoning,
                "rule_checks": rule_checks,
                "output_summary": {
                    "found": brief.found,
                    "churn_risk_level": brief.churn_risk_level,
                    "tickets_considered": brief.tickets_considered,
                    "num_open_risks": len(brief.open_risks),
                    "provider": brief.provider,
                },
            }
        )
    return results


def _write_markdown_report(report: dict, path: Path) -> None:
    lines = ["# Eval Report", ""]
    lines.append(f"**Overall pass rate:** {report['overall_pass_rate']:.0%} "
                 f"({report['total_passed']}/{report['total_cases']} cases)")
    lines.append(f"**Average quality score:** {report['overall_avg_quality_score']:.2f}")
    lines.append(f"**LLM-as-judge mode:** {report['judge_mode']}")
    lines.append("")

    for suite_name, suite in [("Task 1 — Triage", report["triage"]), ("Task 2 — Account Brief", report["account_brief"])]:
        lines.append(f"## {suite_name}")
        lines.append("")
        lines.append(f"Pass rate: {suite['pass_rate']:.0%} ({suite['passed']}/{suite['total']}) · "
                      f"Avg quality: {suite['avg_quality_score']:.2f}")
        lines.append("")
        lines.append("| Case | Adversarial | Passed | Quality | Judge method | Notes |")
        lines.append("|---|---|---|---|---|---|")
        for r in suite["results"]:
            note = r.get("error") or r.get("judge_reasoning", "")
            note = (note[:80] + "…") if len(note) > 80 else note
            lines.append(
                f"| `{r['id']}` | {'✓' if r['adversarial'] else ''} | "
                f"{'✅' if r['passed'] else '❌'} | {r['quality_score']:.2f} | "
                f"{r['judge_method']} | {note} |"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    triage_cases = json.loads((ROOT / "evals" / "cases_triage.json").read_text())
    brief_cases = json.loads((ROOT / "evals" / "cases_account_brief.json").read_text())

    client = get_client()
    judge_mode = f"llm ({client.provider})" if client.available else "heuristic (no LLM provider configured)"
    print(f"Eval harness — judge mode: {judge_mode}")

    triage_results = run_triage_cases(triage_cases)
    brief_results = run_account_brief_cases(brief_cases)

    def _summarize(results: list[dict]) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r["passed"])
        avg_q = sum(r["quality_score"] for r in results) / total if total else 0.0
        return {"total": total, "passed": passed, "pass_rate": passed / total if total else 0.0,
                "avg_quality_score": avg_q, "results": results}

    triage_summary = _summarize(triage_results)
    brief_summary = _summarize(brief_results)

    total_cases = triage_summary["total"] + brief_summary["total"]
    total_passed = triage_summary["passed"] + brief_summary["passed"]
    all_scores = [r["quality_score"] for r in triage_results + brief_results]

    report = {
        "judge_mode": judge_mode,
        "total_cases": total_cases,
        "total_passed": total_passed,
        "overall_pass_rate": total_passed / total_cases if total_cases else 0.0,
        "overall_avg_quality_score": sum(all_scores) / len(all_scores) if all_scores else 0.0,
        "triage": triage_summary,
        "account_brief": brief_summary,
    }

    (ROOT / "eval_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    _write_markdown_report(report, ROOT / "eval_report.md")

    print(f"\nOverall: {total_passed}/{total_cases} passed "
          f"({report['overall_pass_rate']:.0%}), avg quality {report['overall_avg_quality_score']:.2f}")
    print("Wrote eval_report.json and eval_report.md")

    return 0 if total_passed == total_cases else 1


if __name__ == "__main__":
    sys.exit(main())
