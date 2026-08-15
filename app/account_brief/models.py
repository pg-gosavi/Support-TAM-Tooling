from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TicketFlag(BaseModel):
    ticket_id: str
    signal_type: str   # e.g. "repeated_p1", "escalation_note", "negative_language", "declining_health"
    reason: str         # short human-readable explanation
    quote: str           # verbatim substring copied from the ticket body or escalation note


class AccountBrief(BaseModel):
    account_id: str
    found: bool
    company: Optional[str] = None

    executive_summary: Optional[str] = None
    open_risks: list[TicketFlag] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)

    churn_risk_level: Optional[str] = None  # "Low" | "Medium" | "High"
    churn_risk_reasoning: Optional[str] = None

    tickets_considered: int = 0
    as_of_date: Optional[str] = None
    provider: str = "offline"

    error: Optional[str] = None


class _LLMBriefNarrative(BaseModel):
    """What we ask the LLM to write. It only narrates facts we hand it —
    it does not decide which tickets are risky or invent quotes; that's done
    deterministically in pipeline.py so flags/quotes stay verifiable."""

    executive_summary: str
    talking_points: list[str]
