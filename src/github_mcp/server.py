"""Entry point: builds the MCP server and registers its tools."""

import base64
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import quote

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, ToolAnnotations
from pydantic import BaseModel, Field

from github_mcp import __version__
from github_mcp.config import Settings
from github_mcp.github_client import GitHubAPIError, GitHubClient
from github_mcp.models import (
    CreatedIssue,
    DirectoryEntry,
    DirectoryListing,
    FileContents,
    IssueList,
    IssueSummary,
    PullRequestList,
    PullRequestSummary,
    RateLimitStatus,
    RepoSearchResult,
    Repository,
    RepoSummary,
)

# stdio transport uses stdout for protocol messages, so logs must go to stderr.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("github_mcp")

settings = Settings.from_env()


@dataclass
class AppContext:
    github: GitHubClient


@asynccontextmanager
async def lifespan(_server: MCPServer) -> AsyncIterator[AppContext]:
    """Create shared resources once at startup and close them cleanly at shutdown."""
    github = GitHubClient(settings)
    logger.info("GitHub client ready (authenticated=%s)", settings.github_token is not None)
    try:
        yield AppContext(github=github)
    finally:
        await github.aclose()


mcp = MCPServer(
    name="github",
    version=__version__,
    instructions=(
        "Tools for exploring GitHub repositories, issues and pull requests. "
        "Use search_repositories to find repositories, then get_repository for details. "
        "To read code, call list_directory to explore, then get_file_contents for one file. "
        "list_issues and list_pull_requests return the most recent first; has_more=true "
        "means there are more than you were given. "
        "If a tool reports a rate limit, call get_rate_limit and tell the user when it resets "
        "instead of retrying. "
        "A repository's README is also available as the resource "
        "github://repos/{owner}/{repo}/readme. "
        "create_issue changes GitHub: only call it when the user has asked for an issue to be "
        "created, and show them the title and body first."
    ),
    lifespan=lifespan,
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def _github(ctx: Context) -> GitHubClient:
    return ctx.request_context.lifespan_context.github


Owner = Annotated[
    str, Field(description="Account or organisation that owns the repo, e.g. 'pallets'")
]
Repo = Annotated[str, Field(description="Repository name, e.g. 'flask'")]
Ref = Annotated[
    str | None,
    Field(description="Branch, tag or commit SHA. Defaults to the repository's default branch."),
]

State = Annotated[
    Literal["open", "closed", "all"], Field(description="Filter by state. Defaults to open.")
]
Limit = Annotated[int, Field(ge=1, le=100, description="Maximum items to return, newest first")]


class ServerStatus(BaseModel):
    version: str
    github_api_url: str
    authenticated: bool
    writes_enabled: bool


@mcp.tool()
def server_status() -> ServerStatus:
    """Report whether the server is running and whether a GitHub token is configured."""
    return ServerStatus(
        version=__version__,
        github_api_url=settings.github_api_url,
        authenticated=settings.github_token is not None,
        writes_enabled=settings.allow_writes,
    )


@mcp.tool(annotations=READ_ONLY)
async def get_rate_limit(ctx: Context) -> RateLimitStatus:
    """Show how many GitHub API requests are left this hour and when the budget resets.
    Checking it does not use up any requests."""
    try:
        data = await _github(ctx).get("/rate_limit")
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc
    return RateLimitStatus.from_api(data, authenticated=settings.github_token is not None)


@mcp.tool(annotations=READ_ONLY)
async def get_repository(
    owner: Owner,
    repo: Repo,
    ctx: Context,
) -> Repository:
    """Get details of one GitHub repository: description, stars, language, topics, license,
    default branch and open issue count."""
    try:
        data = await _github(ctx).get(f"/repos/{owner}/{repo}")
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc
    return Repository.from_api(data)


@mcp.tool(annotations=READ_ONLY)
async def search_repositories(
    query: Annotated[
        str,
        Field(
            description=(
                "GitHub search syntax. Examples: 'mcp server language:python', "
                "'topic:llm stars:>1000', 'user:anthropics'"
            )
        ),
    ],
    ctx: Context,
    limit: Annotated[int, Field(ge=1, le=30, description="Maximum results to return")] = 10,
) -> RepoSearchResult:
    """Search public GitHub repositories, sorted by best match. Returns a short summary of
    each match; call get_repository for full details of one."""
    try:
        data = await _github(ctx).get(
            "/search/repositories", params={"q": query, "per_page": limit}
        )
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc
    return RepoSearchResult(
        total_count=data["total_count"],
        items=[RepoSummary.from_api(item) for item in data["items"]],
    )


async def _get_contents(ctx: Context, owner: str, repo: str, path: str, ref: str | None):
    # quote() escapes spaces and special characters but keeps "/" between folders.
    path = path.strip("/")
    url = f"/repos/{owner}/{repo}/contents" + (f"/{quote(path)}" if path else "")
    params = {"ref": ref} if ref else None
    try:
        return await _github(ctx).get(url, params=params)
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
async def list_directory(
    owner: Owner,
    repo: Repo,
    ctx: Context,
    path: Annotated[str, Field(description="Folder path; empty for the repository root")] = "",
    ref: Ref = None,
) -> DirectoryListing:
    """List the files and folders at a path in a repository. Use it to explore the
    structure of a codebase before reading individual files with get_file_contents."""
    data = await _get_contents(ctx, owner, repo, path, ref)
    if not isinstance(data, list):
        raise ToolError(f"'{path}' is a file, not a folder. Use get_file_contents to read it.")

    # Folders first, then files, each alphabetically: easier for the model to scan.
    entries = sorted(data, key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return DirectoryListing(
        repository=f"{owner}/{repo}",
        path=path.strip("/") or "/",
        entries=[
            DirectoryEntry(name=e["name"], path=e["path"], type=e["type"], size=e["size"])
            for e in entries
        ],
    )


@mcp.tool(annotations=READ_ONLY)
async def get_file_contents(
    owner: Owner,
    repo: Repo,
    path: Annotated[
        str, Field(description="File path from the repository root, e.g. 'src/app.py'")
    ],
    ctx: Context,
    ref: Ref = None,
    max_chars: Annotated[
        int,
        Field(ge=1_000, le=100_000, description="Cut the file off after this many characters"),
    ] = 20_000,
) -> FileContents:
    """Read the text of one file in a repository. Long files are cut off at max_chars
    (truncated=true tells you this happened). Binary files return no content."""
    data = await _get_contents(ctx, owner, repo, path, ref)
    if isinstance(data, list):
        raise ToolError(f"'{path}' is a folder. Use list_directory to see what's inside.")
    if data.get("type") != "file":
        raise ToolError(f"'{path}' is a {data.get('type')}, not a regular file.")

    result = FileContents(
        repository=f"{owner}/{repo}",
        path=data["path"],
        size=data["size"],
        is_binary=False,
        truncated=False,
        content=None,
    )

    # GitHub only inlines files up to 1 MB; bigger ones come back with encoding "none".
    if data.get("encoding") != "base64":
        raise ToolError(
            f"'{path}' is {data['size']:,} bytes, too large to read through the GitHub API "
            "(1 MB limit)."
        )

    raw = base64.b64decode(data["content"])
    text = _decode_text(raw)
    if text is None:
        result.is_binary = True
        return result

    result.truncated = len(text) > max_chars
    result.content = text[:max_chars]
    return result


@mcp.tool(annotations=READ_ONLY)
async def list_issues(
    owner: Owner,
    repo: Repo,
    ctx: Context,
    state: State = "open",
    labels: Annotated[
        str | None, Field(description="Comma-separated label names, e.g. 'bug,help wanted'")
    ] = None,
    limit: Limit = 20,
) -> IssueList:
    """List issues in a repository, newest first. Pull requests are left out; use
    list_pull_requests for those."""
    params = {"state": state, "sort": "created", "direction": "desc"}
    if labels:
        params["labels"] = labels
    try:
        # GitHub's issues endpoint also returns pull requests (they carry a
        # "pull_request" key), so we filter them out while paging.
        items, has_more = await _github(ctx).get_paginated(
            f"/repos/{owner}/{repo}/issues",
            params,
            max_items=limit,
            keep=lambda item: "pull_request" not in item,
        )
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc
    return IssueList(
        repository=f"{owner}/{repo}",
        state=state,
        returned=len(items),
        has_more=has_more,
        items=[IssueSummary.from_api(item) for item in items],
    )


@mcp.tool(annotations=READ_ONLY)
async def list_pull_requests(
    owner: Owner,
    repo: Repo,
    ctx: Context,
    state: State = "open",
    limit: Limit = 20,
) -> PullRequestList:
    """List pull requests in a repository, newest first, with their branch names and
    draft status."""
    params = {"state": state, "sort": "created", "direction": "desc"}
    try:
        items, has_more = await _github(ctx).get_paginated(
            f"/repos/{owner}/{repo}/pulls", params, max_items=limit
        )
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc
    return PullRequestList(
        repository=f"{owner}/{repo}",
        state=state,
        returned=len(items),
        has_more=has_more,
        items=[PullRequestSummary.from_api(item) for item in items],
    )


# ---------------------------------------------------------------------------
# Step 6: a write tool, a resource and prompts
# ---------------------------------------------------------------------------

# Hints for hosts: this tool changes things (not read-only), but only adds, never
# deletes or overwrites (not destructive), and calling it twice makes two issues
# (not idempotent). Hosts typically ask the user to approve such calls.
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
    labels: Annotated[
        list[str] | None, Field(description="Existing label names to apply, e.g. ['bug']")
    ] = None,
) -> CreatedIssue:
    """Create a new issue in a GitHub repository. This changes GitHub and is visible to
    everyone who can see the repository. Only use it when the user asked for an issue;
    confirm the title and body with them first."""
    if not settings.allow_writes:
        raise ToolError(
            "Creating issues is turned off on this server. To allow it, set "
            "GITHUB_ALLOW_WRITES=true and use a token with Issues write permission."
        )
    payload: dict[str, object] = {"title": title}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = labels
    try:
        data = await _github(ctx).post(f"/repos/{owner}/{repo}/issues", json=payload)
    except GitHubAPIError as exc:
        raise ToolError(str(exc)) from exc
    logger.info("Created issue %s/%s#%s", owner, repo, data.get("number"))
    return CreatedIssue.from_api(data, repository=f"{owner}/{repo}")


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


@mcp.prompt(title="Summarise a repository")
def summarize_repository(owner: str, repo: str) -> str:
    """Get a short overview of a repository: what it does, how it's built, how healthy it is."""
    return (
        f"Give me an overview of the GitHub repository {owner}/{repo} for someone deciding "
        "whether to use it or contribute to it.\n\n"
        f"Use get_repository for the facts, read the README (resource "
        f"github://repos/{owner}/{repo}/readme, or get_file_contents on README.md), "
        "list_directory to see how the code is organised, and list_issues for current "
        "problems.\n\n"
        "Cover: what it does and who it's for, the tech stack, how the code is organised, "
        "how active and healthy the project looks, and how to get started. "
        "Keep it under 300 words."
    )


# Upper bound on diff text put into the review prompt, so a huge PR can't flood the context.
MAX_DIFF_CHARS = 40_000


@mcp.prompt(title="Review a pull request")
async def review_pull_request(owner: str, repo: str, number: int, ctx: Context) -> str:
    """Review a pull request. The PR's description and changed lines are loaded for you."""
    github = _github(ctx)
    try:
        pr = await github.get(f"/repos/{owner}/{repo}/pulls/{number}")
        files, more_files = await github.get_paginated(
            f"/repos/{owner}/{repo}/pulls/{number}/files", max_items=100
        )
    except GitHubAPIError as exc:
        # Prompts have no "isError" result like tools, so failures travel as a protocol
        # error. MCPError keeps our readable message (any other exception is hidden as
        # "Internal server error").
        code = INVALID_PARAMS if exc.status_code < 500 else INTERNAL_ERROR
        raise MCPError(code, str(exc)) from exc

    author = (pr.get("user") or {}).get("login")
    intro = (
        f'Please review pull request #{number} in {owner}/{repo}: "{pr["title"]}" by '
        f"{author}, merging {pr['head']['ref']} into {pr['base']['ref']}."
    )
    parts = [
        intro,
        f"Description:\n{pr.get('body') or '(no description)'}",
        f"Changed files ({len(files)}{'+' if more_files else ''}):",
    ]
    budget = MAX_DIFF_CHARS
    skipped = 0
    for f in files:
        header = f"### {f['filename']} ({f['status']}, +{f['additions']} -{f['deletions']})"
        patch = f.get("patch") or "(no text diff: binary or very large file)"
        if len(patch) > budget:
            skipped += 1
            parts.append(f"{header}\n(diff left out to keep this prompt short)")
            continue
        budget -= len(patch)
        parts.append(f"{header}\n```diff\n{patch}\n```")
    if skipped:
        parts.append(
            f"{skipped} diff(s) were left out. Use get_file_contents with "
            f"ref={pr['head']['sha']} to read those files."
        )
    parts.append(
        "Review for correctness bugs, security problems, missing tests and readability. "
        "Name the file and line for each point. To see more context, use get_file_contents "
        f"with ref={pr['head']['sha']}. End with a verdict: approve, request changes, or "
        "comment."
    )
    return "\n\n".join(parts)


def _decode_text(raw: bytes) -> str | None:
    """Return the bytes as UTF-8 text, or None if they look like a binary file."""
    if b"\x00" in raw:  # text files practically never contain null bytes
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> None:
    logger.info("Starting GitHub MCP server v%s", __version__)
    mcp.run()  # stdio by default


if __name__ == "__main__":
    main()
