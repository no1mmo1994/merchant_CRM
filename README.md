# PulseOrder

> Personal dashboard to manage multiple Grab Merchant stores from one place.

## Status

🚧 **Phase 01 — Bootstrap monorepo & tooling** (in progress)

See `plans/260728-grab-store-management-dashboard/plan.md` for the full roadmap.

## Architecture

```
┌─ PulseOrder (Next.js 15, App Router, TS, Tailwind, shadcn/ui) ─┐
│  Light + Dark theme · Framer Motion · Recharts · TanStack Query  │
└────────────────┬────────────────────────────────────────────────┘
                 │  REST/JSON
┌────────────────▼────────────────────────────────────────────────┐
│ FastAPI (Python 3.11+, httpx async, SQLModel/SQLite, Fernet)    │
│  APScheduler background jobs · cookie-based session              │
└────────────────┬────────────────────────────────────────────────┘
                 │
            api.grab.com (reverse-engineered endpoints)
```

## Tech Stack

- **Frontend**: Next.js 15 (App Router, TypeScript), Tailwind CSS, shadcn/ui, Framer Motion, Recharts, Zustand, TanStack Query, react-hook-form + zod
- **Backend**: FastAPI (Python 3.11+), httpx async, SQLModel, SQLite, Fernet, APScheduler
- **Tooling**: pnpm (Node), uv (Python), concurrently

## Prerequisites

- Node.js 20+
- pnpm 9+ (`npm install -g pnpm`)
- Python 3.11+
- uv (`pip install uv` or see https://github.com/astral-sh/uv)

## Monorepo Layout

```
grab-dashboard/
├── apps/
│   └── web/              # Next.js 15 frontend
├── services/
│   └── api/              # FastAPI backend
├── data/                 # SQLite database (gitignored)
├── docs/                 # Reference docs
├── package.json          # Root scripts (dev, build, etc.)
├── pnpm-workspace.yaml   # pnpm workspace config
└── .env.example          # Shared env template
```

## Quick Start

> **Status note**: until Phase 01 is complete, the commands below won't work yet.

```bash
# 1. Install dependencies
pnpm install
cd services/api && uv sync && cd ../..

# 2. Configure environment
cp .env.example .env
# Edit .env: generate a Fernet key and set TOKEN_ENCRYPTION_KEY
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. Start both services (backend on :8000, frontend on :3000)
pnpm dev
```

Visit:
- Frontend: <http://localhost:3000>
- Backend API: <http://localhost:8000/api/health>
- OpenAPI docs: <http://localhost:8000/docs>

## Deployment

Two modes supported via `APP_MODE` env var:

- **`local`**: bind to 127.0.0.1, no HTTPS, no password (dev-friendly)
- **`deploy`**: bind to 0.0.0.0, HTTPS required, admin password mandatory

See `plans/260728-grab-store-management-dashboard/research/deployment-guide.md` for full deployment guide (VPS, Tailscale, Cloudflare Tunnel).

## License

Private — single-owner project.
