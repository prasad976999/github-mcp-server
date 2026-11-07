# Step 7: Continuous integration (CI)

Goal: every push and every pull request is checked automatically by GitHub (lint, formatting, tests on several Python versions and operating systems, and a coverage floor), so the project can never quietly break. A green CI badge also tells an interviewer, at a glance, that the project is maintained properly.

New files: `.github/workflows/ci.yml`, `.github/dependabot.yml`.
Changed files: `pyproject.toml` (pytest-cov, coverage settings, stricter ruff rules), `uv.lock`, `server.py` (one line wrapped for the new lint rule), `README.md`.

## 1. What CI is, and why it matters

**Continuous integration** means every change is automatically built and tested on a clean machine, not just on your laptop. It catches:

- "works on my machine" problems (a file you forgot to commit, a package only installed locally),
- problems on Python versions or operating systems you didn't try,
- style drift and lint errors, before anyone reviews the code.

**GitHub Actions** is GitHub's built-in CI. A **workflow** is a YAML file in `.github/workflows/`. It contains **jobs** (each runs on a fresh virtual machine, a **runner**), and each job has **steps** (shell commands or reusable **actions**).

## 2. The workflow, line by line (`.github/workflows/ci.yml`)

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
```

- **`on`**: the **triggers**. Every push to `main`, and every pull request (from any branch). A PR is checked *before* it's merged.

```yaml
permissions:
  contents: read
```

- **Least privilege again.** Each run gets a temporary token; this limits it to reading the code. If a dependency were ever compromised, it couldn't push code or change settings.

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

- If you push twice quickly, the first run is cancelled. Its result would be out of date anyway, and it saves CI minutes.

### The lint job

```yaml
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - name: Install dependencies (exact versions from uv.lock)
        run: uv sync --locked
      - name: Lint
        run: uv run ruff check .
      - name: Check formatting
        run: uv run ruff format --check .
```

- **`runs-on: ubuntu-latest`**: a fresh Linux machine for every run. Nothing is left over from earlier runs.
- **`timeout-minutes: 10`**: a stuck job is killed instead of running for the default 6 hours.
- **`actions/checkout@v4`**: downloads your repository onto the runner.
- **`astral-sh/setup-uv@v6`**: installs uv. `enable-cache: true` caches downloaded packages between runs, so later runs are faster.
- **`@v4`, `@v6`**: actions are pinned to a major version, so a breaking change in an action can't silently break CI. (Stricter still is pinning to a full commit SHA; Dependabot, below, keeps these up to date either way.)
- **`uv sync --locked`**: installs the **exact** versions in `uv.lock`, and **fails if `uv.lock` doesn't match `pyproject.toml`**. That catches the classic mistake of adding a dependency without committing the updated lock file.
- **`ruff format --check`**: doesn't change files, only fails if any file isn't formatted. Locally you run `uv run ruff format .` to fix it.

### The test job and the matrix

```yaml
  test:
    name: Tests (Python ${{ matrix.python-version }}, ${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    timeout-minutes: 10
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python-version }}
          enable-cache: true
      - name: Install dependencies (exact versions from uv.lock)
        run: uv sync --locked
      - name: Run tests with coverage (fails under 90%)
        run: uv run pytest --cov --cov-report=term-missing
