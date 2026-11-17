"""Build the interactive study guide (one self-contained HTML file).

Usage: python3 build_site.py <project_dir> <qa.json> <out.html>

Sources: docs/STUDY-GUIDE.md (split into parts), docs/step-NN.md, the real source
files, and qa.json (flashcards). Markdown is converted with pandoc.
"""

import html
import json
import re
import subprocess
import sys
from pathlib import Path

project = Path(sys.argv[1])
qa = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
out = Path(sys.argv[3])
here = Path(__file__).parent


def md(text: str, prefix: str) -> str:
    """Markdown -> HTML fragment, with ids prefixed so documents can't collide."""
    return subprocess.run(
        [
            "pandoc",
            "-f",
            "markdown-smart",
            "-t",
            "html",
            f"--id-prefix={prefix}-",
            "--highlight-style=pygments",
            "--wrap=none",
        ],
        input=text,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def code_html(text: str, lang: str, prefix: str) -> str:
    fence = "~~~~~~~~"
    return md(f"{fence} {{.{lang}}}\n{text}\n{fence}\n", prefix)


guide = (project / "docs/STUDY-GUIDE.md").read_text(encoding="utf-8")
guide = re.sub(r"^---\n.*?\n---\n", "", guide, flags=re.S)
parts = {}
for chunk in re.split(r"\n(?=# (?:Part \d+b?\.|How to use))", "\n" + guide):
    chunk = chunk.strip()
    if chunk:
        title = chunk.split("\n", 1)[0].lstrip("# ").strip()
        parts[title] = chunk.split("\n", 1)[1] if "\n" in chunk else ""


def part(prefix_title: str) -> tuple[str, str]:
    for t, body in parts.items():
        if t.startswith(prefix_title):
            return t, body
    raise KeyError(prefix_title)


# ---- Overview ---------------------------------------------------------------
_, p1 = part("Part 1.")
_, howto = part("How to use")
progress = howto[howto.index("| Step |") :].strip()
p1_sections = re.split(r"\n(?=## )", "\n" + p1)
overview_md = "\n".join(s for s in p1_sections if s.strip())
overview_html = md(overview_md, "ov")
progress_html = md(progress, "pg")

# ---- Build log (steps) -----------------------------------------------------
steps = []
for f in sorted((project / "docs").glob("step-*.md")):
    text = f.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    num = re.search(r"(\d+)", f.stem).group(1).lstrip("0")
    title = first.lstrip("# ").split(":", 1)[-1].strip()
    goal = re.search(r"^Goal: (.+)$", rest, re.M)
    steps.append(
        {
            "num": num,
            "title": title,
            "goal": goal.group(1) if goal else "",
            "html": md(re.sub(r"^Goal: .+\n", "", rest, count=1, flags=re.M), f"s{num}"),
            "file": f"docs/{f.name}",
        }
    )

# ---- Deep dive (parts 2-5) ------------------------------------------------------
deep = []
for key, short in [
    ("Part 2.", "Concepts"),
    ("Part 3.", "Architecture"),
    ("Part 3b.", "Toolbox"),
    ("Part 4.", "Code walkthrough"),
    ("Part 5.", "Commands"),
]:
    t, body = part(key)
    pid = "d-" + re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-")
    deep.append(
        {
            "id": pid,
            "title": t.split(". ", 1)[1],
            "short": short,
            "html": md(body, pid),
            "toc": [h for h in re.findall(r"^## (.+)$", body, re.M)],
        }
    )

# ---- Source code ---------------------------------------------------------------
files = []
order = [
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    ".dockerignore",
    "src/github_mcp/__init__.py",
    "src/github_mcp/config.py",
    "src/github_mcp/github_client.py",
    "src/github_mcp/models.py",
    "src/github_mcp/server.py",
    "src/github_mcp/http_app.py",
    "scripts/demo.py",
    "tests/conftest.py",
    "tests/test_server.py",
    "tests/test_repositories.py",
    "tests/test_contents.py",
    "tests/test_issues_and_prs.py",
    "tests/test_errors_and_retries.py",
    "tests/test_resources_prompts_and_writes.py",
    "tests/test_http_transport.py",
    ".github/workflows/ci.yml",
    ".github/dependabot.yml",
]
roles = {
    "pyproject.toml": "Project definition: dependencies, scripts, test, coverage and lint settings",
    ".env.example": "Documents the environment variables; the real .env is never committed",
    ".gitignore": "Files git must never commit",
    "Dockerfile": "Step 8: multi-stage container image, non-root, health check",
    ".dockerignore": "Step 8: keeps secrets and clutter out of the image",
    "src/github_mcp/http_app.py": "Step 8: HTTP mode with bearer token and Host checks",
    "scripts/demo.py": "Step 8: scripted client tour for demos",
    "tests/test_http_transport.py": "Step 8: HTTP mode and its guards",
    "src/github_mcp/__init__.py": "Package version",
    "src/github_mcp/config.py": "Settings from environment variables",
    "src/github_mcp/github_client.py": "HTTP layer: auth, retries, rate limits, pagination, errors",
    "src/github_mcp/models.py": "Trimmed, typed output shapes",
    "src/github_mcp/server.py": "MCP layer: tools, resource, prompts",
    "tests/conftest.py": "Shared fixtures: fake GitHub, fake sleep",
    "tests/test_server.py": "Step 1: wiring",
    "tests/test_repositories.py": "Step 2: repositories",
    "tests/test_contents.py": "Step 3: reading code",
    "tests/test_issues_and_prs.py": "Step 4: issues, PRs, pagination",
    "tests/test_errors_and_retries.py": "Step 5: retries and rate limits",
    "tests/test_resources_prompts_and_writes.py": "Step 6: resources, prompts, writes",
    ".github/workflows/ci.yml": "Steps 7-8: CI on GitHub Actions, with a Docker check",
    ".github/dependabot.yml": "Step 7: automatic dependency updates",
}
langs = {".py": "python", ".toml": "toml", ".yml": "yaml", ".example": "bash", ".gitignore": "bash"}
for i, rel in enumerate(order):
    path = project / rel
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8").rstrip("\n")
    lang = langs.get(path.suffix or path.name, "bash")
    if path.name in (".gitignore", ".dockerignore"):
        lang = "bash"
    elif path.name == "Dockerfile":
        lang = "dockerfile"
    files.append(
        {
            "rel": rel,
            "role": roles.get(rel, ""),
            "lines": text.count("\n") + 1,
            "html": code_html(text, lang, f"f{i}"),
            "id": f"file-{i}",
        }
    )

# ---- Practice ---------------------------------------------------------------
_, p7 = part("Part 7.")
checklist = [ln[len("- [ ] ") :].strip() for ln in p7.splitlines() if ln.startswith("- [ ]")]


def inline(text: str) -> str:
    """Escape, then turn `code` and **bold** into tags (for flashcards)."""
    t = html.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)


