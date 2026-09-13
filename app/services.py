"""
Shared business logic used by both the FastAPI backend (app/main.py) and the
Streamlit dashboard (dashboard/app.py), so "sending a campaign" is written
once and both surfaces stay in sync.
"""
from sqlalchemy.orm import Session
from app.models import Recipient, Campaign, Send
from app.sender import render_template, new_tracking_token, send_single_email, build_tracking_pixel, rewrite_links_for_tracking


def send_campaign_now(db: Session, campaign_id: int, recipient_ids: list[int] | None = None):
    campaign = db.query(Campaign).get(campaign_id)
    if not campaign:
        raise ValueError("Campaign not found")

    query = db.query(Recipient)
    if recipient_ids:
        query = query.filter(Recipient.id.in_(recipient_ids))
    recipients = query.all()

    results = []
    for recipient in recipients:
        merge_fields = {
            "name": recipient.name,
            "email": recipient.email,
            "company": recipient.company or "",
            "role": recipient.role or "",
        }
        subject = render_template(campaign.subject_template, merge_fields)
        body = render_template(campaign.body_template, merge_fields)
        token = new_tracking_token()
        body_tracked = rewrite_links_for_tracking(body + build_tracking_pixel(token), token)

        success, error = send_single_email(recipient.email, subject, body_tracked)

        db.add(Send(
            recipient_id=recipient.id,
            campaign_id=campaign.id,
            status="sent" if success else "failed",
            is_follow_up=0,
            tracking_token=token,
        ))
        db.commit()
        results.append({"recipient": recipient.email, "success": success, "error": error})

    return results
