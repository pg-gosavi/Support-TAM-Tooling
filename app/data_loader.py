"""Small shared loader for the mock dataset. Cached in-process (the dataset
is tiny — 500 tickets, 50 accounts — so this is just to avoid re-reading
disk on every call within a single run)."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def load_tickets() -> list[dict]:
    return json.loads((DATA_DIR / "tickets.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_accounts() -> list[dict]:
    return json.loads((DATA_DIR / "accounts.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def account_map() -> dict[str, dict]:
    return {a["account_id"]: a for a in load_accounts()}


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@lru_cache(maxsize=1)
def dataset_as_of_date() -> datetime:
    """The 'current time' this whole dataset is anchored to.

    We deliberately use the max `created_at` across tickets.json rather than
    the real wall-clock `datetime.now()`. Two reasons:
    1. It's the actual documented choice DATA_SCHEMA.md leaves open
       ("last 90 days ... relative to the most recent created_at in the
       dataset, or system date — pick one and document it").
    2. Using wall-clock time would make Task 2's "byte-identical output for
       the same account_id" guarantee false the moment a 90-day boundary is
       crossed between two runs, weeks or months apart. Anchoring to the
       dataset's own max date makes the 90-day window — and therefore the
       whole brief — fully deterministic regardless of when it's run.
    """
    tickets = load_tickets()
    return max(parse_iso(t["created_at"]) for t in tickets)


def get_account_tickets(account_id: str, days: int = 90) -> list[dict]:
    from datetime import timedelta

    cutoff = dataset_as_of_date() - timedelta(days=days)
    return [
        t
        for t in load_tickets()
        if t["account_id"] == account_id and parse_iso(t["created_at"]) > cutoff
    ]
