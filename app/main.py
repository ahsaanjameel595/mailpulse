import csv
import io
import json
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db, init_db
from app.models import Recipient, Campaign, Send, Open, Click, Reply
from app.schemas import RecipientIn, CampaignIn, CampaignOut, SendCampaignRequest
from app.sender import render_template, new_tracking_token, send_single_email, build_tracking_pixel, rewrite_links_for_tracking
from app.services import send_campaign_now
from app.tracking import router as tracking_router

app = FastAPI(title="MailPulse", description="Self-hosted AI-powered mail outreach & analytics agent")
app.include_router(tracking_router)


@app.on_event("startup")
def on_startup():
    init_db()


# ---------- Recipients ----------

@app.post("/recipients")
def add_recipient(recipient: RecipientIn, db: Session = Depends(get_db)):
    existing = db.query(Recipient).filter(Recipient.email == recipient.email).first()
    if existing:
        raise HTTPException(400, "Recipient with this email already exists")
    db_recipient = Recipient(
        name=recipient.name,
        email=recipient.email,
        company=recipient.company,
        role=recipient.role,
        custom_fields=json.dumps(recipient.custom_fields or {}),
    )
    db.add(db_recipient)
    db.commit()
    db.refresh(db_recipient)
    return {"id": db_recipient.id}


@app.post("/recipients/upload_csv")
async def upload_recipients_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """CSV columns expected: name, email, company, role (extra columns become custom_fields)."""
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    added, skipped = 0, 0
    known_fields = {"name", "email", "company", "role"}
    for row in reader:
        if not row.get("email"):
            continue
        if db.query(Recipient).filter(Recipient.email == row["email"]).first():
            skipped += 1
            continue
        custom = {k: v for k, v in row.items() if k not in known_fields}
        db.add(Recipient(
            name=row.get("name", ""),
            email=row["email"],
            company=row.get("company"),
            role=row.get("role"),
            custom_fields=json.dumps(custom),
        ))
        added += 1
    db.commit()
    return {"added": added, "skipped_existing": skipped}


@app.get("/recipients")
def list_recipients(db: Session = Depends(get_db)):
    return db.query(Recipient).all()


# ---------- Campaigns ----------

@app.post("/campaigns", response_model=CampaignOut)
def create_campaign(campaign: CampaignIn, db: Session = Depends(get_db)):
    db_campaign = Campaign(**campaign.model_dump())
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign


@app.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(Campaign).all()


# ---------- Sending ----------

@app.post("/campaigns/send")
def send_campaign(req: SendCampaignRequest, db: Session = Depends(get_db)):
    try:
        results = send_campaign_now(db, req.campaign_id, req.recipient_ids)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"sent": len([r for r in results if r["success"]]), "failed": len([r for r in results if not r["success"]]), "details": results}


# ---------- Replies (manual log, or call from your IMAP poller — see poller.py) ----------

@app.post("/replies")
def log_reply(send_id: int, body: str = "", sentiment: str = None, db: Session = Depends(get_db)):
    send = db.query(Send).get(send_id)
    if not send:
        raise HTTPException(404, "Send not found")
    db.add(Reply(send_id=send_id, body=body, sentiment=sentiment))
    db.commit()
    return {"logged": True}


# ---------- Analytics ----------

@app.get("/analytics/{campaign_id}")
def campaign_analytics(campaign_id: int, db: Session = Depends(get_db)):
    sends = db.query(Send).filter(Send.campaign_id == campaign_id).all()
    total = len(sends)
    if total == 0:
        return {"total_sent": 0}

    opened = db.query(Send).join(Open).filter(Send.campaign_id == campaign_id).distinct().count()
    replied = db.query(Send).join(Reply).filter(Send.campaign_id == campaign_id).distinct().count()
    clicked = db.query(Send).join(Click).filter(Send.campaign_id == campaign_id).distinct().count()
    bounced = sum(1 for s in sends if s.status == "failed")

    sentiments = db.query(Reply.sentiment, func.count(Reply.id)).join(Send).filter(
        Send.campaign_id == campaign_id
    ).group_by(Reply.sentiment).all()

    return {
        "total_sent": total,
        "open_rate": round(opened / total * 100, 1),
        "reply_rate": round(replied / total * 100, 1),
        "click_rate": round(clicked / total * 100, 1),
        "bounce_rate": round(bounced / total * 100, 1),
        "sentiment_breakdown": {s or "unclassified": c for s, c in sentiments},
    }


@app.get("/analytics/{campaign_id}/high_engagement_no_reply")
def high_engagement_no_reply(campaign_id: int, db: Session = Depends(get_db)):
    """Recipients who opened 3+ times but never replied — flagged for manual follow-up."""
    sends = db.query(Send).filter(Send.campaign_id == campaign_id).all()
    flagged = []
    for send in sends:
        has_reply = db.query(Reply).filter(Reply.send_id == send.id).first()
        open_record = db.query(Open).filter(Open.send_id == send.id).first()
        if open_record and open_record.open_count >= 3 and not has_reply:
            flagged.append({"recipient_email": send.recipient.email, "opens": open_record.open_count})
    return flagged
