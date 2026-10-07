## Verifying a visual change — see the rendered image, not just a passing test

A passing `bbr test //agentplane/app/frontend:visual` only proves every scene mounted
without an uncaught error — it says nothing about whether it looks right (there are no checked-in
pixel baselines here; see `util/testing/frontend_visual/README.md`). Before calling a visual
change (`threads/projected_session.tsx`, `threads/projected_session.css`, or any other component/stylesheet here) done, actually look
at a rendered PNG of every state you touched. Either of these satisfies that — the point is seeing
the real pixels, not a specific mechanism for getting there:

- **Wait for CI's `pr-visuals` comment** on the PR: it renders every visual scenario and posts
  before/after/diff thumbnails automatically once pushed.
- **Or run the scenario locally** — `bbr test //agentplane/app/frontend:visual
--test_filter=<scenario-or-test-name> --noremote_accept_cached --nocache_test_results` — and download the PNG it
  writes to the test's
  undeclared outputs (`buildbuddy_api` skill: `bbapi artifact list <invocation-id>` for the exact
  name, passed to `capture_scene`, then `bbapi artifact download <invocation-id>
"<name>-actual.png"`), then view it. A failure in another shard: `bbapi target log <invocation-id>
visual --failed`.

A local interactive browser session (running the app, clicking through it by hand) is neither
required nor the goal here — it's extra machinery for the same answer a screenshot already gives.
Reach for it only when a _static_ screenshot genuinely can't show what changed (verifying motion
itself, not an animation's start/end frames — which visual tests disable anyway).

## Adding a visual test

Fixture catalogs in `harness/scenarios.json` and `harness/interaction_scenarios.json`
contain routes and canned application data only. Python tests own readiness, clicks,
scrolls, assertions and capture; `visual_pages.py` shares preparation and capture metadata.
Use `util/testing/viewports.py` for browser geometry. Keep the existing target and image
names so PR visual review retains its baseline identity.

Do not add harness switches that click, focus, scroll or inspect the DOM. Add an ordinary
Python behavior test and an explicit screenshot checkpoint instead. BUILD names the test
module, not individual scenes. Filter with the test function or parametrized case ID.
