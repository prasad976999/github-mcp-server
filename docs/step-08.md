# Step 8: Deployment (HTTP mode, Docker) and presentation

Goal: the server can run as a network service in a Docker container, safely, and the project presents itself well to anyone who opens the repository: a README that sells it in 30 seconds and a demo script that shows it working.

New files: `src/github_mcp/http_app.py`, `Dockerfile`, `.dockerignore`, `scripts/demo.py`, `tests/test_http_transport.py` (12 new tests, 55 in total).
Changed files: `config.py` (HTTP settings), `server.py` (`/health` route, `main()` picks the transport, `transport` in `server_status`), `.github/workflows/ci.yml` (Docker job), `.env.example`, `README.md`, `docs/ROADMAP.md`.

## 1. stdio vs Streamable HTTP

MCP defines how messages (JSON-RPC) travel between client and server. That's the **transport**. There are two that matter:

| | stdio | Streamable HTTP |
|---|---|---|
| Who starts the server | The client starts it as a child process | It runs on its own, as a service |
| How they talk | stdin / stdout | HTTP POST to one endpoint (`/mcp`) |
| How many clients | Exactly one | Many, possibly on other machines |
| Security | Nothing listens on the network | Anyone who can reach the port can call it |
| Typical use | Claude Desktop, Claude Code on your laptop | A shared team server, a container, the cloud |

Until now we only had stdio. It's the right default (simplest, safest), so it stays the default. HTTP is opt-in: `MCP_TRANSPORT=http`.

**The key insight:** the tools, resources and prompts don't change at all. Only the way bytes arrive changes. That's why `server.py` needed just a few lines: the transport is a separate layer, which is exactly the point of MCP's design.

```python
def main() -> None:
    logger.info("Starting GitHub MCP server v%s (%s)", __version__, settings.transport)
    if settings.transport == "http":
        from github_mcp.http_app import serve

        serve(settings)
    else:
        mcp.run()  # stdio: the client starts this process and talks over stdin/stdout
```

The import is inside the `if` so stdio users never load the web server code.

## 2. The new problem: the network

With stdio, only the program that started the server can talk to it. With HTTP, **anyone who can reach the port** can, and every request uses *your* GitHub token. So `http_app.py` adds three guards.

### Guard 1: loopback by default

`MCP_HOST` defaults to `127.0.0.1` (**loopback**: only programs on the same computer can connect). `0.0.0.0` means "every network interface", which is what a container needs (see below) but is dangerous on a laptop on public Wi-Fi.

### Guard 2: a bearer token, required off loopback

```python
if settings.http_host not in LOOPBACK_HOSTS and settings.auth_token is None:
    raise RuntimeError(f"Refusing to listen on {settings.http_host} without MCP_AUTH_TOKEN: ...")
```

- **Fail closed**: an unsafe configuration doesn't start with a warning nobody reads, it refuses to start, with a message saying how to fix it. The same philosophy as writes being off by default.
- Clients send `Authorization: Bearer <token>`. A **bearer token** means "whoever bears (holds) this token is allowed in", like a ticket.

The check is a small **ASGI middleware**. ASGI is the standard interface between Python web servers (uvicorn) and web apps (Starlette): an app is just `async def app(scope, receive, send)`. A middleware is an app that wraps another app and decides whether to pass the request on:

```python
async def __call__(self, scope, receive, send):
    if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
        await self.app(scope, receive, send)        # lifespan events and /health pass
        return
    supplied = dict(scope["headers"]).get(b"authorization", b"")
    if hmac.compare_digest(supplied, self._expected):
        await self.app(scope, receive, send)        # right token: through
        return
    ...send a 401 with "WWW-Authenticate: Bearer"
```

- **`hmac.compare_digest`**, not `==`: `==` stops at the first different character, so a wrong guess that starts correctly takes slightly longer. Measured over many requests, that leaks the token one character at a time (a **timing attack**). `compare_digest` always takes the same time.
- **401 Unauthorized** with `WWW-Authenticate: Bearer` is the standard HTTP way to say "you need a bearer token".
- **Why not OAuth?** The SDK supports full OAuth 2.1, which is the right choice for a public multi-user service (each user logs in, gets their own scopes). For a single-owner server, a shared secret is simpler and adequate. Knowing *when* each is appropriate is the interview point.

### Guard 3: DNS rebinding protection

A subtle browser attack: you visit `evil.example`. Its page makes your browser send requests to `evil.example`, then the attacker changes the DNS record of `evil.example` to point to `127.0.0.1`. Your browser now sends requests to *your* local server, but still with `Host: evil.example`. The defence is to refuse any request whose `Host` header isn't one we expect:

```python
security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"] + settings.allowed_hosts,
    ...
)
```

