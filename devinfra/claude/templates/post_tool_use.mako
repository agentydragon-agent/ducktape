<%
MAX_DIFF_LINES = 20
MAX_ISSUES_SHOWN = 3
MAX_OUTPUT_CHARS = 500
%>\
% if auto_applied:
Auto-applied: ${", ".join(h.hook_name for h in auto_applied)}
% endif
% if failed:
${len(failed)} ${"hook" if len(failed) == 1 else "hooks"} failed on ${file_name}:
% for hr in failed:
<%
    status = "modified file" if hr.files_modified else f"exit {hr.exit_code}"
    output_text = hr.output.decode(errors="replace").strip()[:MAX_OUTPUT_CHARS]
%>\
  ${hr.hook_name} (${status})
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
