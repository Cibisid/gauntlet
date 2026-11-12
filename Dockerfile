# syntax=docker/dockerfile:1.7
# Multi-stage build: wheels are built in a full image; the runtime image is slim,
# runs as a non-root user and contains no build tools.
# Default command runs the proxy; override with `mock-server`, `run`, `gate`, etc.

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip build && python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GAUNTLET_STATE_DIR=/var/lib/gauntlet
# Apply Debian security updates the base image hasn't picked up yet: Trivy fails CI on any
# HIGH/CRITICAL CVE that has a fix (zlib1g CVE-2026-76844 / CVE-2026-85091 first tripped this).
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app app \
 && mkdir -p /var/lib/gauntlet && chown app:app /var/lib/gauntlet
WORKDIR /app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
COPY --chown=app:app releases ./releases
COPY --chown=app:app cases ./cases
COPY --chown=app:app judges ./judges
USER 10001
EXPOSE 8080 8089
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('HEALTH_PORT','8080'); urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=2)" || exit 1
ENTRYPOINT ["gauntlet"]
CMD ["proxy", "--host", "0.0.0.0", "--port", "8080"]
