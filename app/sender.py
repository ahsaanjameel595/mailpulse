"""
Sending service: mail-merge templating + rate-limited batch sending over SMTP
(Gmail SMTP with an app password is the simplest path for a self-hosted
prototype; swap this out for the Gmail API if you need higher volume/OAuth).

Each send gets a unique tracking_token embedded as:
  - an invisible 1x1 pixel pointing at /track/open/{token}.png
  - links rewritten to go through /track/click/{token}?url=<original>
"""
import os
import time
import uuid
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # Gmail App Password, not your normal password
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

LINK_RE = re.compile(r'href="(https?://[^"]+)"')


def render_template(template: str, recipient: dict) -> str:
    """Simple {field} mail-merge substitution."""
    merged = template
    for key, value in recipient.items():
        merged = merged.replace("{" + key + "}", str(value) if value else "")
    return merged


def rewrite_links_for_tracking(html_body: str, token: str) -> str:
    def _replace(match):
        original_url = match.group(1)
        tracked = f"{PUBLIC_BASE_URL}/track/click/{token}?url={quote(original_url)}"
        return f'href="{tracked}"'
    return LINK_RE.sub(_replace, html_body)


def build_tracking_pixel(token: str) -> str:
    return f'<img src="{PUBLIC_BASE_URL}/track/open/{token}.png" width="1" height="1" style="display:none" />'


def send_single_email(to_email: str, subject: str, html_body: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    if not SMTP_USER or not SMTP_PASSWORD:
        return False, "SMTP_USER / SMTP_PASSWORD not configured in .env"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def send_batch(jobs: list[dict], batch_size: int = 20, delay_seconds: float = 2.0):
    """
    jobs: list of {"to_email", "subject", "body", "token"}
    Yields (job, success, error) as it goes, so caller can persist results
    incrementally rather than waiting for the whole batch to finish.
    Rate-limited: sleeps `delay_seconds` between sends and pauses briefly
    every `batch_size` emails, per the doc's deliverability guidance.
    """
    for i, job in enumerate(jobs, start=1):
        body_with_tracking = job["body"] + build_tracking_pixel(job["token"])
        body_with_tracking = rewrite_links_for_tracking(body_with_tracking, job["token"])
        success, error = send_single_email(job["to_email"], job["subject"], body_with_tracking)
        yield job, success, error
        time.sleep(delay_seconds)
        if i % batch_size == 0:
            time.sleep(delay_seconds * 5)  # longer pause between batches


def new_tracking_token() -> str:
    return uuid.uuid4().hex
