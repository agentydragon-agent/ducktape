<%
MAX_DIFF_LINES = 20
MAX_ISSUES_SHOWN = 3
MAX_OUTPUT_CHARS = 500
would_fix = [h for h in result.failed_hooks if h.files_modified]
errors = [h for h in result.failed_hooks if not h.files_modified]
%>\
${file_path.name}:
% if result.auto_applied_results:
  Auto-applied: ${", ".join(h.hook_name for h in result.auto_applied_results)}
% endif
% if would_fix:
  Not auto-applied (would also edit): ${", ".join(h.hook_name for h in would_fix)}
% endif
% for hr in errors:
  ${hr.hook_name} (exit ${hr.exit_code})
% if pre_commit.show_hook_output:
<%
    output_text = hr.output.decode(errors="replace").strip()[:MAX_OUTPUT_CHARS]
%>\
% for line in output_text.splitlines()[:MAX_ISSUES_SHOWN]:
    ${line}
% endfor
% endif
% endfor
% if pre_commit.show_report_diffs and result.report_only_diff:
Changes pre-commit would make:
% for line in result.report_only_diff[:MAX_DIFF_LINES]:
${line}\
% endfor
% if len(result.report_only_diff) > MAX_DIFF_LINES:
... (diff truncated, ${len(result.report_only_diff) - MAX_DIFF_LINES} more lines)
% endif
% endif
% if errors:
Run `pre-commit run --files ${file_path}` to apply fixes.
% endif
