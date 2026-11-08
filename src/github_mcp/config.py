"""Settings loaded from environment variables (and a local .env file in development).

Secrets never live in code. In production the MCP host passes GITHUB_TOKEN to this
process as an environment variable; locally we read it from a git-ignored .env file.
"""

import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    request_timeout_s: float = Field(default=15.0, gt=0)
    # Write tools (create_issue) refuse to run unless this is switched on explicitly.
    allow_writes: bool = False

    # How MCP clients reach this server. "stdio" (the default) is for a client that starts
    # the server itself; "http" serves Streamable HTTP, e.g. from a Docker container.
    transport: Literal["stdio", "http"] = "stdio"
    http_host: str = "127.0.0.1"  # loopback only unless you choose otherwise
    http_port: int = Field(default=8000, ge=1, le=65535)
    # Clients must send "Authorization: Bearer <this>" in HTTP mode. Required for any
    # address other than loopback, because the server acts with your GitHub token.
    auth_token: SecretStr | None = None
    # Extra Host header values to accept in HTTP mode (DNS rebinding protection).
    allowed_hosts: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Settings":
        # Real environment variables win over .env (override=False).
        load_dotenv(override=False)
        return cls(
            github_token=os.environ.get("GITHUB_TOKEN") or None,
            github_api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            request_timeout_s=float(os.environ.get("GITHUB_TIMEOUT_S", "15")),
            allow_writes=os.environ.get("GITHUB_ALLOW_WRITES", "").lower() in {"1", "true", "yes"},
            transport=os.environ.get("MCP_TRANSPORT", "stdio").lower(),
            http_host=os.environ.get("MCP_HOST", "127.0.0.1"),
            http_port=int(os.environ.get("MCP_PORT", "8000")),
            auth_token=os.environ.get("MCP_AUTH_TOKEN") or None,
            allowed_hosts=[
                h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
            ],
        )
