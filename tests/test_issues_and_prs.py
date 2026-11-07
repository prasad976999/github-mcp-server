import httpx
from mcp import Client

from github_mcp.github_client import MAX_PAGES
from github_mcp.server import mcp

API = "https://api.github.com"


def issue(number: int, *, is_pr: bool = False) -> dict:
    data = {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "user": {"login": "octocat"},
        "labels": [{"name": "bug"}],
        "comments": 2,
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T10:00:00Z",
        "html_url": f"https://github.com/o/r/issues/{number}",
    }
    if is_pr:
        data["pull_request"] = {"url": "..."}
    return data


def pull(number: int) -> dict:
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "open",
        "user": {"login": "octocat"},
        "draft": number % 2 == 0,
        "head": {"ref": f"feature-{number}"},
        "base": {"ref": "main"},
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T10:00:00Z",
        "html_url": f"https://github.com/o/r/pull/{number}",
    }


def next_link(page: int) -> dict:
    return {"Link": f'<{API}/repos/o/r/issues?state=open&per_page=2&page={page}>; rel="next"'}


async def test_list_issues_trims_fields_and_drops_pull_requests(github_api):
    github_api.get("/repos/o/r/issues").respond(
        200, json=[issue(3), issue(2, is_pr=True), issue(1)]
    )

    async with Client(mcp) as client:
        result = await client.call_tool("list_issues", {"owner": "o", "repo": "r"})

    assert result.is_error is False
    data = result.structured_content
    assert [i["number"] for i in data["items"]] == [3, 1]
    assert data["items"][0]["author"] == "octocat"
    assert data["items"][0]["labels"] == ["bug"]
    assert data["has_more"] is False


async def test_list_issues_sends_state_labels_and_newest_first(github_api):
    route = github_api.get("/repos/o/r/issues").respond(200, json=[])

    async with Client(mcp) as client:
        await client.call_tool(
            "list_issues", {"owner": "o", "repo": "r", "state": "closed", "labels": "bug,docs"}
        )

    params = route.calls.last.request.url.params
    assert params["state"] == "closed"
    assert params["labels"] == "bug,docs"
    assert params["sort"] == "created"
    assert params["direction"] == "desc"


async def test_list_issues_follows_link_header_until_limit(github_api):
    pages = {
        None: httpx.Response(200, json=[issue(6), issue(5)], headers=next_link(2)),
        "2": httpx.Response(200, json=[issue(4), issue(3)], headers=next_link(3)),
        "3": httpx.Response(200, json=[issue(2), issue(1)]),
    }
    route = github_api.get("/repos/o/r/issues").mock(
        side_effect=lambda request: pages[request.url.params.get("page")]
    )

    async with Client(mcp) as client:
        result = await client.call_tool("list_issues", {"owner": "o", "repo": "r", "limit": 3})

    data = result.structured_content
    assert [i["number"] for i in data["items"]] == [6, 5, 4]
    assert data["returned"] == 3
    assert data["has_more"] is True
    assert route.call_count == 2  # stopped as soon as it had enough


async def test_pagination_stops_at_max_pages(github_api):
    # A repository that always says "there's another page".
    route = github_api.get("/repos/o/r/issues").mock(
        side_effect=lambda request: httpx.Response(
            200, json=[issue(1)], headers=next_link(int(request.url.params.get("page", 1)) + 1)
        )
    )

    async with Client(mcp) as client:
        result = await client.call_tool("list_issues", {"owner": "o", "repo": "r", "limit": 100})

    assert route.call_count == MAX_PAGES
    assert result.structured_content["has_more"] is True


async def test_list_issues_rejects_unknown_state():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_issues", {"owner": "o", "repo": "r", "state": "merged"}
        )

    assert result.is_error is True


async def test_list_pull_requests_returns_branches_and_draft(github_api):
    route = github_api.get("/repos/o/r/pulls").respond(200, json=[pull(8), pull(7)])

    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_pull_requests", {"owner": "o", "repo": "r", "state": "all", "limit": 5}
        )

    assert result.is_error is False
    first = result.structured_content["items"][0]
    assert first["number"] == 8
    assert first["head"] == "feature-8"
    assert first["base"] == "main"
    assert first["draft"] is True
    assert route.calls.last.request.url.params["state"] == "all"
    assert route.calls.last.request.url.params["per_page"] == "5"


async def test_list_pull_requests_missing_repo_is_a_tool_error(github_api):
    github_api.get("/repos/o/nope/pulls").respond(404, json={"message": "Not Found"})

    async with Client(mcp) as client:
        result = await client.call_tool("list_pull_requests", {"owner": "o", "repo": "nope"})

    assert result.is_error is True
    assert "Not found" in result.content[0].text


async def test_pagination_never_follows_links_to_other_hosts(github_api):
    github_api.get("/repos/o/r/issues").respond(
        200,
        json=[issue(1)],
        headers={"Link": '<https://api.github.com.evil.example/steal?page=2>; rel="next"'},
    )

    async with Client(mcp) as client:
        result = await client.call_tool("list_issues", {"owner": "o", "repo": "r", "limit": 10})

    # respx fails the test on any request to an unmocked host, so reaching here proves
    # the token was never sent to the look-alike host.
    assert result.is_error is False
    assert result.structured_content["returned"] == 1
