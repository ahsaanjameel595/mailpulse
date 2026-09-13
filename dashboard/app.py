"""
MailPulse Dashboard — the ONE screen a non-technical client needs.
Covers: uploading recipients, creating a campaign, sending it, and viewing
analytics — all through buttons and forms, no API docs or terminal needed.

Run with: streamlit run dashboard/app.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import csv
import json
import streamlit as st
import pandas as pd
from sqlalchemy import func

from app.database import SessionLocal
from app.models import Campaign, Recipient, Send, Open, Reply, Click
from app.services import send_campaign_now

st.set_page_config(page_title="MailPulse", layout="wide", page_icon="📬")
st.title("📬 MailPulse")

page = st.sidebar.radio("Go to", ["👥 Recipients", "✉️ Create & Send", "📊 Analytics"])

# ============================================================
# RECIPIENTS PAGE
# ============================================================
if page == "👥 Recipients":
    st.header("Recipients")

    db = SessionLocal()
    recipients = db.query(Recipient).all()

    st.subheader("Add recipients")
    tab1, tab2 = st.tabs(["Upload CSV", "Add one manually"])

    with tab1:
        st.caption("CSV columns expected: name, email, company, role")
        uploaded = st.file_uploader("Choose a CSV file", type="csv")
        if uploaded is not None and st.button("Upload"):
            content = uploaded.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            added, skipped = 0, 0
            known = {"name", "email", "company", "role"}
            for row in reader:
                if not row.get("email"):
                    continue
                if db.query(Recipient).filter(Recipient.email == row["email"]).first():
                    skipped += 1
                    continue
                custom = {k: v for k, v in row.items() if k not in known}
                db.add(Recipient(
                    name=row.get("name", ""),
                    email=row["email"],
                    company=row.get("company"),
                    role=row.get("role"),
                    custom_fields=json.dumps(custom),
                ))
                added += 1
            db.commit()
            st.success(f"Added {added} new recipients ({skipped} already existed and were skipped).")
            st.rerun()

    with tab2:
        with st.form("add_recipient_form", clear_on_submit=True):
            name = st.text_input("Name")
            email = st.text_input("Email")
            company = st.text_input("Company (optional)")
            role = st.text_input("Role (optional)")
            submitted = st.form_submit_button("Add recipient")
            if submitted:
                if not name or not email:
                    st.error("Name and email are required.")
                elif db.query(Recipient).filter(Recipient.email == email).first():
                    st.error("A recipient with this email already exists.")
                else:
                    db.add(Recipient(name=name, email=email, company=company, role=role, custom_fields="{}"))
                    db.commit()
                    st.success(f"Added {name}.")
                    st.rerun()

    st.subheader(f"Current recipients ({len(recipients)})")
    if recipients:
        st.dataframe(pd.DataFrame([
            {"Name": r.name, "Email": r.email, "Company": r.company, "Role": r.role}
            for r in recipients
        ]), use_container_width=True)
    else:
        st.info("No recipients yet — upload a CSV or add one above.")

    db.close()

# ============================================================
# CREATE & SEND PAGE
# ============================================================
elif page == "✉️ Create & Send":
    st.header("Create & Send a Campaign")

    db = SessionLocal()
    recipients = db.query(Recipient).all()

    st.caption(
        "Use {name}, {company}, {role} inside your subject/body — each recipient "
        "gets their own version automatically."
    )

    with st.form("create_campaign_form"):
        name = st.text_input("Campaign name", placeholder="e.g. October Outreach")
        subject = st.text_input("Subject line", placeholder="Hi {name}, quick question")
        body = st.text_area(
            "Email body (HTML allowed)",
            placeholder="<p>Hi {name}, ...</p>",
            height=180,
        )
        with st.expander("Follow-up (optional — sent automatically if no reply)"):
            follow_up_days = st.number_input("Send follow-up after how many days?", min_value=1, value=3)
            max_follow_ups = st.number_input("Maximum follow-ups", min_value=0, value=1)
            follow_up_subject = st.text_input("Follow-up subject", placeholder="Following up, {name}")
            follow_up_body = st.text_area("Follow-up body (HTML allowed)", placeholder="<p>Just checking in...</p>")

        create_submitted = st.form_submit_button("Create Campaign")
        if create_submitted:
            if not name or not subject or not body:
                st.error("Campaign name, subject, and body are required.")
            else:
                campaign = Campaign(
                    name=name,
                    subject_template=subject,
                    body_template=body,
                    follow_up_subject_template=follow_up_subject or None,
                    follow_up_body_template=follow_up_body or None,
                    follow_up_after_days=int(follow_up_days),
                    max_follow_ups=int(max_follow_ups),
                )
                db.add(campaign)
                db.commit()
                st.success(f"Campaign '{name}' created. Scroll down to send it.")
                st.rerun()

    st.divider()
    st.subheader("Send an existing campaign")

    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    if not campaigns:
        st.info("No campaigns yet — create one above first.")
    else:
        campaign_options = {c.id: f"{c.name} (created {c.created_at.strftime('%Y-%m-%d %H:%M')})" for c in campaigns}
        selected_campaign_id = st.selectbox(
            "Which campaign?", options=list(campaign_options.keys()), format_func=lambda x: campaign_options[x]
        )

        if not recipients:
            st.warning("No recipients yet — add some on the Recipients page first.")
        else:
            recipient_options = {r.id: f"{r.name} <{r.email}>" for r in recipients}
            select_all = st.checkbox("Send to all recipients", value=True)
            chosen_ids = None
            if not select_all:
                chosen_ids = st.multiselect(
                    "Choose recipients", options=list(recipient_options.keys()),
                    format_func=lambda x: recipient_options[x],
                )

            if st.button("🚀 Send Now", type="primary"):
                with st.spinner("Sending emails..."):
                    results = send_campaign_now(db, selected_campaign_id, chosen_ids if not select_all else None)
                sent = len([r for r in results if r["success"]])
                failed = len(results) - sent
                if failed == 0:
                    st.success(f"Sent {sent} emails successfully.")
                else:
                    st.warning(f"Sent {sent}, failed {failed}.")
                    st.dataframe(pd.DataFrame([r for r in results if not r["success"]]))

    db.close()

# ============================================================
# ANALYTICS PAGE
# ============================================================
elif page == "📊 Analytics":
    st.header("Campaign Analytics")

    db = SessionLocal()
    campaigns = db.query(Campaign).all()

    if not campaigns:
        st.info("No campaigns yet. Create one on the 'Create & Send' page.")
        st.stop()

    campaign_names = {c.id: c.name for c in campaigns}
    selected_id = st.selectbox("Select campaign", options=list(campaign_names.keys()), format_func=lambda x: campaign_names[x])

    sends = db.query(Send).filter(Send.campaign_id == selected_id).all()
    total = len(sends)

    if total == 0:
        st.warning("No sends recorded for this campaign yet.")
        st.stop()

    opened_count = db.query(Send).join(Open).filter(Send.campaign_id == selected_id).distinct().count()
    replied_count = db.query(Send).join(Reply).filter(Send.campaign_id == selected_id).distinct().count()
    bounced_count = sum(1 for s in sends if s.status == "failed")
    clicked_count = db.query(Send).join(Click).filter(Send.campaign_id == selected_id).distinct().count()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Sent", total)
    col2.metric("Open Rate", f"{opened_count/total*100:.1f}%")
    col3.metric("Reply Rate", f"{replied_count/total*100:.1f}%")
    col4.metric("Click Rate", f"{clicked_count/total*100:.1f}%")
    col5.metric("Bounce Rate", f"{bounced_count/total*100:.1f}%")

    st.subheader("Funnel: Sent → Opened → Replied")
    funnel_df = pd.DataFrame({
        "Stage": ["Sent", "Opened", "Replied"],
        "Count": [total, opened_count, replied_count],
    })
    st.bar_chart(funnel_df.set_index("Stage"))

    st.subheader("Reply Sentiment Breakdown")
    sentiments = db.query(Reply.sentiment, func.count(Reply.id)).join(Send).filter(
        Send.campaign_id == selected_id
    ).group_by(Reply.sentiment).all()
    if sentiments:
        sent_df = pd.DataFrame(sentiments, columns=["Sentiment", "Count"]).set_index("Sentiment")
        st.bar_chart(sent_df)
    else:
        st.write("No replies yet.")

    st.subheader("High-engagement, no-reply contacts (flag for manual follow-up)")
    flagged_rows = []
    for send in sends:
        has_reply = db.query(Reply).filter(Reply.send_id == send.id).first()
        open_record = db.query(Open).filter(Open.send_id == send.id).first()
        if open_record and open_record.open_count >= 3 and not has_reply:
            flagged_rows.append({"Email": send.recipient.email, "Opens": open_record.open_count})
    if flagged_rows:
        st.dataframe(pd.DataFrame(flagged_rows))
    else:
        st.write("None currently.")

    st.subheader("Per-recipient timeline")
    timeline_rows = []
    for send in sends:
        open_record = db.query(Open).filter(Open.send_id == send.id).first()
        reply_record = db.query(Reply).filter(Reply.send_id == send.id).first()
        timeline_rows.append({
            "Email": send.recipient.email,
            "Sent At": send.sent_at,
            "Status": send.status,
            "Opened At": open_record.opened_at if open_record else None,
            "Open Count": open_record.open_count if open_record else 0,
            "Replied At": reply_record.replied_at if reply_record else None,
            "Sentiment": reply_record.sentiment if reply_record else None,
        })
    st.dataframe(pd.DataFrame(timeline_rows), use_container_width=True)

    csv_bytes = pd.DataFrame(timeline_rows).to_csv(index=False).encode("utf-8")
    st.download_button("Export as CSV", csv_bytes, "mailpulse_report.csv", "text/csv")

    db.close()
