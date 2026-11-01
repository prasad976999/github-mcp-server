from mcp import Client

from github_mcp.server import mcp


async def test_server_status_tool_is_listed_and_callable():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert "server_status" in [t.name for t in tools.tools]

        result = await client.call_tool("server_status", {})
        assert result.is_error is False
        assert result.structured_content["version"] == "0.1.0"
