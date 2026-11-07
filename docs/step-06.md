# Step 6: Resources, prompts and a write tool

Goal: use all three MCP server primitives (tools, resources and prompts), and add the first tool that **changes** GitHub, with the safety measures a write deserves.

New:
- Tool `create_issue(owner, repo, title, body=None, labels=None)`: off by default.
- Resource template `github://repos/{owner}/{repo}/readme`
- Prompt `summarize_repository(owner, repo)`
- Prompt `review_pull_request(owner, repo, number)`

Changed files: `config.py` (`allow_writes`), `github_client.py` (`post()`, the retry loop becomes `_request(method, ...)`), `models.py` (`CreatedIssue`), `server.py` (all of the above, plus `writes_enabled` in `server_status`), `.env.example`, `README.md`, `tests/test_resources_prompts_and_writes.py` (13 new tests, 43 in total).

## 1. Tools vs resources vs prompts (a classic interview question)

| | **Tools** | **Resources** | **Prompts** |
|---|---|---|---|
| Who decides to use it | The **model** | The **application** (host) or the user | The **user** |
| What it is | An action, like a function call | Read-only data with a URI | A reusable message template |
| Side effects | May have (e.g. `create_issue`) | Never | Never by itself |
| Example here | `list_issues`, `create_issue` | `github://repos/pallets/flask/readme` | `review_pull_request` |
| How a host shows it | Called automatically mid-conversation | An "attach" / "add context" picker | A slash command or menu, e.g. `/review_pull_request` |

Rule of thumb: **if the model should decide when to do it, it's a tool. If it's data a user or app attaches as context, it's a resource. If it's a workflow the user starts, it's a prompt.**

## 2. The README resource

```python
@mcp.resource(
    "github://repos/{owner}/{repo}/readme",
    name="readme",
    title="Repository README",
    description="The README of a GitHub repository, as text.",
    mime_type="text/markdown",
)
async def readme(owner: str, repo: str, ctx: Context) -> str:
    try:
        data = await _github(ctx).get(f"/repos/{owner}/{repo}/readme")
    except GitHubAPIError as exc:
        raise ResourceError(str(exc)) from exc
    text = _decode_text(base64.b64decode(data.get("content", "")))
    if text is None:
        raise ResourceError(f"The README of {owner}/{repo} is not a text file.")
    return text
```

- **A URI template** (`{owner}` and `{repo}` are placeholders, RFC 6570 syntax). Because the URI has placeholders, the SDK registers a **resource template**: clients list it with `resources/templates/list` and read a concrete URI like `github://repos/pallets/flask/readme` with `resources/read`.
- **The custom scheme `github://`** is ours. Any URI scheme is allowed; a clear one tells the user what the data is.
- **`/repos/{owner}/{repo}/readme`** is GitHub's endpoint that finds the README whatever it's called (`README.md`, `readme.rst`...).
- **`mime_type="text/markdown"`** tells the host how to display it.
- **`ResourceError`**: resources have no `isError` result like tools do, so the error goes back as a protocol error with our readable message.
- **Reuses `_decode_text`** from step 3, the same base64 and binary handling as `get_file_contents`.

## 3. Prompts

### `summarize_repository`: a pure template

```python
@mcp.prompt(title="Summarise a repository")
def summarize_repository(owner: str, repo: str) -> str:
    """Get a short overview of a repository: what it does, how it's built, how healthy it is."""
    return (
        f"Give me an overview of the GitHub repository {owner}/{repo} ... "
        "Use get_repository for the facts, read the README ..., list_directory ..., list_issues ..."
        "Cover: what it does and who it's for, the tech stack, ... Keep it under 300 words."
    )
```

- Returning a `str` makes **one user message**. The host puts it in the chat as if the user had typed it.
- It makes no API calls itself. It **tells the model which tools to use**, so a good workflow is packaged once instead of retyped by every user.

### `review_pull_request`: a prompt that loads context

```python
@mcp.prompt(title="Review a pull request")
async def review_pull_request(owner: str, repo: str, number: int, ctx: Context) -> str:
    github = _github(ctx)
    try:
        pr = await github.get(f"/repos/{owner}/{repo}/pulls/{number}")
        files, more_files = await github.get_paginated(
            f"/repos/{owner}/{repo}/pulls/{number}/files", max_items=100
        )
    except GitHubAPIError as exc:
        code = INVALID_PARAMS if exc.status_code < 500 else INTERNAL_ERROR
        raise MCPError(code, str(exc)) from exc
    ...
    budget = MAX_DIFF_CHARS  # 40,000
    for f in files:
        patch = f.get("patch") or "(no text diff: binary or very large file)"
        if len(patch) > budget:
            skipped += 1  # leave this diff out, say so
            continue
        budget -= len(patch)
        parts.append(f"### {f['filename']} (...)\n```diff\n{patch}\n```")
```

