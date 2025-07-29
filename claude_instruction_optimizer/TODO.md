## Network/Internet Access Control

The `internet_needed` field was removed from the codebase as it was not functionally implemented - it only served as metadata in the database and Docker labels without actually controlling network access.

Future implementation should include optional network isolation via task-level switch.
Problem to solve: claude binary still makes LLM sampling requests from inside container.
