# AI Patient Intake Platform

Conversational AI that guides patients through registration, insurance verification, department routing, and appointment booking — in one chat conversation.

**Built on:** Claude Haiku · HAPI FHIR · FastAPI · Next.js · PostgreSQL · Stripe
**Compliance:** HIPAA-compliant infrastructure · NIST IAL2 identity · Audit logging

---

## What it does

A patient opens the app and has a natural conversation with an AI front-desk receptionist. By the end they have a confirmed appointment, verified insurance, a payment receipt, and their record saved to the EHR. The full returning patient journey takes under 90 seconds.

**Returning patient flow:**
1. Identifies as returning → gives name + date of birth
2. AI looks up their record → verifies city and state
3. Confirms phone (last 4 only) and masked email on file
4. Insurance verified → copay shown before booking
5. Picks department → describes reason for visit
6. AI checks for emergencies → asks follow-up if symptoms are vague
7. Picks appointment slot
8. Booked → pays copay (or defers to clinic)
9. Signs HIPAA consent with e-signature
10. Confirmation card + email receipt sent

**New patient flow:** Same but collects all details fresh and creates a new record in HAPI FHIR.

**Minor patient flow:** If patient is under 18, AI asks for guardian name and relationship before continuing.

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop (must be running)
- An [Anthropic API key](https://console.anthropic.com)
- A [Stripe account](https://dashboard.stripe.com) (test mode is fine)
- The [Stripe CLI](https://docs.stripe.com/stripe-cli) (for local webhook testing)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) for email receipts
- A GitHub account with SSH access configured (`~/.ssh/id_ed25519`) if you plan to push changes

---

## First-time setup

### 1. Clone and enter the project

```bash
git clone git@github.com:AmalAHassan/patient_intake.git
cd patient_intake/patient-intake
```

### 2. Copy and fill in environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in these required values:

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://admin:secret@localhost:5432/patientintake
REDIS_URL=redis://localhost:6379
FHIR_BASE_URL=http://localhost:8080/fhir

STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

GMAIL_USER=your@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
DEV_NOTIFY_EMAIL=your@gmail.com
```

> `STRIPE_WEBHOOK_SECRET` is generated when you run `stripe listen` (see Terminal 4 below) — copy it in after your first run.

### 3. Set up the Python backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

### 4. Create the database tables

```bash
cd backend
source .venv/bin/activate
python3 -c "from models import Base, engine; Base.metadata.create_all(bind=engine); print('Tables created')"
cd ..
```

### 5. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 6. Install and set up the Stripe CLI

The Stripe CLI lets you forward live webhook events to your local backend so payment confirmations work in development.

**macOS (Homebrew):**
```bash
brew install stripe/stripe-cli/stripe
```

**Windows (Scoop):**
```bash
scoop bucket add stripe https://github.com/stripe/scoop-bucket.git
scoop install stripe
```

**Linux:** download the latest binary from the [Stripe CLI releases page](https://github.com/stripe/stripe-cli/releases) and add it to your `PATH`.

Then authenticate once:

```bash
stripe login
```

This opens a browser window to link the CLI to your Stripe account. You only need to do this once per machine.

---

## Running the app

You need **four terminals** open at the same time.

**Terminal 1 — start the databases:**

```bash
cd patient-intake
docker-compose up -d
```

Starts PostgreSQL, Redis, and HAPI FHIR in the background. Wait about 20 seconds for HAPI FHIR to finish starting, then verify:

```bash
curl http://localhost:8080/fhir/metadata | head -5
```

**Terminal 2 — start the backend:**

```bash
cd patient-intake
source backend/.venv/bin/activate
cd backend
uvicorn main:app --reload --port 8000
```

Starts 3 MCP servers (ports 5001–5003), the crisis notifier (port 8001), and FastAPI (port 8000).

**Terminal 3 — start the frontend:**

```bash
cd patient-intake/frontend
npm run dev
```

Open **http://localhost:3000** in your browser.

**Terminal 4 — forward Stripe webhooks:**

```bash
stripe listen --forward-to localhost:8000/payment/webhook
```

This prints a webhook signing secret (`whsec_...`) the first time you run it — copy that value into `STRIPE_WEBHOOK_SECRET` in your `.env` and restart the backend (Terminal 2) so it picks up the change. Leave this terminal running any time you're testing a payment; without it, Stripe events (like `payment_intent.succeeded`) never reach your local backend.

To fire a one-off test event without going through the UI:

```bash
stripe trigger payment_intent.succeeded
```

---

## Stopping everything

```bash
# Stop frontend        — Ctrl+C in Terminal 3
# Stop backend         — Ctrl+C in Terminal 2
# Stop Stripe listener — Ctrl+C in Terminal 4

# Stop databases
docker-compose down
```

---

## Ports

| Service | Port | What it is |
|---------|------|------------|
| Frontend (Next.js) | 3000 | Patient chat UI |
| Backend (FastAPI) | 8000 | API + conversation loop |
| PostgreSQL | 5432 | Sessions + patient records |
| Redis | 6379 | Conversation history |
| HAPI FHIR | 8080 | EHR patient records |
| patient-lookup MCP | 5001 | Looks up patients from CSV |
| eligibility MCP | 5002 | Insurance check (mock) |
| hapi-fhir MCP | 5003 | Writes patient records to FHIR |
| Crisis notifier | 8001 | Emergency alert dashboard |

---

## Project structure

```
patient-intake/
├── .env                        # your config — never commit this
├── .env.example                # safe template to copy from
├── docker-compose.yml          # PostgreSQL + Redis + HAPI FHIR
├── Makefile                    # dev shortcuts
├── start_mcp_servers.py        # launches all MCP servers
├── crisis_notifier.py          # mock crisis alert server (port 8001)
├── test_evals.py               # LLM evaluation suite (10 tests)
├── AGENT_GUIDELINES.md         # clinical behavior rules for the AI
├── README.md
│
├── frontend/
│   └── pages/
│       ├── index.tsx           # main chat UI
│       └── portal.tsx          # patient portal — view statements + pay
│
└── backend/
    ├── main.py                 # FastAPI entry point
    ├── config.py                # reads .env
    ├── models.py                # PostgreSQL models (Patient, IntakeSession)
    ├── requirements.txt         # Python dependencies
    ├── routes/
    │   ├── intake.py             # /intake/start, /intake/message
    │   └── payment.py            # /payment/create-intent, /payment/confirm, /payment/webhook, /portal/lookup
    ├── services/
    │   ├── claude.py              # conversation loop + tool execution + system prompt
    │   ├── mcp_client.py          # routes tool calls to local MCP servers
    │   ├── fhir_client.py         # writes to HAPI FHIR
    │   ├── sms.py                 # email confirmations + payment receipts (Gmail SMTP)
    │   └── patient_lookup.py      # looks up patients from CSV
    ├── mcp_servers/
    │   ├── patient_lookup/        # looks up patient records
    │   ├── eligibility/           # insurance eligibility check
    │   └── hapi_fhir/             # FHIR read/write
    └── data/
        └── patients_enriched.csv  # synthetic patient data for testing
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | Your Anthropic API key |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `REDIS_URL` | ✅ | Redis connection string |
| `FHIR_BASE_URL` | ✅ | HAPI FHIR URL (default: localhost:8080/fhir) |
| `STRIPE_SECRET_KEY` | ✅ | Stripe secret key (test or live) |
| `STRIPE_PUBLISHABLE_KEY` | ✅ | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | ✅ | Printed by `stripe listen` — see Terminal 4 |
| `GMAIL_USER` | ✅ | Gmail address for sending confirmations |
| `GMAIL_APP_PASSWORD` | ✅ | Gmail app password (not your real password) |
| `DEV_NOTIFY_EMAIL` | ✅ | Where to send receipts in dev |
| `MCP_PATIENT_LOOKUP_URL` | | MCP server URL (default: localhost:5001/sse) |
| `MCP_ELIGIBILITY_URL` | | MCP server URL (default: localhost:5002/sse) |
| `MCP_EHR_URL` | | MCP server URL (default: localhost:5003/sse) |
| `CRISIS_NOTIFIER_URL` | | Crisis alert server (default: localhost:8001) |

---

## Test card for payments

Stripe test mode accepts these card details:

```
Card number:  4242 4242 4242 4242
Expiry:       12/34
CVC:          123
ZIP:          10001
```

This always succeeds. No real money is charged. With Terminal 4's `stripe listen` running, the resulting webhook event will reach your backend and trigger the receipt email automatically.

---

## Patient portal

Go to **http://localhost:3000/portal**

Enter your name and date of birth to view your appointments, see payment status, and pay any outstanding copays.

---

## Running the eval suite

The eval suite runs 10 scripted conversations against your live backend and checks that Claude is following instructions correctly.

```bash
cd patient-intake
source backend/.venv/bin/activate
python3 test_evals.py
```

Make sure `make dev` is running before you run the evals.

**What it tests:**

| # | Test | Checks |
|---|------|--------|
| 01 | Greeting | Opens with new/returning question |
| 02 | Returning patient lookup | Name → DOB → city/state verification |
| 03 | Phone masking | Never shows full phone number |
| 04 | Email masking | Shows masked format only |
| 05 | Insurance privacy | Never shows member ID |
| 06 | Emergency detection | Chest pain → 911 redirect |
| 07 | Crisis detection | Suicidal ideation → 988 redirect |
| 08 | Minor detection | DOB under 18 → asks for guardian |
| 09 | Vague symptom | "Headache" → asks follow-up |
| 10 | Complete flow | All fields captured at completion |

The report shows pass/fail for each check and suggests exactly which line in the system prompt to fix for any failures.

---

## Viewing patient data

**Quick terminal check:**

```bash
cd patient-intake/backend
source .venv/bin/activate
python3 -c "
from models import SessionLocal, Patient
db = SessionLocal()
for p in db.query(Patient).order_by(Patient.created_at.desc()).limit(5).all():
    print(p.name, '|', p.dob, '|', p.department, '|', p.payment_status)
db.close()
"
```

**TablePlus (recommended):** Download from [tableplus.com](https://tableplus.com) and connect with:
- Host: `localhost` · Port: `5432`
- Database: `patientintake` · User: `admin` · Password: `secret`

**HAPI FHIR UI:** Open [http://localhost:8080](http://localhost:8080) → click Patient.

---

## Crisis notification

When a patient mentions suicidal thoughts or a medical emergency, the AI hard-stops and sends an alert to the crisis notifier dashboard.

View live alerts at **http://localhost:8001** while `make dev` is running.

In production: replace the mock handler in `crisis_notifier.py` with real dispatch API calls.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/intake/start` | Start a new intake session |
| POST | `/intake/message` | Send a message, get a reply |
| POST | `/payment/create-intent` | Create Stripe payment intent |
| POST | `/payment/confirm` | Confirm payment + send receipt |
| POST | `/payment/webhook` | Receives forwarded Stripe events (see Terminal 4) |
| POST | `/portal/lookup` | Look up patient appointments by name + DOB |
| GET | `/payment/publishable-key` | Get Stripe publishable key |
| GET | `/health` | Health check |
| GET | `/docs` | FastAPI auto-generated API docs |

---

## Pushing changes to GitHub

This repo is authenticated over SSH, so make sure your key is loaded before pushing:

```bash
ssh-add ~/.ssh/id_ed25519
ssh -T git@github.com   # should greet you by username if the key works
```

Always run git commands from inside the repo root (`patient_intake/`), not a parent folder — running `git add .` from an outer directory can accidentally sweep up unrelated or nested repos.

```bash
cd patient_intake

# check what changed
git status

# stage and commit
git add .
git commit -m "Describe your change here"

# push to the dev2 branch
git push origin dev2
```

If this is a brand-new branch that doesn't exist on the remote yet:

```bash
git push -u origin dev2
```

Railway is configured for git-push-to-deploy, so pushing to `dev2` will automatically trigger a redeploy of the `patient_intake` (backend) and `delightful-communication` (frontend) services on Railway — no separate deploy step needed.

---

## Common problems

**`make: pip: No such file or directory`**
Activate the venv first: `source backend/.venv/bin/activate`

**`Cannot connect to backend`**
Make sure `make dev` is running. Check [http://localhost:8000/docs](http://localhost:8000/docs) to verify FastAPI is up.

**`Patient not found`**
The lookup reads from `backend/data/patients_enriched.csv`. Make sure the file exists and has rows.

**`FHIR write failed`**
Make sure Docker is running: `docker-compose up -d`. Check [http://localhost:8080](http://localhost:8080) to verify HAPI FHIR is up. It takes ~20 seconds to start.

**`column patients.payment_date does not exist`**
The DB schema is out of date. Recreate tables:
```bash
cd backend
source .venv/bin/activate
python3 -c "from models import Base, engine; Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine); print('done')"
```
Note: this deletes existing patient records.

**`Ports already in use`**
```bash
lsof -ti:5001,5002,5003,8000,8001 | xargs kill -9 2>/dev/null; true
make dev
```

**`Payment confirm returns 400`**
Check that `payment_date` column exists in the DB. If not, recreate tables as above.

**Payments succeed in the UI but no receipt email arrives**
Make sure Terminal 4 (`stripe listen --forward-to localhost:8000/payment/webhook`) is running and that `STRIPE_WEBHOOK_SECRET` in `.env` matches the value it printed. Restart the backend after changing `.env`.

**`git push` hangs or fails with SSL/RPC errors**
Use the SSH remote (`git@github.com:AmalAHassan/patient_intake.git`), not HTTPS — HTTPS has caused SSL/RPC errors on this repo due to its size.

---

## Clinical guidelines

The AI agent follows strict clinical rules defined in `AGENT_GUIDELINES.md` at the project root. These are loaded automatically at runtime — edit that file to update agent behavior without touching code.

Key rules:
- Hard stop and redirect to **911** for medical emergencies
- Hard stop and provide **988** for mental health crises
- Never diagnose, recommend medication, or interpret results
- Never show insurance member ID to the patient
- Never show full phone number — last 4 digits only
- Always mask email addresses
- Direct patients to call the clinic when human help is needed

---

*AI Patient Intake Platform · Ledelsea · Built on Claude Haiku · HAPI FHIR · NIST IAL2*