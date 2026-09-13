# MailPulse

Self-hosted AI-powered mail outreach & analytics agent — a free alternative to
Mailchimp/Apollo.io/Outreach.io for personalized bulk email campaigns with
open/reply/click tracking, an agentic follow-up layer (LangGraph), and a
Streamlit analytics dashboard.

## 1. Setup (Windows / PowerShell)

```powershell
cd "C:\Users\bilal\Desktop\Langchain models"
git clone <your-repo-or-just-unzip-this-folder> mailpulse
cd mailpulse

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

copy .env.example .env
# now edit .env: fill SMTP_USER, SMTP_PASSWORD (Gmail App Password), GROQ_API_KEY, DATABASE_URL
```

### PostgreSQL (required — this project uses Postgres, not SQLite)
You need a running Postgres instance. Easiest local option, with Docker installed:
```powershell
docker run --name mailpulse-db -e POSTGRES_USER=mailpulse -e POSTGRES_PASSWORD=mailpulse -e POSTGRES_DB=mailpulse -p 5432:5432 -d postgres:16
```
This matches the default `DATABASE_URL` in `.env.example`. No Docker? Install
PostgreSQL directly (postgresql.org/download) and create a `mailpulse` DB/user,
or use a free hosted instance (Neon, Supabase, Railway all have free tiers) and
paste their connection string into `DATABASE_URL` instead.

### Gmail App Password
1. Enable 2-Step Verification on your Google account.
2. Go to https://myaccount.google.com/apppasswords
3. Generate a password for "Mail" and paste it into `.env` as `SMTP_PASSWORD`.

### Public URL for tracking (local testing)
Tracking pixel/click links need a URL Gmail can actually reach when the
recipient opens the email. For local dev, use ngrok:
```powershell
ngrok http 8000
```
Copy the `https://xxxx.ngrok.io` URL into `.env` as `PUBLIC_BASE_URL`.
(For production, deploy the FastAPI app somewhere with a real domain instead.)

## 2. Run the backend

```powershell
uvicorn app.main:app --reload --port 8000
```
Interactive API docs: http://localhost:8000/docs

## 3. Run the dashboard (separate terminal)

```powershell
.venv\Scripts\activate
streamlit run dashboard/app.py
```

## 4. Typical flow (everything below can be done from the dashboard — no API docs needed)

1. **Recipients page** — upload a CSV (`data/recipients_sample.csv` as a starting template) or add people one at a time.
2. **Create & Send page** — write a subject/body using `{name}`, `{company}`, `{role}` placeholders (and an optional follow-up template + `follow_up_after_days`), then hit **Send Now**. This rate-limits sends to protect deliverability.
3. **Opens/clicks** are tracked automatically via the pixel and rewritten links — nothing to do here.
4. **Replies** — run `python -m app.poller` periodically (cron / Windows Task Scheduler every 15 min) to poll IMAP, match replies to sends, and tag sentiment via Groq.
5. **Follow-ups** — run `python -c "from app.agent import run_follow_up_check_for_all_pending; run_follow_up_check_for_all_pending()"` on a daily schedule. The LangGraph agent checks each original send and decides: send follow-up / stop (already replied) / escalate (opened 3+ times, no reply) / wait.
6. **Analytics page** — open/reply/click/bounce rates, funnel, sentiment breakdown, flagged high-engagement contacts, and a CSV export.

The FastAPI backend (`/docs`) still exists underneath and is what the dashboard
and tracking pixel/links actually call — but day-to-day use only needs the
dashboard.

## 5. Notes / limitations of this scaffold

- SMTP+IMAP via a Gmail App Password is used instead of the full Gmail API/OAuth for simplicity — swap in the Gmail API later if you outgrow this.
- Deliverability: warm up gradually, don't blast 1,000 emails on day one, and only mail people who actually opted in (per CAN-SPAM/GDPR).
- PostgreSQL is the default DB (see setup above for a local Docker one-liner, or use a free hosted Postgres for zero local install).
- The follow-up and reply-polling jobs are meant to run on a schedule (cron/Task Scheduler), not inside a single always-on process — keep that in mind when deploying.

## 6. Future ideas (from the original spec)
- Semantic search over past replies (ChromaDB)
- Multi-channel follow-up (LinkedIn + email)
- Predictive reply-likelihood scoring
