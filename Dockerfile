# syntax=docker/dockerfile:1

# ---- Builder stage ----
FROM dhi.io/python:3.13-debian13-dev AS builder
LABEL org.opencontainers.image.authors=asi@dbca.wa.gov.au
LABEL org.opencontainers.image.source=https://github.com/dbca-wa/nginx-log-archiver

# Install system packages required to run the project
RUN <<EOF
set -euxo pipefail
apt-get update
apt-get install -y --no-install-recommends \
  curl \
  git
# Install the Azure CLI tools
curl -sL https://aka.ms/InstallAzureCLIDeb | bash
EOF

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --no-group dev --link-mode=copy --compile-bytecode --no-python-downloads --frozen

# Environment variables
ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PATH="/app/.venv/bin:$PATH"

# Copy the remaining project files to finish building the project
COPY *.py ./

# Run the project as the nonroot user
USER nonroot
