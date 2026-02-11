{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload"] %}
{% set read_only = true %}
{% set include_reporting = true %}
{% set include_tools = true %}

{% block title %}Open review{% endblock %}

{% block body %}
Perform an open-ended code quality review within the scope. Find both violations of the properties below and any other significant issues not already covered by properties or supplements. Run the detected analysis tools first in the suggested order, then do targeted manual review. Output only findings.
{% endblock %}
