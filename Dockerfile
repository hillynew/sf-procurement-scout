# SF Procurement Scout — FastAPI dashboard + fetch pipeline in one image.
#
# Build:  docker build -t sf-procurement-scout .
# Run:    docker run -p 8000:8000 -v "$PWD/data:/app/data" sf-procurement-scout
# The data/ volume keeps fetch snapshots and user workflow state across
# container restarts; omit it for a throwaway instance.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Dependencies first, so code edits don't bust the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/healthz')" || exit 1

# Shell form so $PORT (injected by Render/Heroku-style hosts) is honored.
CMD uvicorn web.server:app --host 0.0.0.0 --port ${PORT:-8000}
