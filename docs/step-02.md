# Step 2: GitHub client and first real tools

Goal: the server talks to the real GitHub API. Two tools: `search_repositories` and `get_repository`.

New and changed files:

```
src/github_mcp/
├── config.py          # now also reads a local .env file
├── github_client.py   # NEW: all HTTP code lives here
├── models.py          # NEW: trimmed output shapes
└── server.py          # lifespan + two new tools
tests/
├── conftest.py        # NEW: respx fixture that fakes GitHub
└── test_repositories.py  # NEW: 5 tests
```

## 1. The big idea: layers

```
tool function (server.py)  →  GitHubClient (github_client.py)  →  GitHub REST API
        ↑ returns a Pydantic model (models.py)
```

- **server.py** knows about MCP: tool names, descriptions, inputs, errors the model should see. It contains no URLs or headers.
- **github_client.py** knows about HTTP: base URL, auth header, timeouts, turning failed responses into one exception type.
- **models.py** decides what data the model actually gets back.

Interview line: *"I separated the protocol layer from the API layer, so I can test each on its own and swap the transport or the API without touching the other."*

## 2. `github_client.py`

**Headers**
- `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`: GitHub recommends both. Pinning the API version means a future GitHub change can't silently break us.
- `User-Agent`: GitHub rejects requests without one.
- `Authorization: Bearer <token>`: only added when a token exists. Without a token GitHub allows 60 requests/hour per IP; with one, 5,000/hour. That's the main reason to use a token even for public data.

**One shared `httpx.AsyncClient`**
- Created once, reused for every call. It keeps a **connection pool**: the TCP + TLS handshake (often 100ms+) happens once, not on every request.
- **Async** because MCP servers handle requests concurrently. While one tool waits on GitHub, the server can work on another request instead of blocking. This is I/O-bound work, which is exactly where `async` helps.
- **Timeout** (15s default): never let a hung network call hang the model's turn forever.

**Error mapping**
- Every failure (timeout, network error, 401, 403, 404, 422, 5xx) becomes one `GitHubAPIError` with a **plain-English message plus the HTTP status**. The message is written for the *model* to read, because the model is the one that decides what to do next (fix a typo in the repo name, ask the user for a token, try a different query).

## 3. `models.py`: why trim the output?

A raw GitHub repository response has around 100 fields, most of them URLs. Every field costs tokens in the model's context window and adds noise. `Repository.from_api()` keeps around 13 useful ones.

Returning a Pydantic model (not a dict) also gives the client an **output schema** and `structuredContent`, so the model gets typed, predictable fields. `Repository` extends `RepoSummary`, so search results stay short and the detailed view adds more.

Interview line: *"Tool output design is context engineering. I return the smallest useful shape, and a search tool returns summaries with a separate get tool for details."*

## 4. `server.py`

**Lifespan**
```python
@asynccontextmanager
async def lifespan(_server):
    github = GitHubClient(settings)
    try:
        yield AppContext(github=github)
    finally:
        await github.aclose()
```
Code before `yield` runs at startup; code after runs at shutdown. The yielded `AppContext` is available to every tool through `ctx.request_context.lifespan_context`. This is **dependency injection**: tools don't create their own client, they receive a shared one, and connections are closed cleanly when the server stops.

**`ctx: Context`**: a parameter typed as `Context` is injected by the SDK and **hidden from the model**. It isn't part of the tool's input schema.

**Tool design choices** (the "tool design" learning goal from your image):
- **Names** are verbs plus nouns (`search_repositories`, `get_repository`), matching how the model thinks about the task.
- **Docstrings** say what the tool returns *and when to use another tool* ("call get_repository for full details").
- **`Annotated[str, Field(description=...)]`** puts a description and examples on each parameter. The search description teaches GitHub query syntax (`language:python`, `stars:>1000`), which makes the model write much better queries.
- **`Field(ge=1, le=30)`** on `limit`: input validation. The model can't ask for 500 results; the SDK rejects it before our code runs.
- **`ToolAnnotations(read_only_hint=True, open_world_hint=True)`**: hints to the host that the tool doesn't change anything and talks to an external system. Hosts can use this to skip confirmation prompts for safe tools and ask before risky ones.
- **`raise ToolError(...)`**: turns our error into a tool result with `isError: true`. The model reads it and can recover. The server doesn't crash, and no stack trace leaks.

## 5. `config.py`: `.env` support

`load_dotenv(override=False)` reads `GITHUB_TOKEN` from a local `.env` file during development. `override=False` means a real environment variable (for example one set by Claude Desktop's config) wins. `.env` is in `.gitignore`, so the token never gets committed.

## 6. Tests: `respx`

`respx` intercepts `httpx` calls and returns fake responses, so the tests:
- never touch the network (fast, no rate limits, work offline, work in CI),
- can simulate failures that are hard to trigger for real: 404, timeouts.

The 5 tests cover: trimming works, a 404 becomes a readable tool error, the query and limit are passed correctly, the limit is validated, and a timeout becomes a tool error.

## 7. Run it on Windows (PowerShell)

### 7.1 Create a fine-grained GitHub token
1. Go to https://github.com/settings/personal-access-tokens/new
2. Token name: `github-mcp-server`. Expiration: 90 days.
3. Repository access: **Public repositories (read-only)**.
4. Click **Generate token** and copy it (it starts with `github_pat_`). You will only see it once.

*Why fine-grained and read-only?* **Least privilege**: if the token leaks, it can only read public data. Good interview point.

### 7.2 Put it in `.env`
```powershell
cd C:\Users\prasa\projects\github-mcp-server
Copy-Item .env.example .env
notepad .env
```
Replace `github_pat_xxx` with your token, save, close Notepad.

### 7.3 Install new packages and run tests
```powershell
uv sync
uv run pytest
```
Expected: `6 passed`.

### 7.4 Try it live in the Inspector
```powershell
uv run mcp dev src/github_mcp/server.py
```
Connect, then **Tools → List Tools**. Try:
- `server_status`: `authenticated` should now be `true`.
- `search_repositories` with query `mcp server language:python`, limit `5`.
- `get_repository` with owner `modelcontextprotocol`, repo `python-sdk`.
- `get_repository` with owner `nobody-xyz`, repo `nothing`. You should see a readable "Not found" error, not a crash.

## 8. Interview questions for this step

1. **Why async?** GitHub calls are I/O-bound; async lets one process serve concurrent requests while waiting on the network.
2. **Why one shared HTTP client instead of one per request?** Connection pooling avoids repeated TCP/TLS handshakes; it also centralises config and is closed cleanly in the lifespan.
3. **What is the lifespan for?** Startup/shutdown of shared resources and dependency injection into tools via the context.
4. **How does the model see errors?** As tool results with `isError: true` and a human-readable message, so it can correct itself. Never crash, never leak stack traces or secrets.
5. **Why trim API responses?** The context window is a budget; fewer, relevant fields mean cheaper calls and better model decisions.
6. **What makes a good tool description?** Clear name, what it returns, when to use it vs other tools, parameter descriptions with examples, constraints in the schema.
7. **What are tool annotations?** Hints like read-only/destructive/idempotent/open-world that hosts use for safety and UX decisions. They are hints, not security guarantees.
8. **How do you test code that calls an external API?** Mock the HTTP layer (`respx`), test success and failure paths, keep live tests separate and optional.
9. **How do you handle the GitHub token?** Env var / git-ignored `.env`, `SecretStr` so it never prints, fine-grained read-only scope, rotated by expiry.
