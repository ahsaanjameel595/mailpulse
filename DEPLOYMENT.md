# Deploying MailPulse on Your Own Server

This covers running MailPulse in production on a Linux server you control
(VPS, on-prem box, etc.) rather than the local dev setup in the main README.

## 1. PostgreSQL (this is the default DB, not optional)

`DATABASE_URL` in `.env` should already point at Postgres (see `.env.example`).
For production, use a managed Postgres (your VPS provider's managed DB, or
Neon/Supabase/Railway) rather than running Postgres yourself on the same box:

```env
DATABASE_URL=postgresql://user:password@host:5432/mailpulse
```

`psycopg2-binary` is already in `requirements.txt` for this. No code
changes needed — `app/database.py` reads `DATABASE_URL` directly.

## 2. Run the backend as a service (systemd example)

Create `/etc/systemd/system/mailpulse-api.service`:

```ini
[Unit]
Description=MailPulse API
After=network.target

[Service]
WorkingDirectory=/opt/mailpulse
EnvironmentFile=/opt/mailpulse/.env
ExecStart=/opt/mailpulse/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
User=mailpulse

[Install]
WantedBy=multi-user.target
```

Then: `sudo systemctl enable --now mailpulse-api`

## 3. Run the dashboard the same way

Create a second unit, `mailpulse-dashboard.service`, with:
```ini
ExecStart=/opt/mailpulse/.venv/bin/streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
```

## 4. Put both behind Nginx with HTTPS

Reverse-proxy `api.yourdomain.com` -> `localhost:8000` and
`dashboard.yourdomain.com` -> `localhost:8501`. Use `certbot` for free
TLS certificates. This also gives you the real public `PUBLIC_BASE_URL`
the tracking pixel/links need (no more ngrok/cloudflared — those were only
for local development).

## 5. Schedule the background jobs (cron)

These are NOT always-on processes — they run periodically:

```cron
# Poll for replies every 15 minutes
*/15 * * * * cd /opt/mailpulse && /opt/mailpulse/.venv/bin/python -m app.poller

# Run the follow-up agent once a day
0 9 * * * cd /opt/mailpulse && /opt/mailpulse/.venv/bin/python -c "from app.agent import run_follow_up_check_for_all_pending; run_follow_up_check_for_all_pending()"
```

## 6. Environment variables checklist

All of these go in `.env` on the server (copy from `.env.example`):
- `DATABASE_URL` — Postgres connection string
- `SMTP_USER` / `SMTP_PASSWORD` — sending account + Gmail App Password
- `IMAP_HOST` — for reply polling
- `PUBLIC_BASE_URL` — your real domain (e.g. `https://api.yourdomain.com`), NOT localhost
- `GROQ_API_KEY` — for reply sentiment tagging

## 7. Alternative: managed platforms (Render / Railway)

If you'd rather not manage systemd/Nginx yourself, Render.com or
Railway.app can deploy straight from a GitHub repo — push this project,
add their managed Postgres, set the same environment variables above,
and use their "Cron Job" service type for step 5 instead of crontab.
Free tiers exist but have cold-start delays; fine for low-volume use.