cards = [
    {"n": q["n"], "cat": c["title"], "q": inline(q["q"]), "a": inline(q["a"])}
    for c in qa
    for q in c["qs"]
]
cats = [c["title"] for c in qa]

# ---- Stats ------------------------------------------------------------------------
server_src = (project / "src/github_mcp/server.py").read_text(encoding="utf-8")
n_tools = len(re.findall(r"^@mcp\.tool\(", server_src, re.M))
n_res = len(re.findall(r"^@mcp\.resource\(", server_src, re.M))
n_prompts = len(re.findall(r"^@mcp\.prompt\(", server_src, re.M))
n_tests = sum(
    len(re.findall(r"^async def test_|^def test_", (project / f).read_text(), re.M))
    for f in order
    if f.startswith("tests/test_")
)
src_lines = sum(f["lines"] for f in files if f["rel"].startswith("src/"))

# ---- Assemble ------------------------------------------------------------------
E = html.escape
nav_steps = "".join(
    f'<li><a href="#build" data-target="step-{s["num"]}">{s["num"]}. {E(s["title"])}</a></li>'
    for s in steps
)
nav_deep = "".join(
    f'<li><a href="#guide" data-target="{d["id"]}">{E(d["short"])}</a></li>' for d in deep
)

step_cards = "".join(
    f'''
<details class="step" id="step-{s["num"]}"{" open" if s["num"] == "1" else ""}>
  <summary>
    <span class="step-num">Step {s["num"]}</span>
    <span class="step-title">{E(s["title"])}</span>
    <span class="step-goal">{E(s["goal"])}</span>
  </summary>
  <div class="prose">{s["html"]}</div>
  <p class="src-note">Source: <code>{s["file"]}</code></p>
</details>'''
    for s in steps
)

deep_html = "".join(
    f'''
<section class="deep" id="{d["id"]}">
  <h2 class="part-title">{E(d["title"])}</h2>
  <div class="prose">{d["html"]}</div>
</section>'''
    for d in deep
)

file_cards = "".join(
    f'''
<details class="file" id="{f["id"]}">
  <summary><code class="path">{E(f["rel"])}</code><span class="role">{E(f["role"])}</span>
    <span class="lines">{f["lines"]} lines</span></summary>
  <div class="code-wrap">{f["html"]}</div>
</details>'''
    for f in files
)

check_items = "".join(
    f'<li><label><input type="checkbox" id="chk-{i}" data-key="chk-{i}"> '
    f"<span>{inline(t)}</span></label></li>"
    for i, t in enumerate(checklist)
)

cat_buttons = '<button type="button" class="chip on" data-cat="">All</button>' + "".join(
    f'<button type="button" class="chip" data-cat="{E(c)}">'
    f"{E(re.sub(r' [(]step [0-9]+[)]$', '', c))}</button>"
    for c in cats
)

template = (here / "site_template.html").read_text(encoding="utf-8")
page = (
    template.replace(
        "{{STATS}}",
        f"""
<div class="stat"><b>{n_tools}</b><span>tools</span></div>
<div class="stat"><b>{n_res}</b><span>resource template</span></div>
<div class="stat"><b>{n_prompts}</b><span>prompts</span></div>
<div class="stat"><b>{n_tests}</b><span>automated tests</span></div>
<div class="stat"><b>~94%</b><span>code coverage</span></div>
<div class="stat"><b>{src_lines}</b><span>lines of server code</span></div>""",
    )
    .replace("{{PROGRESS}}", progress_html)
    .replace("{{OVERVIEW}}", overview_html)
    .replace("{{NAV_STEPS}}", nav_steps)
    .replace("{{NAV_DEEP}}", nav_deep)
    .replace("{{STEPS}}", step_cards)
    .replace("{{DEEP}}", deep_html)
    .replace("{{FILES}}", file_cards)
    .replace("{{CHECKLIST}}", check_items)
    .replace("{{CATS}}", cat_buttons)
    .replace("{{CARDS_JSON}}", json.dumps(cards).replace("</", "<\\/"))
)
out.write_text(page, encoding="utf-8")
print(
    f"wrote {out} ({len(page) // 1024} KB): {len(steps)} steps, {len(files)} files, "
    f"{len(cards)} cards, {n_tools} tools, {n_tests} tests"
)
