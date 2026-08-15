# Design note

## Failure modes

**1. The LLM returns malformed or non-schema JSON.** Groq's JSON mode is
reliable but not guaranteed — a truncated response or a field with the wrong
type will fail Pydantic validation. `LLMClient.complete_json` catches
`json.JSONDecodeError`/`ValidationError`, feeds the exact error back to the
model, and retries (max 2 extra attempts) before giving up. Detection: the
retry itself surfaces in logs; in production I'd emit a metric per retry and
alert if the retry rate on a given prompt version climbs, since that usually
means the prompt has drifted out of sync with the schema. Mitigation beyond
retries: both pipelines fall back to a deterministic, rule-based path
(`_offline_classify` / `_offline_narrative`) rather than raising — I built
and rely on this fallback throughout development (it's what runs when no
API key is set), so it's exercised, not theoretical.

**2. Urgency/category misclassification on ambiguous or negated text.**
During testing, the offline fallback's keyword matcher flagged "**not**
urgent, just a nice-to-have" as P1 because it substring-matched "urgent",
ignoring the negation — fixed by checking for negation prefixes before
treating a phrase as a signal, and by giving explicit low-urgency phrasing
priority over bare P1/P2 keyword hits (`_has_signal` in
`app/triage/pipeline.py`). Separately, two eval runs against the live model
produced different classifications for the same `triage-03-sso-auth` case
(`Bug` on one run, `How-To` on another) at identical `temperature=0`. Part
of this is inherent model non-determinism — large MoE models aren't
guaranteed bit-identical output across separate calls even at temp=0, since
routing and batching happen server-side — but the prompt also gave the
model no explicit rule for the Bug-vs-How-To boundary, making that
particular call easy to land on either side of. `prompts/triage_v2.md` adds
an explicit rule: anything describing broken behavior is never How-To,
regardless of phrasing. Detection: adversarial eval cases (`triage-06`,
`triage-07`) plus re-running non-adversarial cases a few times catches this
class of flakiness. Mitigation beyond prompt tightening: for genuinely
close calls in production, self-consistency (sample the classification 2-3
times, take the majority) is worth considering for the urgency field
specifically, since that's the tier where a wrong answer is most costly —
full self-consistency on every field isn't worth the added latency/cost.

**3. Retrieval returns a wrong-but-confident KB match.** BM25 matches on
keyword overlap, not meaning — a ticket mentioning "timeout" could surface a
performance doc when the real issue is an auth timeout. Detection: the
retriever's `min_score` threshold is a blunt instrument; a better signal
would be logging matched-doc-vs-agent-override rates once a human is in the
loop. Mitigation: the prompt explicitly tells the model not to claim a KB
match with confidence beyond what's supplied, and the draft response
phrases KB references as "this looks related to," not "this is caused by."

## Latency vs quality trade-off

I used **BM25 keyword retrieval instead of embeddings** for KB matching.
With ~9 source docs (103 chunks after splitting), BM25 is instant, has zero
network dependency, and zero marginal cost — and at this corpus size it's
roughly as accurate as embeddings would be, since there's little semantic
nuance BM25's keyword overlap misses. If latency were the hard constraint
*and* the corpus grew (the actual scaling trigger — see below), I'd keep
BM25 as a fast first-pass filter and only add embeddings if recall on
paraphrased queries (e.g. "can't log in" vs. "authentication failing")
started measurably missing matches that keyword search doesn't catch.

## Data sensitivity

Ticket and account records contain real-shaped PII (contact names, titles,
company names, account financials). Two concrete choices reflect that: (1)
`account_brief/pipeline.py` strips `primary_contact` out of the JSON fact
sheet sent to the LLM — the TAM already knows who their contact is, so the
model never needs that field to do its job, and least-privilege redaction
before the prompt is more reliable than asking a system prompt to
"remember" not to leak fields it was still handed. (2) The provider choice
itself carries a sensitivity trade-off: this submission defaults to Groq
because Groq's free tier does not train on submitted data, whereas the
Gemini fallback's free tier may. For a production system handling real
customer PII, I would not use either free tier: I'd move to a paid tier
with a signed data-processing agreement and contractual zero-retention
terms, or self-host an open-weight model so ticket/account data never
leaves the company's infrastructure. I'd also add structured logging
discipline — log request IDs and classification outputs, never raw ticket
bodies, in any long-lived log store.

## Scaling

At 10x ticket volume (5,000 tickets, ~500 accounts), the first thing that
breaks is the **in-memory BM25 index and synchronous, per-request handling**
in `app/retrieval/kb_retriever.py` and the FastAPI routes as written — every
request currently does full classification inline, single-threaded from the
caller's point of view. The KB corpus itself wouldn't grow 10x just because
ticket volume did, so BM25's cost stays flat; the real pressure is on
**LLM API throughput and rate limits**, since triage is one blocking call
per ticket. I'd move to: (1) async request handling in FastAPI
(`async def` routes + an async OpenAI client) so one slow LLM call doesn't
block others, (2) a queue (e.g. SQS/Celery) so ticket ingestion and
classification decouple — tickets get triaged as capacity allows rather
than synchronously on creation, (3) batching account-brief generation for
QBR prep (these are naturally batchable, unlike live ticket triage), and
(4) only then would I revisit BM25 → a real vector store, if and when the
*knowledge base* — not the ticket volume — grows past what keyword search
handles well.