```

- **A matrix** runs the same job for every combination: 2 operating systems × 3 Python versions = **6 jobs in parallel**.
- **Why Windows?** You develop on Windows and most CI only tests Linux. Paths, line endings and encodings differ, and this catches those bugs.
- **Why 3.11 to 3.13?** `pyproject.toml` promises `requires-python = ">=3.11"`. The matrix proves that promise is true, from the oldest version you claim to support to the newest.
- **`"3.11"` in quotes**: in YAML, `3.10` unquoted would become the number `3.1`. Quoting versions is a habit worth having.
- **`fail-fast: false`**: by default one failing job cancels the rest. Turning that off shows the whole picture, e.g. "fails only on Windows".
- **No secrets needed**: the tests mock GitHub with respx, so CI never needs your token. This is a big benefit of mocking: **secrets never go near CI**.

I checked the workflow with **actionlint** (a linter for GitHub Actions files) and ran the same commands here with Python 3.11, 3.12 and 3.13: all pass.

## 3. Coverage

```toml
[tool.coverage.run]
source = ["github_mcp"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = true
fail_under = 90
```

- **Coverage** measures which lines of your code ran during the tests (`pytest-cov` is the pytest plugin for the `coverage` tool).
- **`branch = true`**: also checks that both sides of each `if` were taken, not just that the line ran. Stricter and more honest.
- **`fail_under = 90`**: the test run **fails** if coverage drops below 90%. It's a ratchet: new code must come with tests. We're at **about 93%** now.
- **`show_missing`**: lists the line numbers that never ran, so you know where tests are missing.
- **Why not 100%?** The remaining lines are mostly defensive fallbacks (malformed headers, unreachable branches). Chasing 100% leads to tests that check nothing useful. **Coverage tells you what is untested, not that tested code is correct**: that's why each guard also has a test that was seen to fail when the code was broken.

## 4. Stricter linting

```toml
[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "SIM"]
```

| Code | Rule set | Catches |
|---|---|---|
| `E`, `W` | pycodestyle | Style errors, e.g. lines over 100 characters |
| `F` | Pyflakes | Real bugs: unused imports, undefined names |
| `I` | isort | Import order |
| `B` | flake8-bugbear | Likely bugs, e.g. mutable default arguments |
| `UP` | pyupgrade | Old syntax that has a modern form (`Optional[X]` → `X \| None`) |
| `SIM` | flake8-simplify | Code that can be written more simply |

Ruff's default is only `E` and `F`. Turning these on found one line that was too long (fixed by splitting the string). Ruff runs all of these in milliseconds because it's written in Rust.

## 5. Dependabot (`.github/dependabot.yml`)

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: monthly
  - package-ecosystem: uv
    directory: /
    schedule:
      interval: monthly
```

- Once a month, GitHub checks for newer versions of the actions and of your Python packages (it reads `uv.lock`) and **opens a pull request** for each update.
- **CI runs on that pull request**, so you only merge an update if the tests still pass. This is how CI and Dependabot work together: updates are automatic but never untested.
- Security fixes matter: an out-of-date `httpx` or `pydantic` with a known vulnerability would be flagged.

## 6. Try it

Locally (PowerShell), the same three checks CI runs:

```
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov
```

Expected: `All checks passed!`, `... files already formatted`, and `43 passed` with `Required test coverage of 90.0% reached`.

To see CI run for real, the project needs to be on GitHub. That's the next action in the thread: create an empty repository on github.com and push. Then the **Actions** tab shows the 7 jobs (1 lint + 6 tests).

## 7. Interview questions for this step

1. **What does your CI do?** On every push to main and every pull request, it checks lint and formatting with ruff and runs the tests with coverage on Linux and Windows, Python 3.11 to 3.13. It installs the exact locked versions and needs no secrets because GitHub is mocked.
2. **Why a matrix with Windows and several Python versions?** To prove the `requires-python` promise and catch OS-specific bugs like paths and encodings. I develop on Windows, but most users and servers run Linux.
3. **What does `uv sync --locked` protect against?** It fails if the lock file is out of date with `pyproject.toml`, so CI always tests exactly what's committed and a forgotten lock file update is caught.
4. **What's code coverage, and is 100% the goal?** The share of lines and branches the tests execute. I enforce a 90% floor so new code needs tests. 100% isn't the goal: coverage shows what's untested, not that tests are good, so I also check that key tests fail when the code is broken.
5. **Why `permissions: contents: read` in the workflow?** Least privilege: the job's token can only read the code, so a compromised dependency or action couldn't push code or change settings.
6. **What does Dependabot add?** Automatic pull requests for outdated or vulnerable dependencies and actions. CI tests each one, so updates are frequent but never untested.
