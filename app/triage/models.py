from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IssueCategory(str, Enum):
    BUG = "Bug"
    FEATURE_REQUEST = "Feature Request"
    HOW_TO = "How-To"
    PERFORMANCE = "Performance"
    BILLING = "Billing"
    INTEGRATION = "Integration"
    ONBOARDING = "Onboarding"
    DATA_LOSS = "Data Loss"
    UNKNOWN = "Unknown"  # graceful fallback for genuinely ambiguous tickets


class UrgencyTier(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TicketInput(BaseModel):
    """Accepts either {subject, body} or a single raw-text blob."""

    subject: Optional[str] = None
    body: Optional[str] = None
    text: Optional[str] = None  # used when the caller only has raw free text

    def resolved_subject_body(self) -> tuple[str, str]:
        """Best-effort split into (subject, body), never raising."""
        if self.subject or self.body:
            return (self.subject or "").strip(), (self.body or "").strip()
        raw = (self.text or "").strip()
        if not raw:
            return "", ""
        lines = raw.split("\n", 1)
        if len(lines) == 2 and len(lines[0]) <= 120:
            return lines[0].strip(), lines[1].strip()
        return "", raw


class ClassificationField(BaseModel):
    value: str
    reasoning: str


class MatchedKBDoc(BaseModel):
    doc_path: str
    section: str
    score: float


class TriageResult(BaseModel):
    product_area: ClassificationField
    issue_category: ClassificationField
    urgency_tier: ClassificationField
    matched_kb_doc: Optional[MatchedKBDoc] = None
    recommended_team: str
    draft_first_response: str
    warnings: list[str] = Field(default_factory=list)
    provider: str = "offline"  # "groq" | "gemini" | "offline" — which path produced this


class _LLMTriageJudgment(BaseModel):
    """What we actually ask the LLM for — narrower than TriageResult.

    Retrieval (matched_kb_doc) and recommended_team are decided by
    deterministic code, not the model — this keeps the parts of the output
    that matter for routing/reporting stable and reduces hallucination risk.
    """

    product_area: str
    product_area_reasoning: str
    issue_category: str
    issue_category_reasoning: str
    urgency_tier: str
    urgency_tier_reasoning: str
    draft_first_response: str
