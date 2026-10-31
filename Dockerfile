# syntax=docker/dockerfile:1.7
# Multi-stage build: wheels are built in a full image, the runtime image is slim,
# runs as a non-root user and contains no build tools.

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip build && python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
COPY --chown=app:app releases ./releases
COPY --chown=app:app cases ./cases
USER app
EXPOSE 8089
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8089/healthz', timeout=2)" || exit 1
ENTRYPOINT ["gauntlet"]
CMD ["mock-server", "--host", "0.0.0.0", "--port", "8089"]