- **Prompts can do work too.** This one fetches the PR's title, author, branches, description and the **diff of every changed file**, so the model starts the review with everything in front of it instead of making several tool calls first.
- **`/pulls/{n}/files`** returns each changed file with a `patch` (the unified diff). It's a list, so we reuse `get_paginated` from step 4.
- **A diff budget** (`MAX_DIFF_CHARS = 40_000`): the same context-window guard as `max_chars` in step 3. Diffs that don't fit are left out **and the prompt says so**, pointing to `get_file_contents` with `ref=<head sha>`, the same idea as `truncated` and `has_more`.
- **`ref=<head sha>`**: the commit at the tip of the PR, so the model reads the code *as changed by the PR*, not as on `main`.
- **`number: int`**: prompt arguments arrive from the client as strings; the SDK converts `"7"` to `7` from the type hint.
- **Why `MCPError`?** For a prompt, the SDK turns any other exception into a generic "Internal server error", hiding our helpful message. `MCPError` is passed through unchanged. `INVALID_PARAMS` (-32602) for 4xx ("you asked for something that doesn't exist") and `INTERNAL_ERROR` (-32603) for 5xx are standard JSON-RPC error codes.

## 4. `create_issue`: a write tool, done carefully

```python
CREATES_DATA = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)


@mcp.tool(annotations=CREATES_DATA)
async def create_issue(
    owner: Owner,
    repo: Repo,
    title: Annotated[str, Field(min_length=1, max_length=256, description="Issue title")],
    ctx: Context,
    body: Annotated[str | None, Field(description="Issue description in Markdown")] = None,
    labels: Annotated[list[str] | None, Field(description="Existing label names ...")] = None,
) -> CreatedIssue:
    """Create a new issue ... Only use it when the user asked for an issue;
    confirm the title and body with them first."""
    if not settings.allow_writes:
        raise ToolError(
            "Creating issues is turned off on this server. To allow it, set "
            "GITHUB_ALLOW_WRITES=true and use a token with Issues write permission."
        )
    payload = {"title": title}  # plus body and labels when given
    data = await _github(ctx).post(f"/repos/{owner}/{repo}/issues", json=payload)
    return CreatedIssue.from_api(data, repository=f"{owner}/{repo}")
```

Five layers of protection, from the outside in:

1. **Least-privilege token.** Your token is read-only, so even if everything else failed, GitHub itself would refuse (403). To really create issues you'd make a separate token with *Issues: Read and write* on chosen repositories only.
2. **Off by default** (`GITHUB_ALLOW_WRITES`). A server that can write should need a deliberate opt-in. `server_status` now reports `writes_enabled`.
3. **Tool annotations.** `read_only_hint=False` tells the host this tool changes things, so hosts like Claude Desktop **ask the user to approve each call** (human in the loop). `destructive_hint=False`: it only adds, never deletes or overwrites. `idempotent_hint=False`: calling it twice makes two issues. **Annotations are hints, not security**: a host may ignore them, which is why layers 1 and 2 exist.
4. **Instructions in the docstring and server instructions**: only create an issue when the user asked, and show them the title and body first. That's the prompt telling the model how to behave.
5. **No blind retries** (next section).

Plus input validation: `title` must be 1 to 256 characters (`min_length`, `max_length` become JSON Schema rules), so an empty title is rejected before any request.

## 5. Why POST is never retried after a 5xx or timeout

In step 5 we retried timeouts and 5xx because GET is **idempotent**. A POST isn't: if GitHub created the issue but the response was lost (timeout) or a proxy returned 502 afterwards, a retry would create a **duplicate issue**. So the retry loop, now `_request(method, url, *, params=None, json=None)`, checks:

```python
idempotent = method == "GET"
...
if not idempotent:
    raise GitHubAPIError(
        error.status_code,
        f"{error} The {method} was not retried because it may already have "
        "succeeded. Check before trying again.",
    ) from error.__cause__
```

The message tells the model to **check first** (for example with `list_issues`) before trying again. Rate-limit waits still apply to POST: a 429 means GitHub rejected the request, so nothing was created and repeating is safe.

Also new in `github_client.py`: `self._http.request(method, url, params=..., json=...)` replaces `self._http.get(...)`, and `json=` makes httpx send a JSON body with the right `Content-Type`.

