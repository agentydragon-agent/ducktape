## Network/Internet Access Control

The `internet_needed` field was removed from the codebase as it was not functionally implemented - it only served as metadata in the database and Docker labels without actually controlling network access.

Future implementation should include optional network isolation via task-level switch.
Problem to solve: claude binary still makes LLM sampling requests from inside container.

## Task Output Accessibility

Once Claude runs inside containers, task outputs (files, logs, results) will not be easily accessible from host filesystem. Need to implement proper output collection:

- Add bind mount or volume for output directory
- Copy results from container to host filesystem after execution
- Consider structured output format for easier analysis
- Preserve file permissions and timestamps

## Wrong filtering of directories

```
Repository bundles huge Cargo target/ artifacts (> 80 MB) and lock files but omits src/. Documentation is absent. This is poor hygiene.
```
