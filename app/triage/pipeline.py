"""
Task 1 — Intelligent ticket triage agent.

Design notes:
- Retrieval (which KB doc, if any, matches) and recommended_team are decided
  by deterministic code, NOT the LLM. Only the three classification fields
  and the draft response text are LLM-generated. This keeps the parts of the
  output that matter for downstream routing/reporting stable and auditable,
  and keeps the LLM's job narrow (less surface area to hallucinate on).
- If no LLM provider is configured, `triage_ticket` falls back to a
  keyword-based offline classifier rather than raising, so the pipeline
  (and `python main.py`) still runs end-to-end with zero configuration.
  `TriageResult.provider` tells you which path actually produced a given
  result ("groq" / "gemini" / "offline").
"""

from __future__ import annotations

import re
from pathlib import Path

from app.llm_client import LLMOutputError, LLMUnavailableError, get_client
from app.retrieval.kb_retriever import get_retriever
from app.triage.models import (
    ClassificationField,
    IssueCategory,
    MatchedKBDoc,
    TriageResult,
    TicketInput,
    UrgencyTier,
    _LLMTriageJudgment,
)

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "triage_v2.md"

_CATEGORY_TO_TEAM = {
    IssueCategory.BUG: "Product Engineering",
    IssueCategory.FEATURE_REQUEST: "Product Management",
    IssueCategory.HOW_TO: "Technical Support (Tier 1)",
    IssueCategory.PERFORMANCE: "Platform Engineering",
    IssueCategory.BILLING: "Billing Support",
    IssueCategory.INTEGRATION: "Platform Engineering",
    IssueCategory.ONBOARDING: "Customer Onboarding",
    IssueCategory.DATA_LOSS: "Product Engineering (Escalations)",
    IssueCategory.UNKNOWN: "Technical Support (Tier 1) — needs manual triage",
}

_PRODUCT_NAMES = [
    "DataBridge Pro",
    "CloudSync",
    "AnalyticsHub",
    "SecureVault",
    "WorkflowEngine",
]

_P1_WORDS = ["outage", "production down", "down for all", "business stopped", "critical",
             "all users", "cannot access", "data loss", "urgent", "asap", "sev1", "sev-1"]
_P2_WORDS = ["major", "significant", "many users", "workaround", "blocked", "47 users",
             "large number of"]
_P4_WORDS = ["cosmetic", "minor", "small issue", "when you get a chance", "no rush",
             "typo", "nice to have", "not urgent", "no urgency", "whenever you get a chance"]

_NEGATION_PREFIXES = ("not ", "no ", "isn't ", "isnt ", "aren't ", "arent ", "without ")


def _has_signal(text: str, phrases: list[str]) -> bool:
    """Substring match that ignores hits immediately preceded by a negation
    (e.g. "not urgent" must not trip the "urgent" P1 signal)."""
    for phrase in phrases:
        start = 0
        while True:
            idx = text.find(phrase, start)
            if idx == -1:
                break
            prefix = text[max(0, idx - 12):idx]
            if not any(prefix.endswith(neg) for neg in _NEGATION_PREFIXES):
                return True
            start = idx + 1
    return False

_CATEGORY_KEYWORDS = {
    IssueCategory.BILLING: ["invoice", "billing", "charge", "payment", "renewal price",
                             "seat count", "overage", "subscription cost"],
    IssueCategory.DATA_LOSS: ["deleted", "data loss", "missing records", "lost data",
                               "corrupted", "can't recover", "cannot recover"],
    IssueCategory.ONBOARDING: ["onboarding", "new user", "getting started", "set up my account",
                                "first time", "provisioning"],
    IssueCategory.HOW_TO: ["how do i", "how to", "documentation", "where can i find",
                            "is it possible to"],
    IssueCategory.FEATURE_REQUEST: ["feature request", "would be great if", "could you add",
                                     "please add", "expected behaviour", "expected behavior",
                                     "currently only allows"],
    IssueCategory.PERFORMANCE: ["slow", "timeout", "latency", "performance", "lag", "throughput"],
    IssueCategory.INTEGRATION: ["sso", "saml", "oauth", "connector", "integration", "webhook",
                                 "api key"],
    IssueCategory.BUG: ["error", "bug", "fails", "failing", "broken", "exception", "crash"],
}


