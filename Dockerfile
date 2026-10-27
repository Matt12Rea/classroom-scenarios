# One image that serves the whole site: the React front end and the FastAPI back end.
#   docker build -t aicss .
#   docker run -p 8000:8000 --env-file .env aicss

# ---- 1. build the website --------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# ---- 2. the server ---------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=production FRONTEND_DIST=/app/frontend/dist PORT=8000 WEB_CONCURRENCY=2
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
# Run as an unprivileged user. /app/data holds the SQLite file if you don't use PostgreSQL.
RUN useradd --create-home --uid 10001 aicss && mkdir -p /app/data && chown -R aicss /app/data
USER aicss
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health',timeout=4)"
# --proxy-headers: trust the HTTPS proxy (Caddy, Render, etc.) to report the real
# visitor IP and https scheme. Each worker handles many requests at once.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
