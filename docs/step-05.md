# Step 5: Errors, retries and rate limits

Goal: the server copes with a flaky network and with GitHub's request limits, without hanging, without hammering GitHub, and always with an error message the model can act on.

New tool:
- `get_rate_limit()`: how many requests are left this hour, and when the budget resets.

Changed files: `github_client.py` (retry loop in `_get_response`, `_rate_limit_wait`, clearer messages), `models.py` (`RateLimitStatus`), `server.py` (new tool, updated instructions), `tests/conftest.py` (fake sleep), `tests/test_errors_and_retries.py` (9 new tests, 30 in total).

## 1. An error taxonomy: which failures are worth retrying?

Not every error deserves a retry. The key question is **"would the exact same request succeed if I sent it again?"**

| Failure | Example | Retry? | Why |
|---|---|---|---|
| Network / timeout | Wi-Fi blip, `ConnectTimeout` | Yes | Usually temporary |
| Server error (5xx) | 500, 502, 503, 504 | Yes | GitHub's problem, often gone in a second |
| Rate limit, short wait | 429 with `Retry-After: 2` | Wait, then yes | GitHub told us exactly when it's OK |
| Rate limit, long wait | 403 with `X-RateLimit-Remaining: 0`, reset in 30 min | **No**, report it | Blocking a tool call for 30 minutes is worse than telling the user |
| Client error (other 4xx) | 404 Not Found, 401, 422 | **No** | The same request will fail the same way; the model must change something |

**Idempotency** is what makes retrying safe. A request is idempotent if doing it twice has the same effect as doing it once. Every call we make is a `GET` (read-only), so a retry can never, say, create two issues. When we add `create_issue` in step 6 (a `POST`), we must **not** blindly retry it: if the first attempt reached GitHub but the response was lost, a retry would create a duplicate.

## 2. Exponential backoff with jitter

```python
MAX_ATTEMPTS = 3  # the first try plus two retries
BASE_DELAY_S = 0.5
...
delay = random.uniform(0, BASE_DELAY_S * 2 ** (attempt - 1))
```

- **Exponential**: the maximum wait doubles each time (0.5 s, then 1 s). If GitHub is struggling, we back off instead of piling on.
- **Jitter** (the randomness, `random.uniform(0, ...)`): if a thousand clients all failed at the same moment and all retried exactly 0.5 s later, they would hit GitHub together again (a "thundering herd"). Random waits spread them out. Picking anywhere from 0 to the ceiling is called **full jitter**.
- **Capped attempts**: 3 attempts means the worst case is bounded (about 1.5 s of waiting plus the request timeouts). An LLM tool call must finish in reasonable time.

## 3. Rate limits

GitHub limits how many requests you can make:
- **Primary limit**: 60 requests/hour without a token, 5,000 with one. Every response tells you where you stand in headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (a Unix timestamp).
- **Secondary limits**: protection against bursts (too many requests too fast, or too many searches). GitHub replies `403` or `429`, usually with `Retry-After: <seconds>`.

`_rate_limit_wait(response)` works out how long GitHub wants us to wait, or `None` if the error isn't a rate limit:

```python
if response.status_code not in (403, 429):
    return None
if retry_after header:                    → that many seconds  (secondary limit)
if X-RateLimit-Remaining == "0":          → reset time minus now  (hourly budget used up)
if status is 429 with no hint:            → 60 seconds  (GitHub's documented advice)
otherwise:                                → None  (a plain 403 is a permissions problem)
```

Then in `_get_response`:
- Wait is **10 s or less** (`MAX_WAIT_S`) → sleep that long and try again.
- Wait is **longer** → stop and return a message: *"GitHub rate limit reached. It resets in about 30 minute(s). Retrying now will not help; tell the user and try again later."* Without a token it adds: *"Adding a GITHUB_TOKEN raises the limit from 60 to 5,000 requests/hour."*

**Why tell the model "retrying now will not help"?** Models tend to retry a failed tool. The error message is effectively a prompt: it tells the model what to do next (stop and inform the user). The server instructions say the same and point to `get_rate_limit`.

**Why is a 403 not always a rate limit?** GitHub uses 403 for both "you've used your quota" and "you don't have permission". The headers tell them apart. Treating a permissions 403 as a rate limit would make us wait for nothing; a test checks we don't.

## 4. The retry loop in `_get_response`, line by line

```python
for attempt in range(1, MAX_ATTEMPTS + 1):
    try:
        response = await self._http.get(url, params=params)
    except httpx.TimeoutException as exc:
        error = GitHubAPIError(504, f"GitHub did not respond in time ({url}).")
        error.__cause__ = exc
    except httpx.HTTPError as exc:
        error = GitHubAPIError(502, f"Could not reach GitHub: {exc}")
        error.__cause__ = exc
    else:
        if response.is_success:
            return response

        wait = _rate_limit_wait(response)
        if wait is not None:
            if wait > MAX_WAIT_S or attempt == MAX_ATTEMPTS:
                raise GitHubAPIError(response.status_code, self._rate_limit_message(wait))
            await _sleep(wait)
            continue

        error = GitHubAPIError(response.status_code, _error_message(response))
        if response.status_code not in RETRYABLE_STATUS:
            raise error

    if attempt == MAX_ATTEMPTS:
        raise GitHubAPIError(
            error.status_code, f"{error} Gave up after {MAX_ATTEMPTS} attempts."
        ) from error.__cause__

    delay = random.uniform(0, BASE_DELAY_S * 2 ** (attempt - 1))
    logger.warning(...)
    await _sleep(delay)
```

