# syntax=docker/dockerfile:1
# GitHub MCP server as a container, serving Streamable HTTP on port 8000.
#
#   docker build -t github-mcp .
#   docker run --rm --env-file .env -e MCP_AUTH_TOKEN=<random secret> \
#     -p 127.0.0.1:8000:8000 github-mcp
#
# Two stages: the first installs dependencies with uv, the second copies only the
# finished virtual environment, so the final image has no uv, no build cache, no tests.

# ---- Stage 1: build ------------------------------------------------------------------
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, in their own layer: this layer is reused from cache on every
# rebuild until pyproject.toml or uv.lock changes, so code edits rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the code itself.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- Stage 2: run --------------------------------------------------------------------
FROM python:3.13-slim
# Never run as root: if the process were ever compromised, it can't change the image.
RUN useradd --create-home --uid 10001 mcp
COPY --from=build --chown=mcp:mcp /app/.venv /app/.venv
USER mcp
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000
EXPOSE 8000
# Docker marks the container unhealthy if /health stops answering.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["github-mcp"]
