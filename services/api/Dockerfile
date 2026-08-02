# ── Stage 1: builder ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv (faster, more reliable than pip for locked deps)
RUN pip install uv

# Copy lockfile + manifest, then install all deps into .venv
COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project

# ── Stage 2: runtime ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy pre-built venv from builder
COPY --from=builder /app/.venv ./.venv

# Copy application source
COPY app/ ./app/
COPY grab/ ./grab/
COPY pyproject.toml README.md ./

# Expose FastAPI port
EXPOSE 8000

# Virtual environment activated via PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run via uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
