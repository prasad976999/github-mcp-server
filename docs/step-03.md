# Step 3: Reading code

Goal: the model can explore a repository's folders and read its files, which is the core of "ask Claude about this codebase".

New tools:
- `list_directory(owner, repo, path="", ref=None)`
- `get_file_contents(owner, repo, path, ref=None, max_chars=20000)`

Changed files: `server.py` (two tools and shared parameter types), `models.py` (three new models), `tests/test_contents.py` (7 new tests, 13 in total).

## 1. The GitHub endpoint

Both tools use one endpoint: `GET /repos/{owner}/{repo}/contents/{path}?ref=...`

- For a **folder**, it returns a JSON **list** of entries.
- For a **file**, it returns a JSON **object** with the content **base64-encoded**.
- `ref` selects a branch, tag or commit. When it's left out, you get the default branch.

So the code checks `isinstance(data, list)` to tell a folder from a file.

## 2. Why two tools instead of one `get_contents`?

We could expose the endpoint as a single tool, but two tools with clear names are easier for the model to use correctly:
- The name says what you get back: a listing or text.
- Each has its own output schema (`DirectoryListing` vs `FileContents`), so the result shape is predictable.
- When the model calls the wrong one, the error tells it which tool to use instead ("'src' is a folder. Use list_directory..."). The model fixes its own mistake on the next call.

Interview line: *"I designed tools around tasks the model does, not around API endpoints, and made error messages point to the right tool."*

## 3. Guarding the context window

A repository can contain huge files. Pasting a 50,000-line file into the model's context is slow, expensive and pushes out more useful information. `get_file_contents` has three guards:

| Case | What happens | Why |
|---|---|---|
| Long text file | Cut off at `max_chars` (default 20,000, allowed range 1,000 to 100,000) and `truncated: true` | Bounded cost; the flag tells the model it hasn't seen everything |
| Binary file (image, zip, compiled) | `is_binary: true`, `content: null` | Base64 or garbled bytes are useless to the model and waste tokens |
| File over 1 MB | Clear tool error | GitHub's contents API doesn't inline files over 1 MB (`encoding: "none"`) |

**Binary detection** (`_decode_text`): a file counts as text if it has no null bytes (`\x00`) and decodes as UTF-8. This is the same simple heuristic git and many editors use.

**Why `truncated` matters:** silently cutting text would let the model think it read the whole file and draw wrong conclusions. Being explicit about partial results is an important habit when building tools for LLMs.

## 4. Smaller details worth knowing

- **Folders first, then files**, alphabetically (`sorted(..., key=lambda e: (e["type"] != "dir", e["name"].lower()))`). The key is a tuple: `False` sorts before `True`, so folders come first. This makes the listing easier for the model to scan, much like a file explorer.
- **`quote(path)`** URL-encodes spaces and special characters but keeps `/`. Without it, a path like `docs/my file.md` would break the request.
- **Shared parameter types** (`Owner`, `Repo`, `Ref`): defined once with their descriptions and reused by every tool. The model sees consistent descriptions everywhere, and we don't repeat ourselves (DRY).
- **Updated server `instructions`** describe the workflow: list first, then read. Server instructions are a good place for guidance that spans several tools.

## 5. Tests (`tests/test_contents.py`)

Each guard has a test:
1. Folders sort before files.
2. `list_directory` on a file returns an error pointing to `get_file_contents`.
3. Text decodes correctly, and `ref` is passed to GitHub.
4. Long files are truncated and flagged.
5. Binary files return no content.
6. `get_file_contents` on a folder returns an error pointing to `list_directory`.
7. Files over 1 MB return a clear error.

## 6. Try it (PowerShell)

```
uv run pytest
uv run mcp dev src/github_mcp/server.py
```

Expected: `13 passed`. Then in the Inspector:
- `list_directory`: owner `modelcontextprotocol`, repo `python-sdk`.
- `list_directory`: same repo, path `src/mcp`.
- `get_file_contents`: same repo, path `README.md`, `max_chars` `2000`. Look for `truncated: true`.
- `get_file_contents`: path `src`. You should get the "is a folder" error.

## 7. Interview questions for this step

1. **How does your server stop a huge file from flooding the model's context?** It truncates at a configurable `max_chars` with an explicit `truncated` flag, skips binary files, and rejects files over GitHub's 1 MB limit with a clear message.
2. **Why tell the model a result was truncated?** So it knows it has partial information and can ask for more or say so to the user, instead of reasoning from an incomplete file as if it were complete.
3. **How do you detect binary files?** Null bytes or invalid UTF-8 mean binary. It's a simple, widely used heuristic.
4. **Why two tools for one API endpoint?** Task-oriented tools with clear names and typed outputs are easier for a model to pick and use; errors redirect it to the right tool.
5. **What is base64 and why does GitHub use it here?** An encoding of arbitrary bytes into safe ASCII text so binary content can travel inside JSON.
6. **What's `ref` for?** It lets the model read code at a specific branch, tag or commit, for example to compare a release with `main` or read the code a PR changes.
