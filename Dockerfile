# SF Procurement Scout — React SPA + FastAPI API + fetch pipeline, one image.
#
# Build:  docker build -t sf-procurement-scout .
# Run:    docker run -p 8000:8000 sf-procurement-scout
# Set DATABASE_URL for Postgres; without it the app uses SQLite at
# /app/data/scout.db (mount a volume there to keep it across restarts).

# --- Stage 1: build the React bundle ---------------------------------------
FROM node:22-slim AS webbuild

WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Dependencies first, so code edits don't bust the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=webbuild /fe/dist ./frontend/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/healthz')" || exit 1

# Shell form so $PORT (injected by Render/Heroku-style hosts) is honored.
CMD uvicorn web.server:app --host 0.0.0.0 --port ${PORT:-8000}
