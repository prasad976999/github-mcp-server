# GitHub MCP Server

An [MCP](https://modelcontextprotocol.io) server, written with the official Python MCP SDK, that lets AI assistants (Claude Desktop, Claude Code, any MCP client) explore and work with GitHub: search repositories, read code, triage issues and review pull requests.

> Status: step 7 of 8 (CI with GitHub Actions, coverage, stricter linting). See [docs/ROADMAP.md](docs/ROADMAP.md).

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
- Cursor-style pagination via GitHub `Link` headers, with a hard page cap
- Rate-limit awareness (`X-RateLimit-Remaining`, `Retry-After`) and exponential backoff on 5xx
- Errors returned as tool errors the model can read, never crashes
- Tests with `pytest` + `respx` (mocked HTTP) + the SDK's in-process `Client`, 90% coverage floor
- GitHub Actions CI: ruff lint and format checks, tests on Linux and Windows with Python 3.11 to 3.13
- Dependabot keeps GitHub Actions and Python dependencies up to date
- Dockerfile and demo GIF (coming in step 8)

## Quick start

```bash
uv sync
cp .env.example .env        # add your token
uv run pytest
uv run mcp dev src/github_mcp/server.py   # opens the MCP Inspector
```

Connect it to Claude Code:

```bash
claude mcp add github -e GITHUB_TOKEN=github_pat_xxx -- uv --directory /path/to/github-mcp-server run github-mcp
```

## Checks (the same ones CI runs)

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run pytest --cov            # tests, fails if coverage drops below 90%
```
