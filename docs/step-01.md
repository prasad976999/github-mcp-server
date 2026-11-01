# Step 1: Scaffold and first tool

Goal: a real MCP server that an AI client can connect to and call, with one tool. No GitHub calls yet; we prove the wiring first.

## 1. What MCP is (the 30-second interview answer)

MCP (Model Context Protocol) is an open protocol, created by Anthropic, that standardises how AI applications connect to external tools and data. Before MCP, every AI app wrote its own integration for every service (N apps x M services). With MCP, a service is wrapped once as an **MCP server** and any **MCP host** (Claude Desktop, Claude Code, IDEs, other agents) can use it. People call it "USB-C for AI tools".

Three roles:

- **Host**: the AI application the user talks to (Claude Desktop, Claude Code).
- **Client**: a component inside the host that holds one connection to one server.
- **Server**: our program. It exposes capabilities and does the real work (calling GitHub).

Messages are **JSON-RPC 2.0**. The host starts by asking the server what it offers (`initialize`, then `tools/list`), and the model decides when to call a tool (`tools/call`).

## 2. The three server primitives

| Primitive | Who controls it | Example in this project |
|---|---|---|
| **Tool** | The model decides to call it | `search_repositories`, `create_issue` |
| **Resource** | The application/user attaches it as context | `github://repos/{owner}/{repo}/readme` |
| **Prompt** | The user picks it (like a slash command) | `review_pull_request` |

This distinction is a very common interview question. Short answer: tools are model-controlled actions, resources are application-controlled read-only data, prompts are user-controlled templates.

## 3. Transports

- **stdio** (what we use now): the host launches our server as a subprocess and talks over stdin/stdout. Simple, local, no network port, the token never leaves the machine.
- **Streamable HTTP**: the server runs as a web service, many clients connect over HTTP. Needed for remote/multi-user deployments (we add it in step 8).

Consequence of stdio that trips people up: **stdout is the protocol channel**. Any `print()` corrupts the JSON-RPC stream. That's why `server.py` sends logs to stderr.

## 4. Project layout

```
github-mcp-server/
├── pyproject.toml        # dependencies + entry point, managed by uv
├── uv.lock               # exact pinned versions (reproducible installs)
├── .env.example          # documents required env vars; real .env is git-ignored
├── src/github_mcp/
│   ├── __init__.py       # version
│   ├── config.py         # Settings from env
│   └── server.py         # MCPServer + tools
├── tests/test_server.py
└── docs/
```

Why each choice:

- **`uv`**: a fast Python package manager (Rust). One tool replaces pip, venv and pip-tools; `uv.lock` makes installs reproducible. Claude Desktop/Code configs commonly launch servers with `uv run`.
- **`src/` layout**: tests import the *installed* package, not files that happen to be in the working directory. Catches packaging bugs early.
- **`[project.scripts] github-mcp = ...`**: gives a real command name, so clients launch `github-mcp` instead of a file path.
- **`mcp[cli]`**: the SDK plus its CLI (`mcp dev` opens the MCP Inspector).

## 5. The code, line by line

### `config.py`
- `SecretStr` wraps the token so it prints as `**********` if it ever ends up in a log or traceback. Small detail, good interview point about secret hygiene.
- Settings come from **environment variables** because the MCP host passes secrets to the server that way (the `env` block in the client config). Never hard-code tokens, never commit `.env`.
- `request_timeout_s: Field(gt=0)`: Pydantic validates config at startup, so a bad value fails fast instead of mid-request.

### `server.py`
- `MCPServer(name=..., instructions=...)`: the high-level server class in **MCP Python SDK v2** (in v1 it was called `FastMCP`; many tutorials online still show v1, so you can mention you used the current v2 API). `instructions` is sent to the host during `initialize` and helps the model understand how to use the server as a whole.
- `@mcp.tool()`: registers a function as a tool. The SDK reads the **function name** (tool name), **docstring** (tool description the model sees), **type hints** (JSON Schema for the inputs) and **return type** (output schema). This is the key idea of "tool design": your docstring and parameter names *are the prompt* the model uses to decide when and how to call the tool.
- Returning a **Pydantic model** (`ServerStatus`) instead of a plain dict gives the client `structuredContent` with a declared output schema, so the model and client get typed, predictable data. (Our first test caught exactly this: a bare `dict` produced no structured output.)
- `mcp.run()` defaults to the stdio transport.

### `tests/test_server.py`
- `Client(mcp)` connects to the server **in-process**, no subprocess or network. The test does exactly what a host does: list tools, call one, check the result. Fast and deterministic.

## 6. Run it yourself

```bash
# once: install uv  ->  https://docs.astral.sh/uv/getting-started/installation/
cd github-mcp-server
uv sync                      # creates .venv and installs everything from uv.lock
uv run pytest                # 1 passed
uv run mcp dev src/github_mcp/server.py
```

`mcp dev` opens the **MCP Inspector** in your browser: click *Connect*, open *Tools*, run `server_status`. You are now doing by hand what Claude does automatically.

Then connect a real host. Claude Code:

```bash
claude mcp add github -- uv --directory /ABSOLUTE/PATH/github-mcp-server run github-mcp
```

Claude Desktop (`claude_desktop_config.json`, Settings > Developer > Edit Config):

```json
{
  "mcpServers": {
    "github": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/github-mcp-server", "run", "github-mcp"],
      "env": { "GITHUB_TOKEN": "github_pat_xxx" }
    }
  }
}
```

Ask Claude: "Is the GitHub server connected? Check its status." It should call `server_status`.

## 7. Commit

```bash
git init && git add . && git commit -m "Scaffold MCP server with server_status tool"
```

Create an empty repo on your GitHub and push. Commit after every step so the history itself tells the story to a reviewer.

## 8. Interview questions for this step

1. **What problem does MCP solve?** The N x M integration problem; one standard protocol between AI apps and tools/data.
2. **Host vs client vs server?** Host = AI app; client = one connection inside the host; server = exposes tools/resources/prompts.
3. **Tool vs resource vs prompt?** Model-controlled action / app-controlled read-only data / user-chosen template.
4. **Why can't you `print()` in a stdio MCP server?** stdout carries JSON-RPC; extra output corrupts the stream. Log to stderr.
5. **How does the model know what a tool does?** From the name, description (docstring) and JSON Schema the SDK generates from type hints, sent in `tools/list`.
6. **How do you pass secrets to an MCP server?** Environment variables set by the host config; never in code or the repo; least-privilege fine-grained tokens.
7. **stdio vs Streamable HTTP?** Local subprocess, single user, no network exposure vs remote service, many clients, needs auth (OAuth) and hardening.
8. **How did you test it?** In-process SDK `Client` against the server object; later, HTTP mocked with `respx`.
