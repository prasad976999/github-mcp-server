# Step 4: Issues, pull requests and pagination

Goal: the model can see what's happening in a repository (open bugs, feature requests, pull requests in review), and the server can safely collect results that span several pages.

New tools:
- `list_issues(owner, repo, state="open", labels=None, limit=20)`
- `list_pull_requests(owner, repo, state="open", limit=20)`

Changed files: `github_client.py` (new `get_paginated`), `models.py` (four new models), `server.py` (two tools, shared `State` and `Limit` types), `tests/test_issues_and_prs.py` (8 new tests, 21 in total).

## 1. What pagination is and why it matters

APIs don't return thousands of items at once. They split results into **pages**. GitHub returns at most 100 items per page (`per_page`), and tells you where the next page is in a **`Link` response header**:

```
Link: <https://api.github.com/repos/o/r/issues?page=2&per_page=20>; rel="next",
      <https://api.github.com/repos/o/r/issues?page=9&per_page=20>; rel="last"
```

httpx parses this for us: `response.links["next"]["url"]`.

**Offset vs cursor pagination** (a common interview question):
- **Offset/page-number** (`?page=3`): simple and lets you jump to any page, but if items are added while you're paging, you can see duplicates or miss items.
- **Cursor** (`?after=abc123`): the server gives an opaque pointer to "where you got to". Stable under changes and efficient for huge datasets, but you can only go forwards.
- GitHub uses page numbers on most REST endpoints and cursors on some (and on GraphQL). **By following the `Link` header instead of building URLs ourselves, our code works with either**: we just follow whatever "next" GitHub gives us.

## 2. `get_paginated` in `github_client.py`

```python
MAX_PAGES = 5

async def get_paginated(self, path, params=None, *, max_items, keep=lambda item: True):
    url = path
    query = {**(params or {}), "per_page": min(100, max(max_items, 1))}
    items = []

    for _ in range(MAX_PAGES):
        response = await self._get_response(url, query)
        items.extend(item for item in response.json() if keep(item))
        url = response.links.get("next", {}).get("url")
        if url is not None and not url.startswith(str(self._http.base_url).rstrip("/") + "/"):
            url = None
        query = None
        if url is None or len(items) >= max_items:
            break

    has_more = len(items) > max_items or url is not None
    return items[:max_items], has_more
```

Line by line:
- **`MAX_PAGES = 5`**: a hard ceiling on requests per tool call. Even if the model asks for a lot, one call can never make more than 5 requests. This bounds latency, rate-limit usage and cost.
- **`*,`**: everything after it must be passed by name (`max_items=20`), which makes calls self-explanatory.
- **`keep`**: an optional filter function applied as items arrive. `list_issues` uses it to drop pull requests (see below). The default keeps everything.
- **`per_page = min(100, max_items)`**: ask for only as many as we need, up to GitHub's maximum of 100. Fewer, smaller requests.
- **`for _ in range(MAX_PAGES)`**: a bounded loop. `while True` with a "next" link could loop for a very long time on a huge repository.
- **`response.links.get("next", {}).get("url")`**: the next page's URL, or `None` on the last page.
- **Same-host check**: our client sends the token on every request. Following a "next" link to another host would leak it, so we only follow links that start with `https://api.github.com/`. The trailing `/` matters: without it, a look-alike host such as `api.github.com.evil.example` would pass. **There's a test for exactly that case.**
- **`query = None`**: the "next" URL already includes every parameter, so we don't send them twice.
- **Stop early** once we have enough items: no wasted requests.
- **`has_more`**: true if we cut items off or GitHub still has a "next" page. **The model is told the list is partial**, the same principle as `truncated` in step 3.
- **`items[:max_items]`**: never return more than asked.

`get()` and `get_paginated()` now share `_get_response()`, which holds the error handling in one place.

## 3. The tools in `server.py`

```python
State = Annotated[Literal["open", "closed", "all"], Field(description="Filter by state. Defaults to open.")]
Limit = Annotated[int, Field(ge=1, le=100, description="Maximum items to return, newest first")]
```

- **`Literal["open", "closed", "all"]`**: the JSON Schema becomes an **enum**, so the model sees exactly which values are allowed, and anything else (like `"merged"`) is rejected before our code runs.
- **`Limit` 1–100, default 20**: sensible by default, never unlimited.

### `list_issues`

