<%doc>
Editor prefill template for git-commit-ai.
The commented section gets '# ' prefix via Mako filter; verbose diff below scissors is verbatim.
</%doc>
<%!
import textwrap

def comment_prefix(text):
    return textwrap.indent(text, "# ", lambda line: True)
%>
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

% if staged_files:
Changes to be committed:
% for status_text, filename in staged_files:
	${status_text.ljust(12)} ${filename}
% endfor
% endif
% if unstaged_files:

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed
  (use "git restore <file>..." to discard changes in working directory
% for status_text, filename in unstaged_files:
	${status_text.ljust(12)} ${filename}
% endfor
% endif
% if untracked_files:

Untracked files:
  (use "git add <file>..." to include in what will be committed)
% for filename in untracked_files:
	${filename}
% endfor
% endif

${scissors_mark}
Do not modify or remove the line above.
Everything below it will be ignored.
</%def>\
${commented()}\
% if verbose_diff:
% for line in verbose_diff:
${line}
% endfor
% endif
