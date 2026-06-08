# AI Patient Intake Platform

Conversational AI that guides patients through registration, insurance verification, and appointment booking.

---

## What you need installed

- Python 3.11+
- Docker Desktop
- A terminal

---

## First time setup

**1. Clone and enter the project**
```bash
cd patient-intake
```

**2. Copy the environment file**
```bash
cp .env.example .env
```
Open `.env` and add your `ANTHROPIC_API_KEY`. Everything else can stay as-is for local dev.

**3. Create and activate the virtual environment**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
cd ..
```

**4. Install dependencies**
```bash
make install
```

---

## Running the app

Every time you want to run the app, do these three steps in order.

**Step 1 — Start the databases**
```bash
docker-compose up -d
```
This starts PostgreSQL, Redis, and HAPI FHIR in the background.

**Step 2 — Activate the virtual environment**
```bash
cd patient-intake/backend
source .venv/bin/activate
cd ..
```

**Step 3 — Start everything**
```bash
make dev
```
This starts the MCP servers and the FastAPI backend together.

**Step 4 — Open the frontend**

In a new terminal:
```bash
cd patient-intake/frontend
python3 -m http.server 3000
```
Then open: **http://localhost:3000/chat.html**

---

## Stopping the app

```bash
make stop          # stops MCP servers and FastAPI
docker-compose down  # stops databases
```

---

## Ports at a glance

| Service | Port | What it is |
|---|---|---|
| Frontend | 3000 | Chat UI |
| FastAPI | 8000 | Backend API |
| PostgreSQL | 5432 | Session + patient database |
| Redis | 6379 | Conversation history |
| HAPI FHIR | 8080 | Patient records (EHR for demo) |
| patient-lookup MCP | 5001 | Looks up patients from CSV |
| eligibility MCP | 5002 | Insurance check (mock by default) |
| hapi-fhir MCP | 5003 | Writes patient records (active EHR) |
| epic MCP | 5004 | Stub — activate when access arrives |
| athena MCP | 5005 | Stub — activate when access arrives |
| cerner MCP | 5006 | Stub — activate when access arrives |

---

## Switching EHR backends

The default is HAPI FHIR (local, no approval needed). When you get Epic or Athena sandbox access, change one line in `.env`:

```bash
EHR_BACKEND=epic      # or athena, cerner
```

Then restart with `make dev`. Nothing else changes.

---

## Switching from mock to real insurance

By default the app uses mock insurance data so you can develop without an Availity account. When you're ready for real eligibility checks:

1. Add your Availity credentials to `.env`
2. Set `USE_MOCK_ELIGIBILITY=false` in `.env`
3. Restart with `make dev`

---

## Project structure

```
patient-intake/
├── .env                      # your config (never commit this)
├── .env.example              # safe template to copy from
├── docker-compose.yml        # PostgreSQL + Redis + HAPI FHIR
├── Makefile                  # dev shortcuts
├── start_mcp_servers.py      # launches all MCP servers
│
├── frontend/
│   └── chat.html             # the patient chat UI
│
└── backend/
    ├── main.py               # FastAPI entry point
    ├── claude.py             # conversation loop
    ├── config.py             # reads .env settings
    ├── models.py             # database models
    │
    ├── routes/               # API endpoints
    ├── services/             # patient lookup, FHIR client
    ├── data/                 # patients_enriched.csv (test data)
    │
    └── mcp_servers/          # one folder per integration
        ├── patient_lookup/   # reads from CSV
        ├── eligibility/      # insurance check
        ├── hapi_fhir/        # active EHR (default)
        ├── epic/             # stub
        ├── athena/           # stub
        └── cerner/           # stub
```

---

## Common problems

**`make: pip: No such file or directory`**
Use `pip3` — or make sure your venv is activated first.

**`Cannot connect to backend`**
Make sure `make dev` is running and you can see FastAPI at http://localhost:8000/docs

**`Patient not found`**
Check that `backend/data/patients_enriched.csv` exists and has rows. The lookup matches on name + date of birth.

**MCP server crashed**
`start_mcp_servers.py` auto-restarts crashed servers. Check the terminal where `make dev` is running for error output.