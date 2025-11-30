{% from "_partials.j2" import scope_block %}

Analyze the mounted repository under /workspace.

{{ scope_block(files, static_action|default("analyze"), ambiguity_tail|default("do not include anything outside run instructions.")) }}

Instructions:
- Read files as needed using available tools only.
- Report issues via critic_submit tools (incremental flow):
  - For each distinct issue: upsert_issue(issue_id, description) with a concise rationale (do not dump multi‑issue reviews into one description).
  - Add occurrences: add_occurrence(issue_id, file, ranges) or add_occurrence_files(issue_id, files={path:[ranges]}). Ranges can be 123 or [140,150].
  - When finished: submit(issues=<N>) where N is the number of issues you created (must match server count).
- Do not output a plain‑text report; do not summarize outside tool calls.
- Use report_failure(error) only when truly blocked (e.g., no files matched scope or access issues), with a brief one‑line reason.
- Focus on concrete evidence: cite exact files and line ranges.