```python
params = {"state": state, "sort": "created", "direction": "desc"}
if labels:
    params["labels"] = labels
items, has_more = await _github(ctx).get_paginated(
    f"/repos/{owner}/{repo}/issues", params, max_items=limit,
    keep=lambda item: "pull_request" not in item,
)
```

- **Newest first** (`sort=created`, `direction=desc`): usually what a person asking about a project wants, and stated in the docstring so the model knows.
- **`labels`**: GitHub takes a comma-separated list, e.g. `bug,help wanted`.
- **Why filter out pull requests?** In GitHub's data model **every pull request is also an issue**, so `/issues` returns both. Pull requests carry a `pull_request` key. Mixing them would confuse the model and waste its limit, so we drop them, and the docstring points to `list_pull_requests`.

### `list_pull_requests`

Same pattern on `/repos/{owner}/{repo}/pulls`. Each item includes **`head`** (the branch with the changes) and **`base`** (the branch it merges into), plus **`draft`**. That's what you need to talk about a PR's status.

## 4. Models

`IssueSummary` and `PullRequestSummary` keep about 10 fields each (GitHub sends around 60 to 80). `author` comes from `user.login`, with `(data.get("user") or {})` guarding against deleted accounts (GitHub sends `null`). `IssueList` and `PullRequestList` add `returned` and `has_more`.

## 5. Tests (`tests/test_issues_and_prs.py`)

| Test | What it checks | Why it's needed |
|---|---|---|
| `test_list_issues_trims_fields_and_drops_pull_requests` | PRs are removed; author and labels mapped | Proves the GitHub quirk is handled |
| `test_list_issues_sends_state_labels_and_newest_first` | `state`, `labels`, `sort`, `direction` reach GitHub | Wrong parameter names would silently give wrong results |
| `test_list_issues_follows_link_header_until_limit` | Follows `Link` across pages and **stops after 2 requests** once it has 3 items; `has_more` is true | The core pagination behaviour, and no wasted requests |
| `test_pagination_stops_at_max_pages` | A repo that always has another page gets exactly 5 requests | Proves the safety ceiling works |
| `test_list_issues_rejects_unknown_state` | `state="merged"` is rejected | Proves the enum validation |
| `test_list_pull_requests_returns_branches_and_draft` | `head`, `base`, `draft`, and `state`/`per_page` sent | The PR happy path |
| `test_list_pull_requests_missing_repo_is_a_tool_error` | 404 becomes a readable error | Error path for the new tool |
| `test_pagination_never_follows_links_to_other_hosts` | A "next" link to `api.github.com.evil.example` is not followed | Security: the token must never go to another host. **I checked this test fails if the trailing `/` is removed from the check.** |

**Simulating pages:** respx's `side_effect` takes a function that looks at the request's `page` parameter and returns the matching fake response with its own `Link` header.

## 6. Try it (PowerShell)

```
uv run pytest
uv run mcp dev src/github_mcp/server.py
```

Expected: `21 passed`. In the Inspector, with owner `modelcontextprotocol` and repo `python-sdk`:
- `list_issues` with limit `5`. You should get 5 issues with `has_more: true`.
- `list_issues` with labels `bug`.
- `list_pull_requests` with state `all` and limit `3`. Look at `head`, `base` and `draft`.
- `list_issues` with state `merged`. It should be rejected.

## 7. Interview questions for this step

1. **How do you handle pagination?** Follow GitHub's `Link` header (`rel="next"`) until I have enough items, with a hard cap of 5 pages per call, and report `has_more` so the model knows the list is partial.
2. **Offset vs cursor pagination?** Offset is simple and allows jumping, but can skip or duplicate items when data changes. Cursor is stable and efficient but forward-only. Following `Link` headers works with both.
3. **Why cap pages for an LLM caller?** A model can ask for far more than it needs. A cap bounds latency, rate-limit usage and context size, whatever the model requests.
4. **Why does your issues tool drop pull requests?** GitHub treats every PR as an issue, so `/issues` returns both. I filter on the `pull_request` key and point the model to `list_pull_requests`.
5. **What's the security risk in following pagination links?** The client sends the token with every request. A "next" URL to another host would leak it, so I only follow URLs under `https://api.github.com/`, and a test checks a look-alike host is refused.
6. **Why `Literal` for `state`?** It becomes an enum in the JSON Schema: the model sees the allowed values and invalid ones are rejected automatically.
