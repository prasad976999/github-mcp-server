import httpx
from mcp import Client

from github_mcp.server import mcp

FLASK = {
    "full_name": "pallets/flask",
    "description": "The Python micro framework for building web applications.",
    "html_url": "https://github.com/pallets/flask",
    "stargazers_count": 69000,
    "language": "Python",
    "updated_at": "2026-10-20T10:00:00Z",
    "default_branch": "main",
    "forks_count": 16000,
    "open_issues_count": 5,
    "topics": ["flask", "python", "wsgi"],
    "license": {"spdx_id": "BSD-3-Clause"},
    "private": False,
    "archived": False,
    "node_id": "fields we don't need are dropped",
}


async def test_get_repository_returns_trimmed_fields(github_api):
    github_api.get("/repos/pallets/flask").respond(200, json=FLASK)

    async with Client(mcp) as client:
        result = await client.call_tool("get_repository", {"owner": "pallets", "repo": "flask"})

    assert result.is_error is False
    repo = result.structured_content
    assert repo["full_name"] == "pallets/flask"
    assert repo["stars"] == 69000
    assert repo["license"] == "BSD-3-Clause"
    assert "node_id" not in repo


async def test_get_repository_not_found_is_a_readable_tool_error(github_api):
    github_api.get("/repos/nobody/nothing").respond(404, json={"message": "Not Found"})

    async with Client(mcp) as client:
        result = await client.call_tool("get_repository", {"owner": "nobody", "repo": "nothing"})

    assert result.is_error is True
    assert "Not found" in result.content[0].text


async def test_search_repositories_passes_query_and_limit(github_api):
    route = github_api.get("/search/repositories").respond(
        200, json={"total_count": 1234, "items": [FLASK]}
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "search_repositories", {"query": "web framework language:python", "limit": 5}
        )

    assert result.is_error is False
    assert result.structured_content["total_count"] == 1234
    assert result.structured_content["items"][0]["full_name"] == "pallets/flask"
    params = route.calls.last.request.url.params
    assert params["q"] == "web framework language:python"
    assert params["per_page"] == "5"


async def test_search_repositories_rejects_limit_over_30():
    async with Client(mcp) as client:
        result = await client.call_tool("search_repositories", {"query": "x", "limit": 500})

    assert result.is_error is True


async def test_timeout_becomes_a_tool_error(github_api):
    github_api.get("/repos/pallets/flask").mock(side_effect=httpx.ConnectTimeout("slow"))

    async with Client(mcp) as client:
        result = await client.call_tool("get_repository", {"owner": "pallets", "repo": "flask"})

    assert result.is_error is True
    assert "did not respond in time" in result.content[0].text
