# Compaction test budget

`//agentplane/x/postgres_codex:test_compaction` reached the 60-second `small` limit
in [CI invocation `c3b8abf9`](https://app.buildbuddy.io/invocation/c3b8abf9-ed61-56c6-bbda-77213b3302de).
The test log completed 16 of 18 cases. Container diagnostics show PostgreSQL image
loading took 25.4 seconds and startup took 3.8 seconds; PostgreSQL became ready
44.3 seconds after the test action started.

BuildBuddy target history on October 28 records successful `devel` executions at
55.0–55.8 seconds, including [invocation `ce53ac80`](https://app.buildbuddy.io/invocation/ce53ac80-29e3-5659-922e-078274d30a36).
An unchanged [focused rerun `78e305cd`](https://app.buildbuddy.io/invocation/78e305cd-cb25-4d08-a0a4-e154acf8bf42)
passed all 18 cases in a 32.2-second action. Pytest reported 15.4 seconds for first-case
setup and 25.9 seconds total; no case took longer than 3 seconds.

The target uses `medium` for container setup and suite execution. The observed
timeout shows continued progress, with no established compaction or cleanup wedge.
