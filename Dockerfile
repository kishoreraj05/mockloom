# Build the frontend. The app bundles the example specs, so it needs examples/ too.
FROM node:22-slim AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
COPY examples/ /src/examples/
RUN npm run build

# Install real wheels, not editable installs, so this also proves the packaging is complete.
FROM python:3.13-slim AS app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY packages/engine/ packages/engine/
COPY apps/api/pyproject.toml apps/api/
COPY apps/api/src/ apps/api/src/
RUN pip install --upgrade pip && pip install ./packages/engine "./apps/api[postgres]"
WORKDIR /app
RUN rm -rf /src && useradd --create-home --uid 10001 mockloom && mkdir /data && chown mockloom /data
COPY --from=web /src/apps/web/dist/ /app/web/
ENV MOCKLOOM_WEB_DIST=/app/web \
    MOCKLOOM_DATABASE_URL=sqlite:////data/mockloom.db \
    PYTHONUNBUFFERED=1
USER mockloom
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/workspaces', timeout=2)"
# One process on purpose: compiled specs, rules and the log stream are held in memory.
CMD ["uvicorn", "mockloom_api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