- **`try / except / else`**: the `else` block runs only if no exception happened, i.e. we got a response. Network failures are handled in the `except` blocks.
- **`error.__cause__ = exc`**: keeps the original exception attached, the same as `raise ... from exc`, so a developer reading a traceback sees the real cause.
- **`continue`** after a rate-limit wait skips the backoff and goes straight to the next attempt.
- **Non-retryable 4xx → `raise error` immediately**: no wasted requests.
- **"Gave up after 3 attempts"**: tells the model the server already retried, so retrying again itself is pointless.
- **`logger.warning`** goes to stderr, so retries are visible in the Inspector's server log without breaking the stdio protocol.
- **`_sleep`** is a module-level alias for `asyncio.sleep`. Tests replace it so they never really wait (see below). `asyncio.sleep` (not `time.sleep`) lets the server keep serving other requests while it waits.

## 5. The `get_rate_limit` tool

Calls `GET /rate_limit`, which **doesn't count against your limit**, and returns `RateLimitStatus`: `authenticated`, `limit`, `remaining`, `used`, `resets_at` (converted from a Unix timestamp to a UTC date-time), and `search_remaining` (search has its own smaller budget of 30 per minute). The model can check the budget before a big exploration, or explain a rate-limit error to the user.

## 6. Tests (`tests/test_errors_and_retries.py`)

**Fake time:** a `sleeps` fixture in `conftest.py` (with `autouse=True`, so it applies to every test) replaces `_sleep` with a function that just records the delay. The whole suite still runs in about a second, and tests can assert exactly how long the code *would* have waited. This is called **dependency injection / test doubles for time**: never make tests actually sleep.

| Test | What it checks | Why it's needed |
|---|---|---|
| `test_server_error_is_retried_then_succeeds` | 503 then 200 → success, 2 requests, one wait ≤ 0.5 s | The basic retry path |
| `test_backoff_doubles_between_attempts` | With jitter pinned to its maximum, waits are exactly `[0.5, 1.0]` | Proves the backoff is exponential |
| `test_gives_up_after_max_attempts` | Always 503 → exactly 3 requests, "Gave up after 3 attempts" | Retries are bounded |
| `test_timeout_is_retried` | A timeout then 200 → success | Network failures are retried too |
| `test_not_found_is_not_retried` | 404 → 1 request, no waiting | Don't waste requests on errors that won't change |
| `test_short_retry_after_is_waited_out` | 429 with `Retry-After: 2` → waits exactly 2 s, then succeeds | Respects GitHub's instruction |
| `test_exhausted_hourly_limit_is_reported_not_waited` | 403, `Remaining: 0`, reset in 30 min → 1 request, no wait, message says "30 minute" | Never hangs a tool call for minutes |
| `test_forbidden_without_rate_limit_headers_is_not_retried` | Plain 403 → "Access denied", no wait | Tells permission errors apart from rate limits. **I checked this test (and the 404 one) fails if the "don't retry 4xx" line is removed.** |
| `test_get_rate_limit_reports_core_budget` | Numbers and reset date are mapped from `/rate_limit` | The new tool's happy path |

`respx` returns a **list** of responses in order when you set `route.side_effect = [...]`, which is how a test simulates "fail, then succeed". `monkeypatch.setattr(github_client.random, "uniform", ...)` makes the random jitter predictable for one test.

## 7. Try it (PowerShell)

```
uv run pytest
uv run mcp dev src/github_mcp/server.py
```

Expected: `30 passed`. In the Inspector:
- `get_rate_limit`. With your token, `limit` should be `5000`. Run another tool, then `get_rate_limit` again: `used` goes up by one (or more for multi-page lists).
- Retries are hard to trigger for real (GitHub is rarely down), which is exactly why the tests simulate them.

## 8. Interview questions for this step

1. **Which errors do you retry, and which not?** Timeouts, network errors and 5xx, because they're usually temporary. Not other 4xx, because the same request fails the same way; the model has to change its input instead.
2. **What's exponential backoff with jitter, and why jitter?** Each retry waits up to twice as long as the last; the actual wait is random within that ceiling, so many clients don't retry in lockstep and overload the server again.
3. **What's idempotency and why does it matter for retries?** Doing a request twice has the same effect as once. GETs are idempotent so retrying is safe; a POST like create_issue isn't, so blind retries could create duplicates.
4. **How do you handle GitHub's rate limits?** Read `Retry-After` and the `X-RateLimit-*` headers. Short waits (≤ 10 s) I wait out; longer ones I report with the reset time, because a tool call shouldn't hang. A `get_rate_limit` tool shows the budget.
5. **How do you test retries without slow tests?** Replace the sleep function with a recorder in a fixture, simulate fail-then-succeed with respx `side_effect` lists, and assert on the recorded delays.
6. **Why put "retrying now will not help" in an error message?** The message goes back to the model as text. It's effectively a prompt, so it should say what to do next.