The SDK enables this automatically only when the host is loopback; in a container the host is `0.0.0.0`, so we turn it on explicitly. A refused request gets **421 Misdirected Request**. `MCP_ALLOWED_HOSTS` adds names when you deploy behind a real domain.

### Stateless and JSON

```python
app = mcp.streamable_http_app(stateless_http=True, json_response=True, ...)
```

- **Stateless**: each request stands alone; the server keeps no session between requests. Any copy of the server can answer any request, so you can run several behind a load balancer, and a restart loses nothing. We can do this because our server has no per-session state (no subscriptions, no server-to-client requests).
- **JSON responses**: Streamable HTTP can answer with a stream of events (SSE) for long-running work with progress updates. Our tools answer in one go, so plain JSON is simpler to call and to debug with `curl`.
- The GitHub client is still created **once** at startup: the SDK's session manager enters our lifespan once, not per request.

### `/health`

```python
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})
```

A **liveness check**: Docker, Kubernetes and load balancers poll it to know the process is alive. It needs no token (it reveals nothing) and calls nothing (it must be cheap and must not use the GitHub rate limit).

## 3. The Dockerfile, line by line

A **container image** packages the app, its exact dependencies and a Python runtime, so it runs the same on any machine with Docker. "Works on my machine" becomes "works on every machine".

```dockerfile
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
```

- **`slim`**: a small Debian with Python, about 150 MB smaller than the full image. Smaller images download faster and have fewer packages that could have vulnerabilities.
- **`COPY --from=<image>`**: grabs just the `uv` binary from uv's official image, the method uv's documentation recommends.

```dockerfile
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
```

- **Layer caching**: each instruction is a cached layer, and Docker rebuilds from the first changed one. Dependencies change rarely, code changes often, so dependencies go first. Editing `server.py` then rebuilds in seconds instead of reinstalling everything.
- **`--locked`**: the exact versions from `uv.lock`, the same guarantee as in CI.
- **`--no-dev`**: no pytest or ruff in the image; they're not needed to run it.
- **`--no-editable`**: installs the project as a normal package into `.venv`, so the source folder isn't needed at run time.

```dockerfile
FROM python:3.13-slim
RUN useradd --create-home --uid 10001 mcp
COPY --from=build --chown=mcp:mcp /app/.venv /app/.venv
USER mcp
```

- **Multi-stage build**: the second `FROM` starts a fresh image and copies only the finished virtual environment. uv, caches and build files stay behind in the first stage. The result is smaller and has less in it to attack.
- **Non-root user**: containers run as root by default. If the server were ever compromised, a non-root process can't modify the system. A habit security reviewers look for.

```dockerfile
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8000
EXPOSE 8000
HEALTHCHECK ... CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["github-mcp"]
```

- **`MCP_HOST=0.0.0.0`** inside the container: the container has its own network. Listening on its loopback would make the server unreachable even from your computer. So the image listens on all of the *container's* interfaces, which is why guard 2 forces you to set `MCP_AUTH_TOKEN`.
- **`-p 127.0.0.1:8000:8000`** when you run it: publishes the port only on *your computer's* loopback. Two layers: the token, and not exposing the port to the network.
- **`PYTHONUNBUFFERED=1`**: logs appear immediately in `docker logs`.
- **`HEALTHCHECK`**: Docker polls `/health` and marks the container `healthy` or `unhealthy`. It uses Python's standard library because `slim` has no `curl`.
- **`CMD ["github-mcp"]`**: the script from `[project.scripts]` in `pyproject.toml`. The JSON-array form runs it directly (no shell), so it receives stop signals properly.

