# Patient Intake FastAPI Backend

## Local dependencies with Docker Compose

The backend relies on PostgreSQL, Redis, and HAPI FHIR. Start them from the repository root:

```bash
cd patient-intake
docker-compose up -d
```

Confirm the services are running with:

```bash
docker ps
```

The compose setup exposes:

- `postgres` on port `5432`
- `redis` on port `6379`
- `hapi` on port `8080`

### Run the backend after Docker is up

From the repo root:

```bash
cd backend
source .venv/bin/activate
python main.py
```

Or using `uvicorn`:

```bash
cd patient_intake/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Environment variables

The backend reads settings from `patient-intake/.env` by default. Make sure `DATABASE_URL`, `REDIS_URL`, and `FHIR_BASE_URL` match your Docker service ports.

## Frontend local preview

To serve the frontend from `patient-intake/frontend`:

```bash
cd patient-intake/frontend
python3 -m http.server 3000
```

Then open:

- `http://localhost:3000/chat.html`

## Notes

- The backend is defined in `patient-intake/backend/main.py`.
- Database initialization happens on startup via `models.init_db()`.
- CORS is already enabled for all origins.

If you want help wiring the frontend or testing specific endpoints, just ask.