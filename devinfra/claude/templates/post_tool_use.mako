<%
MAX_DIFF_LINES = 20
MAX_ISSUES_SHOWN = 3
MAX_OUTPUT_CHARS = 500
would_fix = [h for h in failed if h.files_modified]
errors = [h for h in failed if not h.files_modified]
%>\
${file_name}:
% if auto_applied:
  Auto-applied: ${", ".join(h.hook_name for h in auto_applied)}
% endif
% if would_fix:
  Not auto-applied (would also edit): ${", ".join(h.hook_name for h in would_fix)}
% endif
% for hr in errors:
  ${hr.hook_name} (exit ${hr.exit_code})
% if show_hook_output:
<%
    output_text = hr.output.decode(errors="replace").strip()[:MAX_OUTPUT_CHARS]
%>\
% for line in output_text.splitlines()[:MAX_ISSUES_SHOWN]:
    ${line}
% endfor
% endif
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
% if errors:
Run `pre-commit run --files ${file_path}` to apply fixes.
% endif
