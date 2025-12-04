# Issue Libsonnet Audit Findings

Audit of issue libsonnet files in `ducktape/2025-11-20-00` specimen.

## Issues Found

| File | Issue Type | Current State | Proposed Fix |
|------|------------|---------------|--------------|
| **created-at-auto-default** | Wrong structure | `issue()` with 3 lines (32, 119, 153) for 3 different models | Convert to `issueMulti` with 3 occurrences (Agent, ToolCall, Policy models) |
| **event-count-should-be-derived** | Wrong expect_caught_from | `[['models.py'], ['sqlite.py']]` (OR) | Change to `[['models.py', 'sqlite.py']]` (AND) - need both to understand issue |
| **parse-response-should-not-exist** | Wrong structure | `issue()` with 2 functions bundled | Convert to `issueMulti` with 2 occurrences (parse_response_messages, parse_chat_messages) |
| **policyerror-stage-strenum** | Extraneous lines | Includes lines 9-11 (correct code for comparison) | Remove context lines from filesToRanges, keep only line 15 (actual problem) |
| **pydantic-boundary-handling** | Distinct problems bundled | 2 conceptually different issues in 1 file | Split into 2 files: read-path (sqlite.py dict→Pydantic) and write-path (handler.py early serialization) |
| **single-use-intermediate-variables** | Wrong structure | `issue()` with 6 independent variables | Convert to `issueMulti` with 6 occurrences (one per variable) |
| **sqlalchemy-enum-fields** | Wrong structure | `issue()` with 5 field lines | Convert to `issueMulti` with 5 occurrences (Run.status, Event.type, Policy.status, ChatMessage.author, ChatMessage.mime) |
| **stub-convenience-stack-method** | Wrong structure | `issue()` with 2 ranges | Convert to `issueMulti` with 2 occurrences (PolicyReaderStub, PolicyApproverStub) |
| **unnecessary-wrapper-functions** | Wrong structure | `issue()` for 2 file groups | Convert to `issueMulti` with 2 occurrences (openai_typing.py wrappers, agent.py wrapper) |
| **unused-ui-port-flag** | Wrong expect_caught_from | `[['cli.py'], ['server.py']]` (OR) | Change to `[['cli.py', 'server.py']]` (AND) - need both to see full issue |
| **walrus-assign-check** | Wrong structure | `issue()` with 12 instances across 8 files | Convert to `issueMulti` with 12 occurrences (each assign-then-check pattern) |

## Summary by Action Type

| Action | Count | Files |
|--------|-------|-------|
| Convert to `issueMulti` | 8 | created-at-auto-default, parse-response-should-not-exist, single-use-intermediate-variables, sqlalchemy-enum-fields, stub-convenience-stack-method, unnecessary-wrapper-functions, walrus-assign-check |
| Fix `expect_caught_from` | 3 | event-count-should-be-derived, unused-ui-port-flag, policyerror-stage-strenum |
| Split into separate files | 1 | pydantic-boundary-handling |

## Files Correctly Structured (No Action Needed)

- agententry-should-be-dataclass
- ensure-schema-destroys-data
- exceptiongroup-not-error-strings
- extract-cmd-use-shlex-join
- list-runs-loop-to-comprehension
- no-catch-keyerror-valueerror
- pending-notifier-accept-toolcall
- preset-modified-at-datetime
- registry-get-missing
- removeprefix-not-magic-slice
- return-result-not-reconstruct
- send-json-duplicate-logic
- silent-config-file-fallback
- sqlalchemy-import-in-function
- token-table-pydantic-model
- useless-comments
