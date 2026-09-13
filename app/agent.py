"""
LangGraph agentic decision layer.

For each original send that's old enough, decide one of:
  - "follow_up": no open/reply yet, and days since sent >= follow_up_after_days
  - "stop": recipient already replied
  - "escalate": opened 3+ times but never replied (high engagement, flag for a human)
  - "wait": not enough time has passed yet

This runs as a scheduled job (see scheduler.py) rather than inside the API
request path, since decisions should be made periodically, not on-demand.
"""
from datetime import datetime, timedelta
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END

from app.database import SessionLocal
from app.models import Send, Campaign, Open, Reply
from app.sender import send_single_email, build_tracking_pixel, rewrite_links_for_tracking, new_tracking_token, render_template


class RecipientState(TypedDict):
    send_id: int
    decision: str
    detail: str


def check_status(state: RecipientState) -> RecipientState:
    db = SessionLocal()
    try:
        send = db.query(Send).get(state["send_id"])
        campaign = db.query(Campaign).get(send.campaign_id)
        reply = db.query(Reply).filter(Reply.send_id == send.id).first()
        opens = db.query(Open).filter(Open.send_id == send.id).first()

        if reply:
            state["decision"] = "stop"
            state["detail"] = "recipient replied"
            return state

        days_since_sent = (datetime.utcnow() - send.sent_at).days
        follow_ups_sent = db.query(Send).filter(
            Send.recipient_id == send.recipient_id,
            Send.campaign_id == send.campaign_id,
            Send.is_follow_up > 0,
        ).count()

        if opens and opens.open_count >= 3 and follow_ups_sent >= campaign.max_follow_ups:
            state["decision"] = "escalate"
            state["detail"] = f"opened {opens.open_count}x, no reply, follow-ups exhausted"
            return state

        if days_since_sent >= campaign.follow_up_after_days and follow_ups_sent < campaign.max_follow_ups:
            state["decision"] = "follow_up"
            state["detail"] = f"{days_since_sent} days since last send, sending follow-up #{follow_ups_sent + 1}"
            return state

        state["decision"] = "wait"
        state["detail"] = "not due yet"
        return state
    finally:
        db.close()


def act_on_decision(state: RecipientState) -> RecipientState:
    if state["decision"] != "follow_up":
        return state

    db = SessionLocal()
    try:
        send = db.query(Send).get(state["send_id"])
        campaign = db.query(Campaign).get(send.campaign_id)
        recipient = send.recipient

        if not campaign.follow_up_subject_template or not campaign.follow_up_body_template:
            state["detail"] += " (skipped: no follow-up template set on campaign)"
            return state

        merge_fields = {
            "name": recipient.name,
            "company": recipient.company,
            "role": recipient.role,
        }
        subject = render_template(campaign.follow_up_subject_template, merge_fields)
        body = render_template(campaign.follow_up_body_template, merge_fields)

        token = new_tracking_token()
        body = body + build_tracking_pixel(token)
        body = rewrite_links_for_tracking(body, token)

        success, error = send_single_email(recipient.email, subject, body)

        follow_up_count = db.query(Send).filter(
            Send.recipient_id == recipient.id,
            Send.campaign_id == campaign.id,
            Send.is_follow_up > 0,
        ).count()

        new_send = Send(
            recipient_id=recipient.id,
            campaign_id=campaign.id,
            status="sent" if success else "failed",
            is_follow_up=follow_up_count + 1,
            tracking_token=token,
        )
        db.add(new_send)
        db.commit()

        state["detail"] += f" -> {'sent' if success else f'FAILED: {error}'}"
        return state
    finally:
        db.close()


def build_graph():
    graph = StateGraph(RecipientState)
    graph.add_node("check_status", check_status)
    graph.add_node("act", act_on_decision)
    graph.set_entry_point("check_status")
    graph.add_edge("check_status", "act")
    graph.add_edge("act", END)
    return graph.compile()


follow_up_graph = build_graph()


def run_follow_up_check_for_all_pending():
    """Call this from a scheduler (cron/APScheduler) e.g. once a day."""
    db = SessionLocal()
    try:
        candidate_sends = db.query(Send).filter(Send.is_follow_up == 0).all()
    finally:
        db.close()

    results = []
    for send in candidate_sends:
        result = follow_up_graph.invoke({"send_id": send.id, "decision": "", "detail": ""})
        results.append(result)
    return results
