# GitHub MCP Server

An [MCP](https://modelcontextprotocol.io) server, written with the official Python MCP SDK, that lets AI assistants (Claude Desktop, Claude Code, any MCP client) explore and work with GitHub: search repositories, read code, triage issues and review pull requests.

> Status: step 4 of 8 (issues, pull requests, safe pagination). See [docs/ROADMAP.md](docs/ROADMAP.md).

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

## Features (planned)

**Tools** (actions the model can call)
- `search_repositories`, `get_repository`, `get_file_contents`, `list_directory`
- `list_issues`, `get_issue`, `create_issue` (write, marked destructive-safe via tool annotations)
- `list_pull_requests`, `get_pull_request_diff`
- `server_status`

**Resources** (read-only data addressed by URI)
- `github://repos/{owner}/{repo}/readme`
- `github://user/me`

**Prompts** (reusable templates the user picks)
- `review_pull_request(owner, repo, number)`
- `summarize_repository(owner, repo)`

**Engineering**
- Async I/O with a single pooled `httpx.AsyncClient`, created in the server lifespan
- Cursor-style pagination via GitHub `Link` headers, with a hard page cap
- Rate-limit awareness (`X-RateLimit-Remaining`, `Retry-After`) and exponential backoff on 5xx
- Errors returned as tool errors the model can read, never crashes
- Tests with `pytest` + `respx` (mocked HTTP) + the SDK's in-process `Client`
- Dockerfile, GitHub Actions CI, demo GIF

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
