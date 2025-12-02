Analyze the mounted repository under /workspace.

Files in scope:
{% for file in files %}
- {{ file }}
{% endfor %}

Report issues only for the files listed above.

Instructions:
- Read files as needed using available tools
- Report issues via critic_submit tools (see server instructions for workflow)
- Focus on concrete evidence: cite exact files and line ranges
