# syntax=docker/dockerfile:1
FROM dhi.io/python:3.13-debian13-dev AS build-stage
LABEL org.opencontainers.image.authors=asi@dbca.wa.gov.au
LABEL org.opencontainers.image.source=https://github.com/dbca-wa/nginx-log-archiver

# Install system packages required to run the project
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl git \
  # Install the Azure CLI tools
  && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
  && rm -rf /var/lib/apt/lists/*

# Import uv to install dependencies
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/
WORKDIR /app
# Install project dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --no-group dev --link-mode=copy --compile-bytecode --no-python-downloads --frozen \
  # Remove uv and lockfile after use
  && rm -rf /bin/uv \
  && rm uv.lock

# Make sure we use the virtualenv by default
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Copy the remaining project files to finish building the project
COPY *.py ./

# Run the project as the nonroot user
USER nonroot
