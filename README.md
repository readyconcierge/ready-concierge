# Ready Concierge

AI-powered email copilot and signal layer for luxury hotel concierge teams. Staff forward guest emails, get a polished draft reply in seconds, and send it with one click. No new software to learn — it lives inside your existing email.

## What It Does

**Draft Copilot** — A guest emails the concierge. Staff forwards it to Ready Concierge. Within seconds, staff receives an AI-drafted reply calibrated to Forbes Five-Star standards: warm, specific, anticipatory. One-click mailto button opens their email client with the reply pre-composed. Review, personalize, send.

**Guest Memory** — Returning guests are recognized automatically. The AI references their prior stays, preferences, and past requests to make every reply feel personal.

**Task Tracker** — Every commitment in a draft reply ("I'll book your tee time for 10 AM Friday") is automatically extracted as a task. Email `list@` to get your task list. Reply `done all` to mark them complete.

**Signal Layer** — Daily briefings detect patterns across all guest emails: volume spikes, celebration clusters, complaint trends, VIP arrivals. Sent to the team automatically — no dashboard required.

**Weekly GM Digest** — Every Monday, the GM and team receive a beautifully formatted intelligence brief: email volume, intent breakdown, AI draft acceptance rate, average reply time, task completion stats, top guests, and AI-generated executive insights.

**One-Click Feedback** — Every draft email includes "This was perfect" and "This needed changes" buttons. Staff click once — no login required — and the system learns over time.

---

## Architecture

```
Company → Property → Stream → (Emails, Drafts, Tasks, Knowledge, Signals)
```

- **Company**: Top-level tenant (a hotel brand)
- **Property**: A physical location (Park Hyatt Aviara)
- **Stream**: An operational department (Concierge, Spa, Restaurant Events)

Each stream has its own inbox, knowledge base, task list, and signal schedule.

**Tech stack**: FastAPI + SQLAlchemy (Postgres in production, SQLite for dev) + Anthropic Claude API + SendGrid (inbound webhook + outbound email) + APScheduler + Next.js dashboard on Vercel.

**Model routing**: Complaints and VIP requests route to Claude Sonnet for nuanced drafting. Standard requests use Claude Haiku for speed and cost efficiency.

---

## Deploy to Railway (Production)

### 1. Create a Railway project

```bash
# Install Railway CLI if needed
npm install -g @railway/cli

# Login and init
railway login
railway init
```

### 2. Add a Postgres database

In the Railway dashboard, add a **PostgreSQL** plugin to your project. Railway will set `DATABASE_URL` automatically.

### 3. Set environment variables

In the Railway dashboard → Variables, add:

| Variable | Example | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Your Anthropic API key |
| `SENDGRID_API_KEY` | `SG.xxx` | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | `concierge@aviara.preshift.app` | Inbound + outbound email address |
| `DEFAULT_STAFF_EMAIL` | `concierge@parkhyattaviara.com` | Where draft replies are sent |
| `DEFAULT_SIGNAL_RECIPIENTS` | `concierge@parkhyattaviara.com,gm@parkhyattaviara.com` | Comma-separated list |
| `DEFAULT_COMPANY_NAME` | `Park Hyatt` | Company display name |
| `DEFAULT_PROPERTY_NAME` | `Park Hyatt Aviara` | Property display name |

### 4. Deploy

```bash
railway up
```

Railway uses the included `railway.toml` and `Procfile`. The health check endpoint is `/health`.

On first deploy, the system will:
- Run database migrations automatically
- Create the default Company → Property → Stream
- Auto-seed the Park Hyatt Aviara knowledge base (dining, spa, golf, transportation, etc.)

### 5. Set up SendGrid Inbound Parse

1. Go to **SendGrid** → **Settings** → **Inbound Parse**
2. Add your domain (e.g. `aviara.preshift.app`)
3. Set the destination URL to: `https://your-railway-url.up.railway.app/webhook/inbound`
4. Check **POST the raw, full MIME message**

Then add the MX record for your domain:

```
aviara.preshift.app  MX  mx.sendgrid.net  (priority 10)
```

### 6. Verify it works

```bash
# Health check
curl https://your-railway-url.up.railway.app/health

# Test the webhook (simulate a forwarded guest email)
curl -X POST https://your-railway-url.up.railway.app/webhook/inbound \
  -F "from=Concierge Staff <concierge@parkhyattaviara.com>" \
  -F "to=concierge@aviara.preshift.app" \
  -F "subject=Fwd: Dinner reservation for our anniversary" \
  -F "text=---------- Forwarded message ----------
From: Sarah Chen <sarah.chen@example.com>
Subject: Dinner reservation for our anniversary

Hi, my husband and I are celebrating our 10th anniversary this Saturday. We'd love a table for two at Argyle Steakhouse — ideally with an ocean view. Can you help? Thanks, Sarah" \
  -F "Message-Id=<test-$(date +%s)@sendgrid.example.com>"
```

---

## Local Development

```bash
cd ready-concierge
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create .env with your credentials (see env vars above)
# DATABASE_URL defaults to sqlite:///./ready_concierge.db

uvicorn main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/inbound` | SendGrid inbound email webhook |
| `GET` | `/health` | Health check |
| `GET` | `/api/properties` | List all properties with streams and stats |
| `GET` | `/api/streams/{property_id}` | List streams for a property |
| `POST` | `/api/streams` | Create a new stream (department) |
| `GET` | `/api/emails/{stream_id}` | Email history for a stream |
| `GET` | `/api/tasks/{stream_id}` | Tasks for a stream |
| `PATCH` | `/api/tasks/{task_id}` | Mark task complete/incomplete |
| `GET` | `/api/review/{stream_id}` | Review queue (held drafts) |
| `POST` | `/api/review/{draft_id}/approve` | Approve and send a held draft |
| `POST` | `/api/review/{draft_id}/reject` | Reject a held draft |
| `POST` | `/api/emails/{email_id}/draft` | Generate on-demand draft |
| `POST` | `/api/knowledge/{stream_id}/upload` | Upload knowledge document |
| `GET` | `/api/knowledge/{stream_id}` | List knowledge documents |
| `DELETE` | `/api/knowledge/{stream_id}/{doc_id}` | Delete knowledge document |
| `POST` | `/api/knowledge/{stream_id}/search` | Test knowledge retrieval |
| `POST` | `/signal/trigger` | Manually trigger signal for a stream |
| `POST` | `/api/gm-digest/trigger` | Manually trigger weekly GM digest |
| `GET` | `/api/feedback/{token}/{verdict}` | One-click draft feedback |

Interactive docs: `https://your-url/docs`

---

## Staff Training

Print the one-pager: **`Ready_Concierge_Staff_Guide.pdf`** (included in this repo).

The entire workflow for staff:
1. Forward a guest email to `concierge@aviara.preshift.app`
2. Get a draft reply in ~3 seconds
3. Click "Reply to Guest" to send with one click
4. Click "This was perfect" or "This needed changes" to give feedback

No new apps. No new logins. It lives inside their existing email.

---

## Dashboard

The Next.js dashboard is in `/dashboard` and deployed on Vercel at `ready-concierge-dashboard.vercel.app`.

Pages: Review Queue, Emails, Tasks, Knowledge Base, Settings.

Set the `NEXT_PUBLIC_API_URL` environment variable in Vercel to point to your Railway backend URL.
