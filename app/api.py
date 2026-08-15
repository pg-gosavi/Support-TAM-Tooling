"""FastAPI layer. Both routes are thin wrappers around the same callable
Python functions used everywhere else (app/triage/pipeline.py,
app/account_brief/pipeline.py) — no duplicated logic."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.account_brief.models import AccountBrief
from app.account_brief.pipeline import generate_account_brief
from app.triage.models import TicketInput, TriageResult
from app.triage.pipeline import triage_ticket

app = FastAPI(
    title="Support & TAM Tooling API",
    description="Task 1 (ticket triage) and Task 2 (account brief) as REST endpoints.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageResult)
def triage_endpoint(ticket: TicketInput) -> TriageResult:
    return triage_ticket(ticket.model_dump())


@app.get("/account-brief/{account_id}", response_model=AccountBrief)
def account_brief_endpoint(account_id: str) -> AccountBrief:
    brief = generate_account_brief(account_id)
    return brief
