{% from "_partials.j2" import scope_block %}

Analyze the mounted repository under /workspace.

{{ scope_block(files, static_action|default("analyze"), ambiguity_tail|default("do not include anything outside run instructions.")) }}

Instructions:
- Read files as needed using available tools
- Report issues via critic_submit tools (see server instructions for workflow)
- Focus on concrete evidence: cite exact files and line ranges
