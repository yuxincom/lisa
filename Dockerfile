ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim
ARG NPM_REGISTRY=
ARG PIP_INDEX_URL=

FROM ${NODE_IMAGE} AS web
ARG NPM_REGISTRY
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime
ARG PIP_INDEX_URL
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LISA_ENV=production \
    LISA_DATA_DIR=/app/data

WORKDIR /app
RUN groupadd --gid 10001 lisa \
    && useradd --uid 10001 --gid lisa --create-home lisa

COPY backend/requirements.txt ./backend/requirements.txt
RUN if [ -n "$PIP_INDEX_URL" ]; then \
      pip install --no-cache-dir -i "$PIP_INDEX_URL" -r backend/requirements.txt; \
    else \
      pip install --no-cache-dir -r backend/requirements.txt; \
    fi

COPY backend/app ./backend/app
COPY --from=web /build/dist ./frontend/dist

RUN mkdir -p /app/data && chown -R lisa:lisa /app

USER lisa
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
