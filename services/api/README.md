# PulseOrder API

Backend for the PulseOrder Grab Merchant dashboard. Handles Grab OAuth, menu
management, category/item CRUD, and modifier configuration through the Grab
Merchant API.

## Quick Start

### Local dev mode

```bash
cd services/api
uv sync
APP_MODE=local uv run uvicorn app.main:app --reload
```

Visit <http://127.0.0.1:8000/docs> for the OpenAPI docs.

### Seed Fernet key (local dev only)

In `local` mode a disposable key is generated on startup. For repeatable local
sessions, set `TOKEN_ENCRYPTION_KEY` in your `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Deploy Mode

Requires the following environment variables in `.env`:

| Variable | Description |
|---|---|
| `APP_MODE` | `deploy` (required — enables HTTPS enforcement) |
| `SESSION_SECRET` | Secret for itsdangerous signed-session cookies |
| `ADMIN_PASSWORD_HASH` | bcrypt hash of the admin password |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting stored Grab tokens |
| `DATABASE_URL` | SQLite path or postgres URL (default: `sqlite:///./data/grab.db`) |

### Nginx reverse proxy example

Place certs in `services/api/deploy/certs/` (`fullchain.pem`, `privkey.pem`) and use the
included `deploy/nginx.conf`. Ensure `APP_MODE=deploy` and all secrets above are
set before starting `docker compose up`.

## Endpoints

| Router | Prefix | Description |
|---|---|---|
| `auth` | `/api/auth` | Login, logout, session, token refresh |
| `stores` | `/api/stores` | List stores, store detail, select active store |
| `menu` | `/api/menu` | Full Grab menu fetch |
| `categories` | `/api/categories` | Create, delete, reorder categories |
| `items` | `/api/items` | Create items, upload images |
| `modifiers` | `/api/modifiers` | Verify modifiers, create modifier groups |

Healthcheck: `GET /api/health`

## Token Storage

Grab OAuth tokens are encrypted at rest using **Fernet symmetric encryption**
(`cryptography.fernet.Fernet`). The key is set via `TOKEN_ENCRYPTION_KEY` and
must be a valid Fernet key (44 characters, base64-encoded). Tokens are never
stored in plaintext; the encrypted blob is persisted in SQLite alongside the
user record.

## Development

```bash
# Install dev deps
uv sync --group dev

# Run tests
uv run pytest

# With coverage
uv run pytest --cov=app --cov=grab --cov-report=term-missing

# Type check
uv run mypy app/ grab/

# Lint
uv run ruff check app/ grab/
```

## Docker

```bash
# From workspace root (d:/VIBE CODE/grab/grab-dashboard/)
docker compose up --build

# API only (local dev without nginx)
cd services/api
docker build -t pulseorder-api .
docker run -p 127.0.0.1:8000:8000 --env-file .env pulseorder-api
```

Required `.env` variables for deploy (not needed in `local` mode):

```
APP_MODE=deploy
SESSION_SECRET=<random 32+ byte secret>
ADMIN_PASSWORD_HASH=<bcrypt hash>
TOKEN_ENCRYPTION_KEY=<44-char Fernet key>
```
