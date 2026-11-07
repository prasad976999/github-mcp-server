import time

import httpx
from mcp import Client

from github_mcp import github_client
from github_mcp.server import mcp

# A minimal repository as GitHub would send it (only the fields our model reads).
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
    "topics": ["flask"],
    "license": {"spdx_id": "BSD-3-Clause"},
    "private": False,
    "archived": False,
}

FLASK_ARGS = {"owner": "pallets", "repo": "flask"}


async def call_get_repository():
    async with Client(mcp) as client:
        return await client.call_tool("get_repository", FLASK_ARGS)


async def test_server_error_is_retried_then_succeeds(github_api, sleeps):
    route = github_api.get("/repos/pallets/flask")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=FLASK)]

    result = await call_get_repository()

    assert result.is_error is False
    assert route.call_count == 2
    assert len(sleeps) == 1 and 0 <= sleeps[0] <= 0.5


async def test_backoff_doubles_between_attempts(github_api, sleeps, monkeypatch):
    # Make the random jitter always pick its upper bound, so the ceilings are visible.
    monkeypatch.setattr(github_client.random, "uniform", lambda low, high: high)
    route = github_api.get("/repos/pallets/flask")
    route.side_effect = [httpx.Response(502), httpx.Response(502), httpx.Response(200, json=FLASK)]

    result = await call_get_repository()

    assert result.is_error is False
    assert sleeps == [0.5, 1.0]


async def test_gives_up_after_max_attempts(github_api, sleeps):
    route = github_api.get("/repos/pallets/flask").respond(503)

    result = await call_get_repository()

    assert result.is_error is True
    assert route.call_count == github_client.MAX_ATTEMPTS
    assert "Gave up after 3 attempts" in result.content[0].text


async def test_timeout_is_retried(github_api, sleeps):
    route = github_api.get("/repos/pallets/flask")
    route.side_effect = [httpx.ConnectTimeout("slow"), httpx.Response(200, json=FLASK)]

    result = await call_get_repository()

    assert result.is_error is False
    assert route.call_count == 2


async def test_not_found_is_not_retried(github_api, sleeps):
    route = github_api.get("/repos/pallets/flask").respond(404, json={"message": "Not Found"})

    result = await call_get_repository()

    assert result.is_error is True
    assert route.call_count == 1
    assert sleeps == []


async def test_short_retry_after_is_waited_out(github_api, sleeps):
    route = github_api.get("/repos/pallets/flask")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json=FLASK),
    ]

    result = await call_get_repository()

    assert result.is_error is False
    assert sleeps == [2.0]


async def test_exhausted_hourly_limit_is_reported_not_waited(github_api, sleeps):
    reset = int(time.time()) + 30 * 60
    route = github_api.get("/repos/pallets/flask").respond(
        403,
        json={"message": "API rate limit exceeded"},
        headers={
            "X-RateLimit-Limit": "60",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset),
        },
    )

    result = await call_get_repository()

    assert result.is_error is True
    assert route.call_count == 1
    assert sleeps == []
    assert "rate limit reached" in result.content[0].text
    assert "30 minute" in result.content[0].text


async def test_forbidden_without_rate_limit_headers_is_not_retried(github_api, sleeps):
    route = github_api.get("/repos/pallets/flask").respond(403, json={"message": "Forbidden"})

    result = await call_get_repository()

    assert result.is_error is True
    assert route.call_count == 1
    assert sleeps == []
    assert "Access denied" in result.content[0].text


async def test_get_rate_limit_reports_core_budget(github_api):
    github_api.get("/rate_limit").respond(
        200,
        json={
            "resources": {
                "core": {"limit": 5000, "remaining": 4990, "used": 10, "reset": 1794300000},
                "search": {"limit": 30, "remaining": 29, "used": 1, "reset": 1794296460},
            }
        },
    )

    async with Client(mcp) as client:
        result = await client.call_tool("get_rate_limit", {})

    assert result.is_error is False
    data = result.structured_content
    assert (data["limit"], data["remaining"], data["used"]) == (5000, 4990, 10)
    assert data["search_remaining"] == 29
    assert data["resets_at"].startswith("2026-11-10")
