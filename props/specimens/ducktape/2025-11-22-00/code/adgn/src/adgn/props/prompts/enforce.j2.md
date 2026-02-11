{% extends "_base.j2.md" %}
{% set header_schema_names = ["Occurrence", "LineRange"] %}
{% set read_only = false %}
{% set include_reporting = false %}
{% set include_tools = false %}

{% block title %}Enforce{% endblock %}

{% block body %}
Ensure code within the described scope conforms to the properties defined below and refactor as needed to satisfy them without altering behavior.

Editing policy:
- Prefer minimal, localized edits within the scoped hunks/sections.
- You MAY edit outside the scoped hunks/sections ONLY when necessary to bring the scoped changes and any code you touched into full compliance with all properties (e.g., moving imports to the top of file).
- If edits cascade (A requires B, which requires C, ...), keep fixing until everything you changed and everything originally in scope is compliant, then stop.
- Do NOT perform unrelated changes beyond what is required for compliance.
- Do not commit changes.
- After edits, run project lint/formatters (e.g., ruff, pre-commit) and re-verify against properties.

Requirements:
- You MUST check every changed hunk within the resolved scope
- You MUST bring all scoped files/sections into compliance ALL property definition files
- You MUST also apply any cascaded changes needed in other files as a result of bringing target files in compliance.

Operational guidance:
- Ask for confirmation before any destructive action (deletes/mass renames). Keep changes within the workspace.
- If enforcing a property would make the code worse, explain and propose an adjustment of the property's definition.

Deliverables:
- Apply changes directly in the workspace.
- Print a concise change report as your final message:
  Files changed, properties addressed per file, and any remaining violations you could not safely fix.
{% endblock %}
