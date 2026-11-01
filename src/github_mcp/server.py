"""Entry point: builds the MCP server and registers its tools."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from github_mcp import __version__
from github_mcp.config import Settings
from github_mcp.github_client import GitHubAPIError, GitHubClient
from github_mcp.models import RepoSearchResult, Repository, RepoSummary

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
        "Use search_repositories to find repositories, then get_repository for details."
    ),
    lifespan=lifespan,
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def _github(ctx: Context) -> GitHubClient:
    return ctx.request_context.lifespan_context.github


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
    owner: Annotated[
        str, Field(description="Account or organisation that owns the repo, e.g. 'pallets'")
    ],
    repo: Annotated[str, Field(description="Repository name, e.g. 'flask'")],
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


def main() -> None:
    logger.info("Starting GitHub MCP server v%s", __version__)
    mcp.run()  # stdio by default


if __name__ == "__main__":
    main()