`.dockerignore` keeps `.env`, `.git`, `.venv`, tests and docs out of the **build context** (what's sent to Docker). Most importantly, **your token can never be baked into the image**. The token is passed at run time with `--env-file .env`.

I built the image and ran it: about 257 MB, runs as uid 10001, `/health` answers, Docker reports it `healthy`, a request without the token gets 401, and with the token `server_status` reports `"transport": "http"`. Without `MCP_AUTH_TOKEN` it refuses to start with a one-line explanation.

## 4. CI: a Docker job

A third job in `ci.yml` builds the image, starts it, waits for `/health`, and checks that a request without the token gets 401. So CI now proves the image builds, starts and is locked down on every push, not just that the Python tests pass.

## 5. The demo script (`scripts/demo.py`)

An MCP **client** written with the SDK. It connects either by starting the server over stdio (like Claude Desktop does) or to a URL over HTTP, then lists the tools, resource templates and prompts, and calls the main tools on a real repository. It finishes with `create_issue` to show the safe refusal when writes are off.

```python
if url is None:
    return Client(StdioServerParameters(command=sys.executable, args=["-m", "github_mcp.server"]))
return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers)))
```

It's the same `Client` class the tests use, with a different transport, which again shows the transport is a separate layer. For an interview it's a reliable live demo: one command, and it shows every feature. A screen recording of it (or of Claude Desktop using the server) makes a good GIF for the README.

## 6. Tests (`tests/test_http_transport.py`)

Starlette's **`TestClient`** runs the real HTTP app in-process: no port is opened, but every request goes through the full stack (middleware, Host checks, the MCP endpoint), and it runs startup and shutdown so our lifespan creates the GitHub client.

| Test | What it checks | Why it's needed |
|---|---|---|
| `test_tools_are_served_over_http_on_loopback` | `tools/list` over HTTP returns our tools | HTTP mode works at all |
| `test_tool_call_over_http_returns_structured_result` | `server_status` over HTTP returns structured output | A full tool call, not just a listing |
| `test_missing_or_wrong_bearer_token_is_rejected` | No token or wrong token → 401 with `WWW-Authenticate` | The lock works. **Seen to fail when the token check is disabled.** |
| `test_correct_bearer_token_is_accepted` | Right token → 200 | The lock opens for the right key |
| `test_health_check_needs_no_token` | `/health` → 200 even with auth on | Docker's health check needs no secret |
| `test_unknown_host_header_is_refused` | `Host: evil.example` → 421 | DNS rebinding protection. **Seen to fail when protection is off.** |
| `test_extra_allowed_host_is_accepted` | `MCP_ALLOWED_HOSTS` names are let in | Deploying behind a real domain works |
| `test_refuses_public_address_without_auth_token` | `0.0.0.0` without a token → `RuntimeError` | Fail closed |
| `test_public_address_is_allowed_with_auth_token` | `0.0.0.0` with a token builds | The guard isn't over-eager |
| `test_http_settings_are_read_from_environment` | `MCP_*` variables parsed (case, commas, spaces) | Config is where bugs hide |
| `test_defaults_are_stdio_on_loopback_without_token` | Defaults are the safe ones | Safe defaults are a promise; a test keeps it |
| `test_main_picks_the_transport` | `main()` runs stdio or HTTP by setting | The entry point is wired correctly |

Coverage is now about **94%**.

## 7. Try it

PowerShell, without Docker:

```
uv sync
uv run pytest
uv run python scripts/demo.py
```

Expected: `55 passed`, then the demo output (tools, prompts, real data from GitHub).

HTTP mode (needs Docker Desktop):

```
docker build -t github-mcp .
docker run --rm --env-file .env -e MCP_AUTH_TOKEN=pick-a-long-random-secret -p 127.0.0.1:8000:8000 github-mcp
```

In a second PowerShell window:

```
curl.exe http://127.0.0.1:8000/health
$env:MCP_AUTH_TOKEN="pick-a-long-random-secret"; uv run python scripts/demo.py --url http://127.0.0.1:8000/mcp
```

(`curl.exe`, because in PowerShell plain `curl` is an alias for a different command.)

## 8. Interview questions for this step

1. **stdio or HTTP: when would you use each?** stdio when the client runs on the same machine and starts the server, like Claude Desktop: simplest and nothing listens on the network. HTTP when the server is a shared service or runs in a container or the cloud. The tools don't change, only the transport.
2. **What changes for security when you expose an MCP server over HTTP?** Anyone who can reach it can act with its GitHub token. I listen on loopback by default, refuse to listen elsewhere without a bearer token, compare tokens in constant time, and check the Host header against DNS rebinding.
3. **What is DNS rebinding?** A malicious web page makes a domain it controls resolve to 127.0.0.1, so your browser sends its requests to your local server. Checking the Host header blocks it, because those requests still say the attacker's domain.
4. **Why `hmac.compare_digest`?** `==` returns early on the first difference, which leaks how much of a guess was right through timing. compare_digest takes constant time.
5. **Why stateless HTTP?** No session state means any instance can serve any request, so it scales horizontally behind a load balancer and survives restarts. It fits because my tools are simple request/response.
6. **Walk me through your Dockerfile.** Multi-stage: build with uv from the lock file, dependencies in their own layer for caching, then copy only the virtual environment into a fresh slim image, run as a non-root user, with a health check. Secrets are passed at run time and excluded by .dockerignore.
7. **Why does the container listen on 0.0.0.0, and isn't that unsafe?** Inside a container, loopback is the container's own, so the server must listen on all its interfaces to be reachable. It's safe because the server then requires a token, and I publish the port only on the host's loopback.
8. **Bearer token or OAuth?** A shared secret is enough for a single-owner server. For a public, multi-user service I'd use the SDK's OAuth 2.1 support, so each user authorizes with their own scopes.
9. **How do you know the image works?** CI builds it, starts it, waits for /health and checks unauthenticated requests get 401, on every push.
