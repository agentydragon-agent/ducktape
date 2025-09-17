# TODO: Convert tests to single-param OpenAI mock/live pattern

Pattern reference
- Single-param fixture: `openai_client_param` (mock via behavior function OR `LIVE` sentinel marked `live_llm`)
- Behavior: one async function shaped like `responses.create(**kwargs)`; switch on `req` shape
  - Strong typing preferred: treat `req` as dict (Responses.create params are TypedDict at runtime) or pass SDK request class when readily available
  - Return real SDK Response objects via helpers:
    - `make_assistant_text_response(text, request=None|Req)`
    - `make_function_call_response(tool_name, arguments_json, request=None|Req)`
- Live tests opt-in with `@pytest.mark.live_llm` (default runs exclude)

---

- [ ] adgn/tests/llm/test_openai_responses_live.py
  - Current: `@pytest.mark.live_llm` live-only tests
  - Target: shared trunk parametrized with `openai_client_param = [behavior_switch, LIVE]`
  - Expectations:
    - Behavior returns real SDK Responses with minimal assistant text outputs for happy paths
    - Add branches for any prompts validated in assertions (envelope/shape-only assertions)

- [ ] adgn/tests/llm/mini_codex/test_exec_roundtrip.py
  - Current: contains `@pytest.mark.live_llm` and relies on real OpenAI
  - Target: shared trunk with `openai_client_param = [behavior_switch, LIVE]`
  - Expectations:
    - Behavior must simulate tool flow: emit `ResponseFunctionToolCall` where agent expects function calls; follow-up assistant text or tool outputs as needed
    - Keep assertions on envelope/order; avoid brittle text assertions

- [ ] adgn/tests/llm/properties/test_eval_lint_issue_wt.py
  - Current: `@pytest.mark.live_llm`; drives properties critic/grader flow
  - Target: shared trunk with `openai_client_param` and behavior that handles both agents
  - Expectations:
    - Critic phase: assistant text suffices unless function calls are expected
    - Grader phase: emit `make_function_call_response(tool_name="mcp__grader_submit__submit_result", arguments_json=<valid GradeSubmitInput JSON>)`
    - Ensure grader GateUntil is satisfied (submit_result is called)

- [ ] adgn/tests/wt/e2e/test_github_pr_display_real.py (real_github)
  - Current: `@pytest.mark.real_github` (GitHub network)
  - Target: analogous single-param fixture pattern for the GitHub client (separate from OpenAI)
  - Expectations:
    - Provide a `github_client_param` fixture that accepts a behavior function or LIVE; mock behavior returns canned payloads for the endpoints asserted in the test

- [ ] Audit remaining LLM tests for OpenAI usage
  - Search for `AsyncOpenAI`, `responses.create(`, or `@pytest.mark.live_llm`
  - Apply the same single-param fixture + behavior pattern; keep live variants opt-in

Notes
- Keep behaviors minimal and declarative: big switch on `req["input"]`, `req["tools"]`, `req["tool_choice"]`
- Always return real SDK models from helpers to preserve shape correctness
- Avoid `getattr` in tests; prefer dict/typed access and explicit asserts on types
 Use `-m "not live_llm"` in CI for fast deterministic runs; run live locally as needed
