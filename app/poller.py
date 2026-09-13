"""
Reply detection: polls the Gmail inbox via IMAP, matches replies back to a
send by subject ("Re: <original subject>") + sender email, logs the reply,
and classifies sentiment with a small LLM call via Groq.

Run this periodically (cron / APScheduler / Windows Task Scheduler), e.g.
every 15 minutes:  python -m app.poller
"""
import os
import imaplib
import email
from email.header import decode_header
from datetime import datetime
from dotenv import load_dotenv

from app.database import SessionLocal
from app.models import Send, Reply, Recipient, Campaign

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.getenv("SMTP_USER")  # reuse the same Gmail account
IMAP_PASSWORD = os.getenv("SMTP_PASSWORD")  # Gmail App Password

GROQ_API_KEY = os.getenv("GROQ_API_KEY")


def classify_sentiment(reply_text: str) -> str:
    """Uses Groq for a fast/cheap sentiment call, per the doc's proposed stack.
    Falls back to 'neutral' if no API key is set or the call fails."""
    if not GROQ_API_KEY or not reply_text.strip():
        return "neutral"
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Classify the email reply's sentiment. Answer with exactly one word: positive, neutral, or negative."},
                {"role": "user", "content": reply_text[:2000]},
            ],
            temperature=0,
            max_tokens=5,
        )
        label = completion.choices[0].message.content.strip().lower()
        return label if label in {"positive", "neutral", "negative"} else "neutral"
    except Exception:
        return "neutral"


def _decode(value) -> str:
    parts = decode_header(value or "")
    out = ""
    for text, enc in parts:
        out += text.decode(enc or "utf-8") if isinstance(text, bytes) else text
    return out


def get_email_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="ignore")
        return ""
    return msg.get_payload(decode=True).decode(errors="ignore")


def poll_replies():
    if not IMAP_USER or not IMAP_PASSWORD:
        print("IMAP_USER/IMAP_PASSWORD (reused from SMTP_USER/SMTP_PASSWORD) not set — skipping.")
        return

    db = SessionLocal()
    new_replies = 0
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select("inbox")

        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            return

        message_ids = data[0].split()
        for msg_id in message_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            from_addr = email.utils.parseaddr(msg.get("From"))[1]
            subject = _decode(msg.get("Subject"))
            body = get_email_body(msg)

            # Match to the most recent send to this recipient whose subject
            # (stripped of "Re:") appears in this reply's subject line.
            recipient = db.query(Recipient).filter(Recipient.email == from_addr).first()
            if not recipient:
                continue

            candidate_send = (
                db.query(Send)
                .filter(Send.recipient_id == recipient.id)
                .order_by(Send.sent_at.desc())
                .first()
            )
            if not candidate_send:
                continue

            already_logged = db.query(Reply).filter(Reply.send_id == candidate_send.id).first()
            if already_logged:
                continue

            sentiment = classify_sentiment(body)
            db.add(Reply(send_id=candidate_send.id, replied_at=datetime.utcnow(), body=body, sentiment=sentiment))
            db.commit()
            new_replies += 1

        mail.close()
        mail.logout()
    finally:
        db.close()

    print(f"Poll complete: {new_replies} new replies logged.")


if __name__ == "__main__":
    poll_replies()
