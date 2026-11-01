import pytest
import respx

from github_mcp.server import settings


@pytest.fixture
def github_api():
    """Intercept every HTTP call to the GitHub API; unmatched calls fail the test."""
    with respx.mock(base_url=settings.github_api_url, assert_all_called=False) as router:
        yield router
