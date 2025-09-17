{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload"] %}
{% set read_only = true %}
{% set include_reporting = true %}
{% set include_tools = true %}

{% block title %}Review code and report issues{% endblock %}

{% block body %}
Analyze the codebase for issues including correctness, style, maintainability, design.

We have some properties that good code should meet with formal definitions.
Where you find violations of these properties, report them tagged with the violated property.

But do not limit your search only by the formally defined properties:
report any problem that an experienced reviewer would call out, ways that code is inelegant or awkward or needs refactors, etc.

Do not modify any files.
Output only violations; do not list properties/files with 'No violations'.
Produce a concise structured report.
{% endblock %}
