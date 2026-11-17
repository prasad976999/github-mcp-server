"""Streamable HTTP mode: the same MCP server, reachable over the network.

stdio is enough when the MCP client starts the server itself (Claude Desktop, Claude Code).
HTTP is for running it as a service, for example in a Docker container. That raises
security questions stdio never has, because anyone who can reach the port can use your
GitHub token through it. So this module adds three guards:

1. Loopback by default: it listens on 127.0.0.1 unless told otherwise.
2. A bearer token (MCP_AUTH_TOKEN), required before it will listen on any other address.
3. DNS rebinding protection: requests whose Host header isn't on the allow list are refused,
   so a web page in your browser can't talk to the server through a hostile domain name.
"""

import hmac
import json
import logging

from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from github_mcp.config import Settings
from github_mcp.server import mcp

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
PUBLIC_PATHS = {"/health"}  # reachable without the bearer token


class BearerTokenMiddleware:
    """Reject HTTP requests that don't carry "Authorization: Bearer <token>".

    Written as plain ASGI (a callable taking scope, receive, send) so it wraps any app.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(b"authorization", b"")
        # compare_digest takes the same time whether the first or last byte differs,
        # so an attacker can't guess the token one character at a time by timing replies.
        if hmac.compare_digest(supplied, self._expected):
            await self.app(scope, receive, send)
            return
        body = json.dumps({"error": "Missing or wrong bearer token."}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_app(settings: Settings) -> ASGIApp:
    """Build the HTTP app, refusing unsafe combinations of settings."""
    if settings.http_host not in LOOPBACK_HOSTS and settings.auth_token is None:
        raise RuntimeError(
            f"Refusing to listen on {settings.http_host} without MCP_AUTH_TOKEN: anyone who "
            "can reach this address could use your GitHub token. Set MCP_AUTH_TOKEN, or use "
            "MCP_HOST=127.0.0.1."
        )
    allowed_hosts = DEFAULT_ALLOWED_HOSTS + settings.allowed_hosts
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=[f"http://{h}" for h in allowed_hosts],
    )
    app = mcp.streamable_http_app(
        # Stateless: every request stands alone, so any copy of the server can answer it
        # and nothing is lost on restart. This server keeps no per-session state anyway.
        stateless_http=True,
        # Plain JSON replies instead of an event stream: simpler to call and to debug.
        json_response=True,
        transport_security=security,
        host=settings.http_host,
    )
    if settings.auth_token is None:
        logger.warning("HTTP mode without MCP_AUTH_TOKEN: only safe on 127.0.0.1")
        return app
    return BearerTokenMiddleware(app, settings.auth_token.get_secret_value())


def serve(settings: Settings) -> None:  # pragma: no cover - starts a real network server
    import uvicorn

    try:
        app = build_app(settings)
    except RuntimeError as exc:
        logger.error("%s", exc)  # a clear one-line reason instead of a traceback
        raise SystemExit(1) from None
    logger.info("Serving MCP on http://%s:%d/mcp", settings.http_host, settings.http_port)
    uvicorn.run(app, host=settings.http_host, port=settings.http_port, log_level="info")