def _offline_classify(subject: str, body: str, kb_match: dict | None) -> _LLMTriageJudgment:
    """Deterministic keyword-based fallback used when no LLM API key is configured."""
    text = f"{subject}\n{body}".lower()

    product_area = "Unknown"
    for name in _PRODUCT_NAMES:
        if name.lower() in text:
            product_area = name
            break
    if product_area == "Unknown" and kb_match:
        product_area = kb_match["section"].split(">")[0].strip()

    category = IssueCategory.UNKNOWN
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            category = cat
            break

    # Check explicit low-urgency phrasing first — it's more specific than a
    # bare "urgent"/"critical" hit and should win over the negation-stripped
    # substring checks below (e.g. "not urgent" implies P4, not P1).
    if any(w in text for w in _P4_WORDS):
        urgency = UrgencyTier.P4
    elif _has_signal(text, _P1_WORDS):
        urgency = UrgencyTier.P1
    elif _has_signal(text, _P2_WORDS):
        urgency = UrgencyTier.P2
    else:
        urgency = UrgencyTier.P3

    draft = (
        f"Hi there,\n\nThanks for reaching out — we've logged this as a "
        f"{category.value if category != IssueCategory.UNKNOWN else 'support'} issue"
        f"{' regarding ' + product_area if product_area != 'Unknown' else ''}. "
    )
    if kb_match:
        draft += (
            f"This looks related to our '{kb_match['section']}' documentation "
            f"({kb_match['doc_path']}), which we'd recommend reviewing while our team "
            f"investigates further. "
        )
    draft += "We'll follow up with next steps shortly.\n\n— Support Team"

    return _LLMTriageJudgment(
        product_area=product_area,
        product_area_reasoning=(
            "Offline fallback: matched against known product names / KB section "
            "(no LLM provider configured)."
        ),
        issue_category=category.value,
        issue_category_reasoning="Offline fallback: keyword-based heuristic match.",
        urgency_tier=urgency.value,
        urgency_tier_reasoning="Offline fallback: keyword-based impact heuristic.",
        draft_first_response=draft,
    )


def _safe_enum(enum_cls, raw_value: str, default):
    try:
        return enum_cls(raw_value)
    except ValueError:
        # Be lenient about near-misses (e.g. "P1 " or "bug") before giving up.
        normalized = raw_value.strip()
        for member in enum_cls:
            if member.value.lower() == normalized.lower():
                return member
        return default


def triage_ticket(ticket: dict) -> TriageResult:
    """Classify a raw support ticket. Never raises on malformed/ambiguous input."""
    warnings: list[str] = []
    parsed_input = TicketInput.model_validate(ticket)
    subject, body = parsed_input.resolved_subject_body()

    if not subject and not body:
        warnings.append("No subject/body/text provided — classification is a conservative default.")

    query_text = f"{subject} {body}".strip()
    retriever = get_retriever()
    kb_match = retriever.best_match(query_text) if query_text else None

    client = get_client()
    provider = "offline"

    if not query_text:
        judgment = _LLMTriageJudgment(
            product_area="Unknown",
            product_area_reasoning="No ticket text was provided.",
            issue_category=IssueCategory.UNKNOWN.value,
            issue_category_reasoning="No ticket text was provided.",
            urgency_tier=UrgencyTier.P4.value,
            urgency_tier_reasoning="Defaulting to lowest urgency conservatively; nothing to assess.",
            draft_first_response=(
                "Hi there, thanks for reaching out. Could you share a bit more detail about "
                "the issue you're experiencing so we can route this to the right team?"
            ),
        )
    elif client.available:
        system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        kb_context = (
            f"Matched KB excerpt ({kb_match['doc_path']} — {kb_match['section']}):\n{kb_match['text'][:800]}"
            if kb_match
            else "No confident knowledge-base match was found for this ticket."
        )
        user_prompt = (
            f"Subject: {subject or '(no subject provided)'}\n\n"
            f"Body:\n{body or '(no body provided)'}\n\n"
            f"{kb_context}"
        )
        try:
            judgment = client.complete_json(system_prompt, user_prompt, _LLMTriageJudgment)
            provider = client.provider
        except (LLMUnavailableError, LLMOutputError) as exc:
            warnings.append(f"LLM classification failed, used offline fallback: {exc}")
            judgment = _offline_classify(subject, body, kb_match)
    else:
        warnings.append("No GROQ_API_KEY/GEMINI_API_KEY configured — used offline fallback classifier.")
        judgment = _offline_classify(subject, body, kb_match)

    category_enum = _safe_enum(IssueCategory, judgment.issue_category, IssueCategory.UNKNOWN)
    urgency_enum = _safe_enum(UrgencyTier, judgment.urgency_tier, UrgencyTier.P3)
    if judgment.issue_category != category_enum.value:
        warnings.append(f"Model returned non-enum issue_category '{judgment.issue_category}'; coerced.")
    if judgment.urgency_tier != urgency_enum.value:
        warnings.append(f"Model returned non-enum urgency_tier '{judgment.urgency_tier}'; coerced.")

    recommended_team = _CATEGORY_TO_TEAM[category_enum]

    return TriageResult(
        product_area=ClassificationField(value=judgment.product_area, reasoning=judgment.product_area_reasoning),
        issue_category=ClassificationField(value=category_enum.value, reasoning=judgment.issue_category_reasoning),
        urgency_tier=ClassificationField(value=urgency_enum.value, reasoning=judgment.urgency_tier_reasoning),
        matched_kb_doc=(
            MatchedKBDoc(doc_path=kb_match["doc_path"], section=kb_match["section"], score=kb_match["score"])
            if kb_match
            else None
        ),
        recommended_team=recommended_team,
        draft_first_response=judgment.draft_first_response,
        warnings=warnings,
        provider=provider,
    )
