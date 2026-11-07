import pytest
import respx

from github_mcp import github_client
from github_mcp.server import settings


@pytest.fixture
def github_api():
    """Intercept every HTTP call to the GitHub API; unmatched calls fail the test."""
    with respx.mock(base_url=settings.github_api_url, assert_all_called=False) as router:
        yield router


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Replace real waiting with a list of the delays asked for, so retry tests run instantly."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(github_client, "_sleep", fake_sleep)
    return delays
