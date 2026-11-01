import base64

from mcp import Client

from github_mcp.server import mcp


def file_response(path: str, data: bytes) -> dict:
    return {
        "type": "file",
        "path": path,
        "size": len(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode(),
    }


async def test_list_directory_puts_folders_first(github_api):
    github_api.get("/repos/pallets/flask/contents").respond(
        200,
        json=[
            {"name": "README.md", "path": "README.md", "type": "file", "size": 900},
            {"name": "src", "path": "src", "type": "dir", "size": 0},
            {"name": "LICENSE", "path": "LICENSE", "type": "file", "size": 1475},
        ],
    )

    async with Client(mcp) as client:
        result = await client.call_tool("list_directory", {"owner": "pallets", "repo": "flask"})

    assert result.is_error is False
    names = [e["name"] for e in result.structured_content["entries"]]
    assert names == ["src", "LICENSE", "README.md"]


async def test_list_directory_on_a_file_points_to_get_file_contents(github_api):
    github_api.get("/repos/pallets/flask/contents/README.md").respond(
        200, json=file_response("README.md", b"# Flask")
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_directory", {"owner": "pallets", "repo": "flask", "path": "README.md"}
        )

    assert result.is_error is True
    assert "get_file_contents" in result.content[0].text


async def test_get_file_contents_decodes_text_and_passes_ref(github_api):
    route = github_api.get("/repos/pallets/flask/contents/src/app.py").respond(
        200, json=file_response("src/app.py", b"print('hello')\n")
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_file_contents",
            {"owner": "pallets", "repo": "flask", "path": "src/app.py", "ref": "v3.0.0"},
        )

    assert result.is_error is False
    assert result.structured_content["content"] == "print('hello')\n"
    assert result.structured_content["truncated"] is False
    assert route.calls.last.request.url.params["ref"] == "v3.0.0"


async def test_get_file_contents_truncates_long_files(github_api):
    github_api.get("/repos/o/r/contents/big.txt").respond(
        200, json=file_response("big.txt", b"a" * 5_000)
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_file_contents", {"owner": "o", "repo": "r", "path": "big.txt", "max_chars": 1_000}
        )

    assert result.structured_content["truncated"] is True
    assert len(result.structured_content["content"]) == 1_000


async def test_get_file_contents_does_not_return_binary_data(github_api):
    github_api.get("/repos/o/r/contents/logo.png").respond(
        200, json=file_response("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00binary")
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_file_contents", {"owner": "o", "repo": "r", "path": "logo.png"}
        )

    assert result.is_error is False
    assert result.structured_content["is_binary"] is True
    assert result.structured_content["content"] is None


async def test_get_file_contents_on_a_folder_points_to_list_directory(github_api):
    github_api.get("/repos/o/r/contents/src").respond(200, json=[])

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_file_contents", {"owner": "o", "repo": "r", "path": "src"}
        )

    assert result.is_error is True
    assert "list_directory" in result.content[0].text


async def test_get_file_contents_reports_files_over_1mb(github_api):
    github_api.get("/repos/o/r/contents/data.csv").respond(
        200,
        json={
            "type": "file",
            "path": "data.csv",
            "size": 5_000_000,
            "encoding": "none",
            "content": "",
        },
    )

    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_file_contents", {"owner": "o", "repo": "r", "path": "data.csv"}
        )

    assert result.is_error is True
    assert "too large" in result.content[0].text
