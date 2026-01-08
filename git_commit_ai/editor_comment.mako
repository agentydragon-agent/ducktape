<%doc>
Editor prefill template for git-commit-ai.
The commented section gets '# ' prefix via Mako filter; verbose diff below scissors is verbatim.
</%doc>
<%!
import textwrap
import pygit2

MAX_VERBOSE_DIFF_LINES = 3000

STATUS_TO_TEXT = {
    pygit2.GIT_DELTA_ADDED: "new file:",
    pygit2.GIT_DELTA_MODIFIED: "modified:",
    pygit2.GIT_DELTA_DELETED: "deleted:",
    pygit2.GIT_DELTA_RENAMED: "renamed:",
    pygit2.GIT_DELTA_TYPECHANGE: "typechange:",
}

def comment_prefix(text):
    return textwrap.indent(text, "# ", lambda line: True)

def delta_path(delta):
    if delta.status == pygit2.GIT_DELTA_DELETED:
        return delta.old_file.path
    return delta.new_file.path

def delta_status_text(delta):
    return STATUS_TO_TEXT.get(delta.status, "unknown:")

%>
<%def name="verbose_diff_lines(diff)">\
<%
    patch = diff.patch or ""
    lines = patch.splitlines()
    total = len(lines)
%>\
% for i, line in enumerate(lines):
% if i >= MAX_VERBOSE_DIFF_LINES:
[TRUNCATED: showing first ${MAX_VERBOSE_DIFF_LINES} of ${total} lines]
<% break %>\
% endif
${line}
% endfor
</%def>\
<%def name="commented()" filter="comment_prefix">\
% if user_context:
User context (-m):
${user_context}

% endif
% if previous_message:
Previous commit message (being amended):
${previous_message}

% endif
${stats_line}

Please enter the commit message for your changes. Lines starting
with '#' will be ignored, and an empty message aborts the commit.

On branch ${branch}

% if list(staged_diff.deltas):
Changes to be committed:
% for delta in staged_diff.deltas:
	${delta_status_text(delta).ljust(12)} ${delta_path(delta)}
% endfor
% endif
% if list(unstaged_diff.deltas):

Changes not staged for commit:
  ("git add <file>..." to update what will be committed)
  ("git restore <file>..." to discard changes in working directory)
% for delta in unstaged_diff.deltas:
	${delta_status_text(delta).ljust(12)} ${delta_path(delta)}
% endfor
% endif
% if untracked_files:

Untracked files:
  ("git add <file>..." to include in what will be committed)
% for filename in untracked_files:
	${filename}
% endfor
% endif

${scissors_mark}
Do not modify or remove the line above.
Everything below it will be ignored.
</%def>\
${commented()}\
% if include_verbose:
${verbose_diff_lines(staged_diff)}\
% endif
