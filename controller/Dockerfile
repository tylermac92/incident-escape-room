# Base images are pinned by multi-arch index digest so amd64 and arm64 build natively (D-01).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# The shared isolation check is a path dependency at ../isolation (a named build context).
COPY --from=isolation . /isolation
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
LABEL com.incident-escape-room.managed="true"
COPY --from=build /app/.venv /app/.venv
COPY feed_templates /app/feed_templates
# A new named volume copies this ownership, so the non-root controller can write /data.
RUN install -d -o 10001 -g 10001 /data
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "controller.app:app", "--host", "0.0.0.0", "--port", "8000"]
