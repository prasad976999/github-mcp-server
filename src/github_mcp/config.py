"""Settings loaded from environment variables (and a local .env file in development).

Secrets never live in code. In production the MCP host passes GITHUB_TOKEN to this
process as an environment variable; locally we read it from a git-ignored .env file.
"""

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    request_timeout_s: float = Field(default=15.0, gt=0)

    @classmethod
    def from_env(cls) -> "Settings":
        # Real environment variables win over .env (override=False).
        load_dotenv(override=False)
        return cls(
            github_token=os.environ.get("GITHUB_TOKEN") or None,
            github_api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            request_timeout_s=float(os.environ.get("GITHUB_TIMEOUT_S", "15")),
        )
