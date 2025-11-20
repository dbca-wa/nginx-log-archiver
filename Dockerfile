# syntax=docker/dockerfile:1
# Prepare the base environment.
FROM python:3.13-slim-bookworm AS builder_base

ENV UV_LINK_MODE=copy \
  UV_COMPILE_BYTECODE=1 \
  UV_PYTHON_DOWNLOADS=never \
  UV_PROJECT_ENVIRONMENT=/app/.venv

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
COPY pyproject.toml uv.lock /_lock/
RUN --mount=type=cache,target=/root/.cache \
  cd /_lock && \
  uv sync --frozen --no-group dev

##################################################################################

FROM python:3.13-slim-bookworm
LABEL org.opencontainers.image.authors=asi@dbca.wa.gov.au
LABEL org.opencontainers.image.source=https://github.com/dbca-wa/nginx-log-archiver

# Install system dependencies (inc Azure CLI tools).
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl git \
  # Install the Azure CLI tools
  && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
  && rm -rf /var/lib/apt/lists/*

# Create a non-root user.
RUN groupadd -r -g 10001 app \
  && useradd -r -u 10001 -d /app -g app -N app

COPY --from=builder_base --chown=app:app /app /app
# Make sure we use the virtualenv by default
ENV PATH="/app/.venv/bin:$PATH" \
  # Run Python unbuffered:
  PYTHONUNBUFFERED=1

# Install the project.
WORKDIR /app
COPY *.py ./
USER app
