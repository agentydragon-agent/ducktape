<%
MAX_DIFF_LINES = 20
MAX_ISSUES_SHOWN = 3
MAX_OUTPUT_CHARS = 500
# Report-only hooks that modified the file (changes reverted, e.g. ruff-check --fix)
would_fix = [h for h in failed if h.files_modified]
# Hooks that exited non-zero without modifying (genuine errors, e.g. mypy)
errors = [h for h in failed if not h.files_modified]
%>\
% if auto_applied:
Auto-applied: ${", ".join(h.hook_name for h in auto_applied)}
% endif
% if would_fix:
Would also edit ${file_name}: ${", ".join(h.hook_name for h in would_fix)}
% endif
% if errors:
${len(errors)} ${"hook" if len(errors) == 1 else "hooks"} failed on ${file_name}:
% for hr in errors:
<%
    output_text = hr.output.decode(errors="replace").strip()[:MAX_OUTPUT_CHARS]
%>\
  ${hr.hook_name} (exit ${hr.exit_code})
% for line in output_text.splitlines()[:MAX_ISSUES_SHOWN]:
    ${line}
% endfor
% endfor
% if diff_lines:
Changes pre-commit would make:
% for line in diff_lines[:MAX_DIFF_LINES]:
${line}\
% endfor
% if len(diff_lines) > MAX_DIFF_LINES:
... (diff truncated, ${len(diff_lines) - MAX_DIFF_LINES} more lines)
% endif
% endif
Run `pre-commit run --files ${file_path}` to apply fixes.
% endif
