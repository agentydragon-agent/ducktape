<%
MAX_DIFF_LINES = 20
MAX_ISSUES_SHOWN = 3
MAX_OUTPUT_CHARS = 500
%>\
${file_path.name}:
% if result.auto_applied:
  Auto-applied:\
% for hook_id, hr in result.auto_applied.items():
<%
    status = "now clean" if hr.rerun_exit_code == 0 else f"not fully fixed, still exit {hr.rerun_exit_code}"
%>
    ${hook_id} (${status})\
% endfor

% endif
% if result.would_edit:
  Not auto-applied (would also edit): ${", ".join(result.would_edit)}
% endif
% if result.failed_not_applied:
  Failed (not applied):\
% for hook_id, hr in result.failed_not_applied.items():

    ${hook_id} (exit ${hr.exit_code})\
% if pre_commit.show_hook_output:
<%
    output_text = hr.output.decode(errors="replace").strip()[:MAX_OUTPUT_CHARS]
%>\
% for line in output_text.splitlines()[:MAX_ISSUES_SHOWN]:

      ${line}\
% endfor
% endif
% endfor

% endif
% if pre_commit.show_report_diffs and result.report_only_diff:
Changes pre-commit would make:
% for line in result.report_only_diff[:MAX_DIFF_LINES]:
${line}\
% endfor
% if len(result.report_only_diff) > MAX_DIFF_LINES:
... (diff truncated, ${len(result.report_only_diff) - MAX_DIFF_LINES} more lines)
% endif
% endif
% if result.failed_not_applied:
Run `pre-commit run --files ${file_path}` to apply fixes.
% endif