Interview line: *"Retries are only safe for idempotent requests. For non-idempotent writes, you either use an idempotency key (if the API supports one, like Stripe does) or you don't retry and let the caller check. GitHub's issues API has no idempotency key, so I don't retry."*

## 6. Tests (`tests/test_resources_prompts_and_writes.py`)

| Test | What it checks | Why it's needed |
|---|---|---|
| `test_readme_resource_template_is_listed` | The template URI and `text/markdown` are advertised | Clients can only use resources they can discover |
| `test_readme_resource_returns_decoded_text` | Reading a concrete URI returns the decoded README | The resource happy path |
| `test_missing_readme_is_a_readable_error` | A 404 raises `MCPError` containing "Not found" | Errors must stay readable for resources too |
| `test_prompts_are_listed_with_their_arguments` | Both prompts and their argument names are listed | That's what a host shows the user |
| `test_summarize_repository_prompt_names_the_repo_and_tools` | One user message naming the repo, tools and resource URI | The template is filled in correctly |
| `test_review_pull_request_prompt_loads_description_and_diffs` | Title, author, branches, description, file header, diff and head SHA are in the prompt | The prompt really loads the context |
| `test_review_pull_request_prompt_leaves_out_diffs_over_budget` | With the budget patched to 50 chars, the small diff is in, the huge one is out and counted | The context guard works and is announced |
| `test_review_pull_request_prompt_for_missing_pr_is_a_readable_error` | A 404 gives "Not found", not "Internal server error" | Proves the `MCPError` choice matters |
| `test_create_issue_is_annotated_as_a_non_read_only_tool` | `read_only`, `destructive` and `idempotent` hints are all false | Hosts rely on these to ask for approval |
| `test_create_issue_is_refused_when_writes_are_off` | Clear error and **zero requests** sent | The opt-in switch really blocks writes. **Fails if the check is removed** (I tried) |
| `test_create_issue_posts_title_body_and_labels` | The exact JSON body sent, and the mapped result | Wrong field names would silently drop data |
| `test_create_issue_is_never_retried_after_a_server_error` | 502 → exactly **1** request, "may already have succeeded" | Prevents duplicate issues. **Fails if POST is treated as idempotent** (I tried) |
| `test_create_issue_rejects_an_empty_title` | `title=""` is rejected by the schema | Input validation before any request |

New testing techniques:
- **`monkeypatch.setattr(server.settings, "allow_writes", True)`** flips the switch for one test only; pytest restores it afterwards.
- **`route.calls.last.request.content`** is the raw body httpx sent; `json.loads` turns it back into a dict to compare.
- **`pytest.raises(MCPError, match="Not found")`**: resources and prompts fail by raising, unlike tools, which return `is_error`.

## 7. Try it (PowerShell)

```
uv run pytest
uv run mcp dev src/github_mcp/server.py
```

Expected: `43 passed`. In the Inspector:
- **Resources** tab → **List Templates** → `readme`. Fill in owner `modelcontextprotocol`, repo `python-sdk` and read it. You get the README as text.
- **Prompts** tab → `summarize_repository` with the same owner and repo. You see the message that would go to Claude.
- **Prompts** tab → `review_pull_request`, same repo, with the number of a recent PR (from `list_pull_requests`). You see the description and diffs loaded in.
- **Tools** tab → `create_issue` on any repo. You get "Creating issues is turned off". That's the safety switch working; leave it off.

## 8. Interview questions for this step

1. **What's the difference between tools, resources and prompts?** Tools are actions the model chooses to call and may have side effects. Resources are read-only data with URIs that the application or user attaches. Prompts are templates the user picks, like slash commands.
2. **How do you make a write tool safe?** Least-privilege token, off by default behind a setting, tool annotations so hosts ask the user to approve, instructions to confirm with the user first, input validation, and no blind retries.
3. **Are tool annotations a security boundary?** No, they're hints a host may ignore. Real enforcement is the token's permissions and the server-side switch.
4. **Why not retry a failed POST?** It's not idempotent: the first attempt may have succeeded before the error, so a retry could create a duplicate. Without an idempotency key, I report the failure and tell the model to check first.
5. **Why does `review_pull_request` load the diff itself instead of letting the model call tools?** It saves several round-trips and gives the model the full context up front, with a size budget so a huge PR can't flood the context.
6. **What's a resource template?** A resource URI with placeholders (RFC 6570), like `github://repos/{owner}/{repo}/readme`, so one definition serves every repository.
