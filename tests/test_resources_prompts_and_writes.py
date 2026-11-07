import base64
import json

import httpx
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from github_mcp import server
from github_mcp.server import mcp


def encoded(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# --- Resource -----------------------------------------------------------------


async def test_readme_resource_template_is_listed():
    async with Client(mcp) as client:
        result = await client.list_resource_templates()

    templates = {t.uri_template: t for t in result.resource_templates}
    assert "github://repos/{owner}/{repo}/readme" in templates
    assert templates["github://repos/{owner}/{repo}/readme"].mime_type == "text/markdown"


async def test_readme_resource_returns_decoded_text(github_api):
    github_api.get("/repos/pallets/flask/readme").respond(
        200, json={"content": encoded("# Flask\nA micro framework.")}
    )

    async with Client(mcp) as client:
        result = await client.read_resource("github://repos/pallets/flask/readme")

    assert result.contents[0].text == "# Flask\nA micro framework."


async def test_missing_readme_is_a_readable_error(github_api):
    github_api.get("/repos/pallets/nothing/readme").respond(404, json={"message": "Not Found"})

    async with Client(mcp) as client:
        with pytest.raises(MCPError, match="Not found"):
            await client.read_resource("github://repos/pallets/nothing/readme")


# --- Prompts ------------------------------------------------------------------


async def test_prompts_are_listed_with_their_arguments():
    async with Client(mcp) as client:
        result = await client.list_prompts()

    prompts = {p.name: [a.name for a in p.arguments] for p in result.prompts}
    assert prompts["summarize_repository"] == ["owner", "repo"]
    assert prompts["review_pull_request"] == ["owner", "repo", "number"]


async def test_summarize_repository_prompt_names_the_repo_and_tools():
    async with Client(mcp) as client:
        result = await client.get_prompt("summarize_repository", {"owner": "a", "repo": "b"})

    text = result.messages[0].content.text
    assert result.messages[0].role == "user"
    assert "a/b" in text
    assert "get_repository" in text and "github://repos/a/b/readme" in text


PR = {
    "title": "Fix crash on empty config",
    "user": {"login": "octocat"},
    "body": "Closes #12.",
    "head": {"ref": "fix-empty-config", "sha": "abc123"},
    "base": {"ref": "main"},
}


async def test_review_pull_request_prompt_loads_description_and_diffs(github_api):
    github_api.get("/repos/a/b/pulls/7").respond(200, json=PR)
    github_api.get("/repos/a/b/pulls/7/files").respond(
        200,
        json=[
            {
                "filename": "app/config.py",
                "status": "modified",
                "additions": 2,
                "deletions": 1,
                "patch": "@@ -1 +1,2 @@\n-x = load()\n+x = load() or {}",
            }
        ],
    )

    async with Client(mcp) as client:
        result = await client.get_prompt(
            "review_pull_request", {"owner": "a", "repo": "b", "number": "7"}
        )

    text = result.messages[0].content.text
    assert '"Fix crash on empty config" by octocat' in text
    assert "fix-empty-config into main" in text
    assert "Closes #12." in text
    assert "### app/config.py (modified, +2 -1)" in text
    assert "+x = load() or {}" in text
    assert "ref=abc123" in text


async def test_review_pull_request_prompt_leaves_out_diffs_over_budget(github_api, monkeypatch):
    monkeypatch.setattr(server, "MAX_DIFF_CHARS", 50)
    github_api.get("/repos/a/b/pulls/7").respond(200, json=PR)
    github_api.get("/repos/a/b/pulls/7/files").respond(
        200,
        json=[
            {
                "filename": "small.py",
                "status": "added",
                "additions": 1,
                "deletions": 0,
                "patch": "+print('hi')",
            },
            {
                "filename": "huge.py",
                "status": "modified",
                "additions": 900,
                "deletions": 0,
                "patch": "+" + "x" * 500,
            },
        ],
    )

    async with Client(mcp) as client:
        result = await client.get_prompt(
            "review_pull_request", {"owner": "a", "repo": "b", "number": "7"}
        )

    text = result.messages[0].content.text
    assert "+print('hi')" in text
    assert "x" * 500 not in text
    assert "1 diff(s) were left out" in text


async def test_review_pull_request_prompt_for_missing_pr_is_a_readable_error(github_api):
    github_api.get("/repos/a/b/pulls/999").respond(404, json={"message": "Not Found"})

    async with Client(mcp) as client:
        with pytest.raises(MCPError, match="Not found"):
            await client.get_prompt(
                "review_pull_request", {"owner": "a", "repo": "b", "number": "999"}
            )


# --- Write tool ---------------------------------------------------------------

ISSUE_ARGS = {
    "owner": "a",
    "repo": "b",
    "title": "Docs typo",
    "body": "In README.",
    "labels": ["docs"],
}


async def test_create_issue_is_annotated_as_a_non_read_only_tool():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    hints = tools["create_issue"].annotations
    assert hints.read_only_hint is False
    assert hints.destructive_hint is False
    assert hints.idempotent_hint is False


async def test_create_issue_is_refused_when_writes_are_off(github_api, monkeypatch):
    monkeypatch.setattr(server.settings, "allow_writes", False)
    route = github_api.post("/repos/a/b/issues")

    async with Client(mcp) as client:
        result = await client.call_tool("create_issue", ISSUE_ARGS)

    assert result.is_error is True
    assert "GITHUB_ALLOW_WRITES" in result.content[0].text
    assert route.call_count == 0


async def test_create_issue_posts_title_body_and_labels(github_api, monkeypatch):
    monkeypatch.setattr(server.settings, "allow_writes", True)
    route = github_api.post("/repos/a/b/issues").respond(
        201,
        json={"number": 42, "title": "Docs typo", "html_url": "https://github.com/a/b/issues/42"},
    )

    async with Client(mcp) as client:
        result = await client.call_tool("create_issue", ISSUE_ARGS)

    assert result.is_error is False
    assert json.loads(route.calls.last.request.content) == {
        "title": "Docs typo",
        "body": "In README.",
        "labels": ["docs"],
    }
    assert result.structured_content == {
        "repository": "a/b",
        "number": 42,
        "title": "Docs typo",
        "url": "https://github.com/a/b/issues/42",
    }


async def test_create_issue_is_never_retried_after_a_server_error(github_api, monkeypatch):
    monkeypatch.setattr(server.settings, "allow_writes", True)
    route = github_api.post("/repos/a/b/issues").mock(
        side_effect=[httpx.Response(502), httpx.Response(201, json={})]
    )

    async with Client(mcp) as client:
        result = await client.call_tool("create_issue", ISSUE_ARGS)

    assert result.is_error is True
    assert route.call_count == 1
    assert "may already have succeeded" in result.content[0].text


async def test_create_issue_rejects_an_empty_title(github_api, monkeypatch):
    monkeypatch.setattr(server.settings, "allow_writes", True)

    async with Client(mcp) as client:
        result = await client.call_tool("create_issue", {**ISSUE_ARGS, "title": ""})

    assert result.is_error is True
