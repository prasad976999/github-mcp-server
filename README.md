# GitHub MCP Server

[![CI](https://github.com/prasad976999/github-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/prasad976999/github-mcp-server/actions/workflows/ci.yml)
![Python 3.11 to 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![coverage 94%](https://img.shields.io/badge/coverage-94%25-brightgreen)

An [MCP](https://modelcontextprotocol.io) server, written with the official Python MCP SDK, that lets AI assistants (Claude Desktop, Claude Code, any MCP client) explore and work with GitHub: search repositories, read code, triage issues and review pull requests.

It runs two ways: over **stdio**, started by the AI app itself, or as an **HTTP service** in Docker, protected by a bearer token.

## What you can ask an assistant to do with it

- "Find popular Python MCP servers and tell me which is most active."
- "Explain how the `src/` folder of modelcontextprotocol/python-sdk is organised."
- "What are the five newest open issues on this repo, and which look like bugs?"
- "Review pull request 123" (the `review_pull_request` prompt loads the description and diffs).
- "Open an issue for this bug" (only when writes are switched on, and only after showing you the text).

## Architecture

```
┌──────────────────────┐   JSON-RPC over stdio   ┌───────────────────────────────┐   HTTPS   ┌──────────────┐
│ MCP client (host)     │ ──────────────────────▶ │ github-mcp server              │ ────────▶ │ GitHub REST  │
│ Claude Desktop / Code │ ◀────────────────────── │                               │ ◀──────── │ API v3       │
└──────────────────────┘                         │  server.py   tools/resources/  │           └──────────────┘
                                                  │              prompts           │
                                                  │  github_client.py  async httpx │
                                                  │   auth · pagination · retries  │
                                                  │   rate-limit · error mapping   │
                                                  │  models.py   trimmed outputs   │
                                                  └───────────────────────────────┘
```

Layers, each with one job:

| Layer | File | Responsibility |
|---|---|---|
| Protocol | `server.py` | Registers tools, resources and prompts with `MCPServer`; no HTTP code here. |
| API client | `github_client.py` | One shared `httpx.AsyncClient`: auth header, timeouts, pagination, rate-limit handling, retries, error mapping. |
| Models | `models.py` | Pydantic models that trim GitHub's huge JSON down to what an LLM needs (saves tokens, gives typed structured output). |
| Config | `config.py` | Reads `GITHUB_TOKEN` etc. from the environment. |

## Features

**Tools** (actions the model can call)

- `search_repositories`, `get_repository`
- `list_directory`, `get_file_contents`
- `list_issues`, `list_pull_requests` (newest first, safe pagination)
- `create_issue` (write tool: off unless `GITHUB_ALLOW_WRITES=true`, annotated as non-read-only)
- `server_status`, `get_rate_limit`

**Resources** (read-only data addressed by URI)

- `github://repos/{owner}/{repo}/readme`

**Prompts** (reusable templates the user picks)

- `summarize_repository(owner, repo)`
- `review_pull_request(owner, repo, number)` (loads the PR description and diffs for you)

**Engineering**

- Async I/O with a single pooled `httpx.AsyncClient`, created in the server lifespan
- Pagination via GitHub `Link` headers, with a hard page cap
- Rate-limit awareness (`X-RateLimit-Remaining`, `Retry-After`) and exponential backoff with jitter; only idempotent requests are retried
- Errors returned as tool errors the model can read and act on, never crashes
- Two transports: stdio, and Streamable HTTP (stateless, JSON responses) with a bearer token, DNS rebinding protection and a `/health` endpoint
- Docker image: multi-stage build, non-root user, health check
- 55 tests with `pytest` + `respx` (mocked HTTP) + the SDK's in-process `Client`, 90% coverage floor
- GitHub Actions CI: ruff lint and format, tests on Linux and Windows with Python 3.11 to 3.13, and a Docker build-and-run check
- Dependabot keeps GitHub Actions and Python dependencies up to date

## Quick start (stdio)

```bash
uv sync
cp .env.example .env        # add your token (on Windows: copy .env.example .env)
uv run pytest
uv run python scripts/demo.py   # a scripted tour: lists everything, calls the main tools
uv run mcp dev src/github_mcp/server.py   # or explore it in the MCP Inspector
```

Connect it to Claude Code:

```bash
claude mcp add github -e GITHUB_TOKEN=github_pat_xxx -- uv --directory /path/to/github-mcp-server run github-mcp
```

Or to Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "github": {
      "command": "uv",
      "args": ["--directory", "/path/to/github-mcp-server", "run", "github-mcp"],
      "env": { "GITHUB_TOKEN": "github_pat_xxx" }
    }
  }
}
```

## Run it as an HTTP service (Docker)

```bash
docker build -t github-mcp .
docker run --rm --env-file .env -e MCP_AUTH_TOKEN=pick-a-long-random-secret \
  -p 127.0.0.1:8000:8000 github-mcp
curl http://127.0.0.1:8000/health                       # {"status":"ok",...}
MCP_AUTH_TOKEN=pick-a-long-random-secret uv run python scripts/demo.py --url http://127.0.0.1:8000/mcp
```

Connect Claude Code to it:

```bash
claude mcp add --transport http github http://127.0.0.1:8000/mcp --header "Authorization: Bearer pick-a-long-random-secret"
```

Without Docker: `MCP_TRANSPORT=http uv run github-mcp` serves on 127.0.0.1:8000.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GITHUB_TOKEN` | none | Fine-grained token. Without it you get 60 requests/hour instead of 5,000. |
| `GITHUB_ALLOW_WRITES` | off | Set to `true` to enable `create_issue`. |
| `GITHUB_TIMEOUT_S` | 15 | Timeout for each GitHub request. |
| `MCP_TRANSPORT` | `stdio` | `http` to serve Streamable HTTP. The Docker image sets this. |
| `MCP_HOST`, `MCP_PORT` | `127.0.0.1`, `8000` | Where HTTP mode listens. |
| `MCP_AUTH_TOKEN` | none | Bearer token clients must send in HTTP mode. Required for any host but loopback. |
| `MCP_ALLOWED_HOSTS` | none | Extra `Host` header values to accept, comma-separated. |

## Security model

- **Secrets stay out of code and git**: tokens come from environment variables or a git-ignored `.env`, which is also kept out of the Docker image.
- **Least privilege**: a read-only token is enough; writes need a separate switch and a token that allows them; CI runs with `contents: read`.
- **Writes need a human**: `create_issue` is off by default, annotated as non-read-only, and the instructions tell the model to show the user first.
- **HTTP mode is closed by default**: it listens on loopback, refuses to listen anywhere else without a bearer token, compares tokens in constant time, and rejects unknown `Host` headers (DNS rebinding protection).
- **The container runs as a non-root user.**

## Project structure

```
src/github_mcp/
  server.py         tools, resource, prompts, /health, entry point
  github_client.py  HTTP to GitHub: auth, retries, rate limits, pagination, errors
  models.py         trimmed, typed outputs
  config.py         settings from environment variables
  http_app.py       HTTP mode: bearer token, Host checks, stateless app
tests/              55 tests, one file per build step
scripts/demo.py     scripted tour for demos
Dockerfile          multi-stage image, non-root, health check
docs/               step-by-step explainers (step-01.md to step-08.md) and the study guide
```

## Checks (the same ones CI runs)

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run pytest --cov            # tests, fails if coverage drops below 90%
docker build -t github-mcp .   # the image builds
```

## How it was built

In eight steps, each with its own explainer in [docs/](docs/) and a commit: scaffold, repositories, reading code, pagination, retries and rate limits, resources/prompts/writes, CI, and deployment. [docs/ROADMAP.md](docs/ROADMAP.md) lists them, and [docs/STUDY-GUIDE.md](docs/STUDY-GUIDE.md) (also as HTML, PDF and slides) explains every decision.
