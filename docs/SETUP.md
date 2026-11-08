# Setup — New coder runbook

## 0. Prerequisites
- Windows / macOS / Linux, Node 22, Python 3.12, Docker 24+

## 1. Clone / open
```powershell
cd D:\proofos
cp .env.example .env
```

## 2. Start
```powershell
docker compose -f infra/docker-compose.yml up --build
```
- API docs: http://localhost:8000/docs
- Web: http://localhost:5173
- Postgres: `psql "postgresql://proofos:proofos@localhost:5432/proofos"`

This command starts the local development stack. Production deployments must use
both `infra/docker-compose.yml` and `infra/docker-compose.production.yml`; see
`docs/PRODUCTION.md` for secret generation, HTTPS, bootstrap, and proxy setup.

## 3. Create tables (dev)
```powershell
cd D:\proofos\services\api
python -m pip install -r requirements.txt
python -c "from app.core.db import Base, engine; from app.models.models import *; Base.metadata.create_all(engine)"
uvicorn app.main:app --reload --port 8000
```

## 4. Frontend
```powershell
cd D:\proofos\apps\web
npm install
npm run dev
```

## 5. Agent
```powershell
cd D:\proofos\apps\agent
python agent.py --api http://localhost:8000
```

## 6. How to add a feature
1. Model in `services/api/app/models/`
2. Schema in `services/api/app/schemas/`
3. Router in `services/api/app/api/` + register in `main.py`
4. **Emit proof** via `app.core.proof.emit()` — never return 200 without it
5. UI in `apps/web/src/` (Tailwind, user-friendly, no console errors)
6. Docs: update `ARCHITECTURE.md` + `ROADMAP.md`, journal entry

## 7. How to verify proof
`GET /v1/proof/verify/{id}` must return `verified: true` with all checks green.
