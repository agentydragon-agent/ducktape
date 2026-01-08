# TODO: Convert tests to single-param OpenAI mock/live pattern

The `openai_client_param` fixture pattern is implemented in `tests/support/responses.py`.

## Pattern Reference

- Single-param fixture: `openai_client_param` (mock via behavior function OR `LIVE` sentinel marked `live_openai_api`)
- Behavior: one async function shaped like `responses.create(**kwargs)`; switch on `req` shape
- Live tests opt-in with `@pytest.mark.live_openai_api` (default runs exclude)

## Remaining Work

- [ ] `wt/tests/e2e/test_github_pr_display_real.py` (real_github)

  - Current: `@pytest.mark.real_github` (GitHub network)
  - Target: analogous single-param fixture pattern for the GitHub client (separate from OpenAI)
  - Expectations: `github_client_param` fixture that accepts a behavior function or LIVE; mock behavior returns canned payloads

- [ ] Audit remaining LLM tests for OpenAI usage
  - Search for `AsyncOpenAI`, `responses.create(`, or `@pytest.mark.live_openai_api`
  - Apply the same single-param fixture + behavior pattern; keep live variants opt-in

## Completed / Removed

- `test_openai_responses_live.py` → moved to `openai_utils/tests/test_responses_api_live.py`
- `test_exec_roundtrip.py` → removed
- `test_eval_lint_issue_wt.py` → removed with `lint_issue` module (commit 2180be60f)
