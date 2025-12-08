Analyze all of the following files in the mounted repository under /workspace:
{% for file in files %}
- {{ file }}
{% endfor %}

Read files as needed using available tools
Report issues via critic_submit tools - see server instructions for workflow.
