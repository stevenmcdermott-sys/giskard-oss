# Build context is the repo root (see /railway.json's dockerfilePath), since this
# service depends on sibling workspace packages under /libs via editable path deps.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY libs/ ./libs/
COPY apps/scan-ui/backend/ ./apps/scan-ui/backend/

WORKDIR /app/apps/scan-ui/backend
RUN uv sync --locked --no-dev

EXPOSE 8000
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
