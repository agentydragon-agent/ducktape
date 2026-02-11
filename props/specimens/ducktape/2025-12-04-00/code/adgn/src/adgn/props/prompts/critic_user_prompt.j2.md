Analyze the mounted repository under /workspace.

Analyze all of the following files:
{% for file in files %}
- {{ file }}
{% endfor %}

Instructions:
- Read files as needed using available tools
- Report issues via critic_submit tools (see server instructions for workflow)
- Focus on concrete evidence: cite exact files and line ranges
