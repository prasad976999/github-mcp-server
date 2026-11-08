# Build roadmap

Each step ends with something that runs, a passing test suite, and a git commit. Each has its own explainer in `docs/step-NN.md` with interview questions.

| Step | What you build | What it teaches (interview topics) |
|---|---|---|
| 1 | Project scaffold, config, one `server_status` tool, first test, connect to Inspector and Claude | MCP architecture (host/client/server), transports, JSON-RPC, `uv`, src layout, secrets via env |
| 2 | `GitHubClient` in the server lifespan, trimmed Pydantic output models, `search_repositories` + `get_repository`, error mapping, `respx` tests | async I/O, connection pooling, dependency injection, tool design, context budgets |
| 3 | Reading code: `get_file_contents`, `list_directory` (base64 decoding, size limits, binary files) | large outputs, truncation strategies, safe defaults |
| 4 | Pagination (`Link` header) with page caps, plus `list_issues`, `list_pull_requests` | cursor vs offset pagination, bounding cost for LLM callers |
| 5 | Error handling, rate limits (`X-RateLimit-*`, `Retry-After`), retries with backoff | error taxonomy, idempotency, why errors go back to the model as text |
| 6 | Resources (`github://...` URIs) and prompts (`review_pull_request`), a write tool (`create_issue`) with tool annotations | tools vs resources vs prompts, human-in-the-loop, least privilege tokens |
| 7 | Test suite with `respx` mocks, GitHub Actions CI, ruff | testing code that calls external APIs, CI |
| 8 | Dockerfile, Streamable HTTP transport with a bearer token, README polish, demo script | deployment, stdio vs HTTP, network security, containers, presenting the project |
