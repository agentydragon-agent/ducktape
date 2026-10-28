# Sandbox access test budget

`//agentplane/app:test_sandbox_access` timed out after 60.28 seconds in
[CI invocation `a9289432`](https://app.buildbuddy.io/invocation/a9289432-f7db-54cf-9cea-6db142627a40).
All three pytest cases passed in 29.47 seconds, and the retained API-server log shows orderly
API-server and etcd shutdown. The executor reported 61.44 seconds of cumulative file download
latency during the action. These timings overlap; they are not additive.

The preceding target-history page contained 39 passing runs, including 28.45, 44.06 and 32.86
seconds. A focused RBE rerun passed in 40.1 seconds in
[invocation `7e861a87`](https://app.buildbuddy.io/invocation/7e861a87-3658-4bf8-9bda-9157b54a92fb).
That invocation's Go target failed because the diagnostic pytest flag was also passed to Go;
the independent Go rerun passed in `1da3b44f-3215-42f9-82dd-cf9bacf70790`.

Size this API-server integration target `medium`, consistent with the observed executor-latency
workaround in [the RBE investigation](../../devinfra/debug/2026_08_rbe_small_test_timeouts.md).
This changes the test budget; it does not establish a fix for executor latency.
