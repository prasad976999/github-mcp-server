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
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from github_mcp import __version__
from github_mcp.config import Settings
from github_mcp.github_client import GitHubAPIError, GitHubClient
from github_mcp.models import (
    DirectoryEntry,
    DirectoryListing,
    FileContents,
    IssueList,
    IssueSummary,
    PullRequestList,
    PullRequestSummary,
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
        "means there are more than you were given."
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


@mcp.tool()
def server_status() -> ServerStatus:
    """Report whether the server is running and whether a GitHub token is configured."""
    return ServerStatus(
        version=__version__,
        github_api_url=settings.github_api_url,
        authenticated=settings.github_token is not None,
    )


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
            f"'{path}' is {data['size']:,} bytes, too large to read through the GitHub API (1 MB limit)."
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
