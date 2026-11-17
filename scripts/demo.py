"""A scripted tour of the server, as an MCP client sees it. Good for a live demo.

    uv run python scripts/demo.py                       # starts the server itself over stdio
    uv run python scripts/demo.py --url http://127.0.0.1:8000/mcp   # talks to HTTP mode

For HTTP mode, the bearer token is read from MCP_AUTH_TOKEN. GITHUB_TOKEN (from .env) is
used by the server, never by this script.
"""

import argparse
import asyncio
import json
import os
import sys

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

DEMO_REPO = {"owner": "modelcontextprotocol", "repo": "python-sdk"}


def show(title: str, value: object) -> None:
    print(f"\n=== {title} ===")
    print(value if isinstance(value, str) else json.dumps(value, indent=2, default=str)[:1500])


def connect(url: str | None) -> Client:
    if url is None:
        # stdio: start the server as a child process, exactly as Claude Desktop does.
        return Client(
            StdioServerParameters(command=sys.executable, args=["-m", "github_mcp.server"])
        )
    headers = {}
    if token := os.environ.get("MCP_AUTH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers)))


async def call(client: Client, tool: str, args: dict) -> None:
    result = await client.call_tool(tool, args)
    if result.is_error:
        show(f"{tool} (error, as the model would see it)", result.content[0].text)
    else:
        show(tool, result.structured_content)


async def main(url: str | None) -> None:
    async with connect(url) as client:
        tools = await client.list_tools()
        show("Tools", [t.name for t in tools.tools])
        templates = await client.list_resource_templates()
        show("Resource templates", [t.uri_template for t in templates.resource_templates])
        prompts = await client.list_prompts()
        show("Prompts", [p.name for p in prompts.prompts])

        await call(client, "server_status", {})
        await call(client, "get_rate_limit", {})
        await call(
            client, "search_repositories", {"query": "mcp server language:python", "limit": 3}
        )
        await call(client, "get_repository", DEMO_REPO)
        await call(client, "list_directory", {**DEMO_REPO, "path": ""})
        await call(client, "list_issues", {**DEMO_REPO, "limit": 3})
        # Writes are off by default, so this shows the refusal without touching GitHub.
        await call(client, "create_issue", {**DEMO_REPO, "title": "demo"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="Streamable HTTP endpoint, e.g. http://127.0.0.1:8000/mcp")
    asyncio.run(main(parser.parse_args().url))
