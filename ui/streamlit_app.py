"""
Bonus: thin Streamlit UI over Task 1 + Task 2, meant for a non-technical
support agent or TAM to actually use — not a developer console.

Run with: streamlit run ui/streamlit_app.py  (from the repo root)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app.account_brief.pipeline import generate_account_brief  # noqa: E402
from app.data_loader import load_accounts, load_tickets  # noqa: E402
from app.llm_client import get_client  # noqa: E402
from app.triage.pipeline import triage_ticket  # noqa: E402

st.set_page_config(page_title="Support & TAM Tooling", page_icon="🛠️", layout="wide")

client = get_client()
with st.sidebar:
    st.markdown("### LLM provider")
    if client.available:
        st.success(f"{client.provider} ({client.model})")
    else:
        st.warning("No API key configured — running offline fallback mode.\n\nSet `GROQ_API_KEY` in `.env` for real LLM output.")
    st.caption("See `.env.example` for setup.")

tab1, tab2 = st.tabs(["🎫 Ticket Triage", "📋 Account Brief"])

with tab1:
    st.header("Ticket triage")
    tickets = load_tickets()
    sample_ids = ["(write your own)"] + [t["ticket_id"] for t in tickets[:15]]
    choice = st.selectbox("Try a sample ticket, or write your own below:", sample_ids)

    if choice != "(write your own)":
        sample = next(t for t in tickets if t["ticket_id"] == choice)
        default_subject, default_body = sample["subject"], sample["body"]
    else:
        default_subject, default_body = "", ""

    subject = st.text_input("Subject", value=default_subject)
    body = st.text_area("Body", value=default_body, height=180)

    if st.button("Triage this ticket", type="primary"):
        with st.spinner("Classifying..."):
            result = triage_ticket({"subject": subject, "body": body})

        col1, col2, col3 = st.columns(3)
        col1.metric("Product area", result.product_area.value)
        col2.metric("Category", result.issue_category.value)
        col3.metric("Urgency", result.urgency_tier.value)

        with st.expander("Reasoning"):
            st.write(f"**Product area:** {result.product_area.reasoning}")
            st.write(f"**Category:** {result.issue_category.reasoning}")
            st.write(f"**Urgency:** {result.urgency_tier.reasoning}")

        st.markdown(f"**Recommended team:** {result.recommended_team}")

        if result.matched_kb_doc:
            st.info(f"📚 Matched KB doc: `{result.matched_kb_doc.doc_path}` — {result.matched_kb_doc.section} "
                    f"(score {result.matched_kb_doc.score})")
        else:
            st.caption("No confident knowledge-base match.")

        st.markdown("**Draft first response:**")
        st.text_area("draft", value=result.draft_first_response, height=140, label_visibility="collapsed")

        if result.warnings:
            for w in result.warnings:
                st.caption(f"⚠️ {w}")

with tab2:
    st.header("TAM account brief")
    accounts = load_accounts()
    account_options = {f"{a['account_id']} — {a['company']}": a["account_id"] for a in accounts}
    label = st.selectbox("Choose an account:", list(account_options.keys()))
    account_id = account_options[label]

    if st.button("Generate brief", type="primary"):
        with st.spinner("Building brief..."):
            brief = generate_account_brief(account_id)

        if not brief.found:
            st.error(brief.error)
        else:
            st.subheader(f"{brief.company}  ·  churn risk: {brief.churn_risk_level}")
            st.caption(f"As of {brief.as_of_date} · {brief.tickets_considered} ticket(s) considered · provider: {brief.provider}")

            st.markdown("### Executive summary")
            st.write(brief.executive_summary)

            st.markdown("### Open risks & flagged issues")
            if not brief.open_risks:
                st.write("No specific risk signals identified.")
            for flag in brief.open_risks:
                st.markdown(f"- **{flag.signal_type}** ({flag.ticket_id}): {flag.reason}\n\n  > {flag.quote}")

            st.markdown("### Recommended talking points")
            for point in brief.talking_points:
                st.markdown(f"- {point}")
