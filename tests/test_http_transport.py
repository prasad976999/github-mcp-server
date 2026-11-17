"""Step 8: the Streamable HTTP mode and its three guards (loopback, bearer token, Host check)."""

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from github_mcp import server
from github_mcp.config import Settings
from github_mcp.http_app import build_app

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def http_client(**settings) -> TestClient:
    # TestClient runs the app in-process (no real port) and runs its startup and shutdown.
    return TestClient(build_app(Settings(**settings)), base_url="http://localhost:8000")


def test_tools_are_served_over_http_on_loopback():
    with http_client() as client:
        response = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS)
    assert response.status_code == 200
    names = [t["name"] for t in response.json()["result"]["tools"]]
    assert {"server_status", "search_repositories", "create_issue"} <= set(names)


def test_tool_call_over_http_returns_structured_result():
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}
    call["params"] = {"name": "server_status", "arguments": {}}
    with http_client() as client:
        response = client.post("/mcp", json=call, headers=MCP_HEADERS)
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["version"] == "0.1.0"


def test_missing_or_wrong_bearer_token_is_rejected():
    with http_client(auth_token=SecretStr("s3cret")) as client:
        missing = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS)
        wrong = client.post(
            "/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, "Authorization": "Bearer guess"}
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_correct_bearer_token_is_accepted():
    with http_client(auth_token=SecretStr("s3cret")) as client:
        response = client.post(
            "/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, "Authorization": "Bearer s3cret"}
        )
    assert response.status_code == 200


def test_health_check_needs_no_token():
    with http_client(auth_token=SecretStr("s3cret")) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_unknown_host_header_is_refused():
    """DNS rebinding protection: a request addressed to another name is refused."""
    with http_client() as client:
        response = client.post(
            "/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, "Host": "evil.example"}
        )
    assert response.status_code == 421


def test_extra_allowed_host_is_accepted():
    with http_client(allowed_hosts=["mcp.internal:*"]) as client:
        response = client.post(
            "/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, "Host": "mcp.internal:8000"}
        )
    assert response.status_code == 200


def test_refuses_public_address_without_auth_token():
    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
        build_app(Settings(http_host="0.0.0.0"))


def test_public_address_is_allowed_with_auth_token():
    build_app(Settings(http_host="0.0.0.0", auth_token=SecretStr("s3cret")))


def test_http_settings_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "HTTP")
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_PORT", "9000")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.internal:*, other:8000")
    settings = Settings.from_env()
    assert settings.transport == "http"
    assert (settings.http_host, settings.http_port) == ("0.0.0.0", 9000)
    assert settings.auth_token.get_secret_value() == "s3cret"
    assert settings.allowed_hosts == ["mcp.internal:*", "other:8000"]


def test_defaults_are_stdio_on_loopback_without_token():
    settings = Settings()
    assert (settings.transport, settings.http_host, settings.auth_token) == (
        "stdio",
        "127.0.0.1",
        None,
    )


def test_main_picks_the_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("stdio"))
    monkeypatch.setattr("github_mcp.http_app.serve", lambda s: calls.append("http"))

    monkeypatch.setattr(server, "settings", Settings(transport="stdio"))
    server.main()
    monkeypatch.setattr(server, "settings", Settings(transport="http"))
    server.main()
    assert calls == ["stdio", "http"]
