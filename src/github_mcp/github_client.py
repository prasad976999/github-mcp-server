"""A small async wrapper around the GitHub REST API.

All HTTP details live here (base URL, auth, headers, timeouts, error mapping), so
tools in server.py only ever deal with Python data and one exception type.
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from github_mcp import __version__
from github_mcp.config import Settings

# Hard stop on how many pages one tool call may fetch, whatever the model asks for.
MAX_PAGES = 5

# Retries: only for failures that may succeed on a second try (network, timeouts, 5xx).
MAX_ATTEMPTS = 3  # the first try plus two retries
BASE_DELAY_S = 0.5  # backoff ceiling doubles each time: 0.5s, then 1s
RETRYABLE_STATUS = {500, 502, 503, 504}

# A tool call should never hang for minutes. Longer rate-limit waits are reported instead.
MAX_WAIT_S = 10.0

logger = logging.getLogger("github_mcp.github_client")

# Indirection so tests can replace sleeping with a recorder and run instantly.
_sleep = asyncio.sleep


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
        self._authenticated = settings.github_token is not None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._get_response(path, params)
        return response.json()

    async def get_paginated(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        max_items: int,
        keep: Callable[[dict[str, Any]], bool] = lambda item: True,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Collect up to max_items from a list endpoint, following GitHub's Link headers.

        Returns the items and whether more exist beyond what we returned. `keep` filters
        items as they arrive (e.g. dropping pull requests from the issues endpoint).
        """
        url: str | None = path
        query = {**(params or {}), "per_page": min(100, max(max_items, 1))}
        items: list[dict[str, Any]] = []

        for _ in range(MAX_PAGES):
            response = await self._get_response(url, query)
            items.extend(item for item in response.json() if keep(item))
            url = response.links.get("next", {}).get("url")
            # Our token is sent with every request, so only follow links back to GitHub.
            if url is not None and not url.startswith(str(self._http.base_url).rstrip("/") + "/"):
                url = None
            # The "next" URL already carries every query parameter.
            query = None
            if url is None or len(items) >= max_items:
                break

        has_more = len(items) > max_items or url is not None
        return items[:max_items], has_more

    async def _get_response(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        """GET with retries. Returns a successful response or raises GitHubAPIError.

        Retried: timeouts, network errors and 5xx (GET is idempotent, so a repeat is safe).
        Rate limits: wait if GitHub asks for a short pause, otherwise explain and stop.
        Not retried: other 4xx errors, because the same request would fail the same way.
        """
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._http.get(url, params=params)
            except httpx.TimeoutException as exc:
                error = GitHubAPIError(504, f"GitHub did not respond in time ({url}).")
                error.__cause__ = exc
            except httpx.HTTPError as exc:
                error = GitHubAPIError(502, f"Could not reach GitHub: {exc}")
                error.__cause__ = exc
            else:
                if response.is_success:
                    return response

                wait = _rate_limit_wait(response)
                if wait is not None:
                    if wait > MAX_WAIT_S or attempt == MAX_ATTEMPTS:
                        raise GitHubAPIError(response.status_code, self._rate_limit_message(wait))
                    logger.warning("Rate limited by GitHub; waiting %.1fs before retrying", wait)
                    await _sleep(wait)
                    continue

                error = GitHubAPIError(response.status_code, _error_message(response))
                if response.status_code not in RETRYABLE_STATUS:
                    raise error

            if attempt == MAX_ATTEMPTS:
                raise GitHubAPIError(
                    error.status_code, f"{error} Gave up after {MAX_ATTEMPTS} attempts."
                ) from error.__cause__

            # Exponential backoff with full jitter: a random wait up to 0.5s, then up to 1s.
            # The randomness stops many clients retrying at the same instant.
            delay = random.uniform(0, BASE_DELAY_S * 2 ** (attempt - 1))
            logger.warning("Attempt %d failed (%s); retrying in %.2fs", attempt, error, delay)
            await _sleep(delay)

        raise AssertionError("unreachable")  # the loop always returns or raises

    def _rate_limit_message(self, wait_s: float) -> str:
        minutes = max(1, round(wait_s / 60))
        message = (
            f"GitHub rate limit reached. It resets in about {minutes} minute(s). "
            "Retrying now will not help; tell the user and try again later."
        )
        if not self._authenticated:
            message += " Adding a GITHUB_TOKEN raises the limit from 60 to 5,000 requests/hour."
        return message

    async def aclose(self) -> None:
        await self._http.aclose()


def _rate_limit_wait(response: httpx.Response) -> float | None:
    """Seconds GitHub wants us to wait, or None if this error is not a rate limit."""
    if response.status_code not in (403, 429):
        return None
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:  # secondary rate limit: GitHub says exactly how long
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return 60.0
    if response.headers.get("x-ratelimit-remaining") == "0":  # hourly budget used up
        try:
            return max(0.0, int(response.headers["x-ratelimit-reset"]) - time.time())
        except (KeyError, ValueError):
            return 60.0
    if response.status_code == 429:  # no hint given; GitHub's docs say wait a minute
        return 60.0
    return None  # a 403 without rate-limit headers is a permissions problem


def _error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("message", "")
    except ValueError:
        detail = response.text[:200]

    hints = {
        401: "The GitHub token is missing, invalid or expired.",
        403: "Access denied. The token may not have permission for this.",
        404: "Not found. Check the owner and repository names, or the token may lack access.",
        422: "GitHub rejected the request parameters.",
        500: "GitHub had an internal error.",
        502: "GitHub is temporarily unavailable.",
        503: "GitHub is temporarily unavailable.",
        504: "GitHub timed out.",
    }
    hint = hints.get(response.status_code, "GitHub returned an error.")
    return f"{hint} (HTTP {response.status_code}: {detail})"
