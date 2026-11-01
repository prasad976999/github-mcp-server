"""A small async wrapper around the GitHub REST API.

All HTTP details live here (base URL, auth, headers, timeouts, error mapping), so
tools in server.py only ever deal with Python data and one exception type.
"""

from typing import Any

import httpx

from github_mcp import __version__
from github_mcp.config import Settings


class GitHubAPIError(Exception):
    """A GitHub API call failed. The message is written to be read by the model."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    def __init__(self, settings: Settings):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"github-mcp-server/{__version__}",
        }
        if settings.github_token is not None:
            headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"

        # One AsyncClient for the whole server lifetime: it keeps a pool of
        # TCP/TLS connections open, so repeated calls skip the handshake.
        self._http = httpx.AsyncClient(
            base_url=settings.github_api_url,
            headers=headers,
            timeout=settings.request_timeout_s,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise GitHubAPIError(504, f"GitHub did not respond in time ({path}).") from exc
        except httpx.HTTPError as exc:
            raise GitHubAPIError(502, f"Could not reach GitHub: {exc}") from exc

        if response.is_success:
            return response.json()
        raise GitHubAPIError(response.status_code, _error_message(response))

    async def aclose(self) -> None:
        await self._http.aclose()


def _error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("message", "")
    except ValueError:
        detail = response.text[:200]

    hints = {
        401: "The GitHub token is missing, invalid or expired.",
        403: "Access denied or rate limit reached.",
        404: "Not found. Check the owner and repository names, or the token may lack access.",
        422: "GitHub rejected the request parameters.",
    }
    hint = hints.get(response.status_code, "GitHub returned an error.")
    return f"{hint} (HTTP {response.status_code}: {detail})"
