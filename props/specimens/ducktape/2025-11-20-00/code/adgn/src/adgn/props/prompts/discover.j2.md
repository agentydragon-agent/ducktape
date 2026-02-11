{% extends "_base.j2.md" %}
{% set header_schema_names = ["IssueCore", "Occurrence", "LineRange", "ReportedIssue", "CriticSubmitPayload"] %}
{% set read_only = true %}
{% set include_reporting = true %}
{% set include_tools = true %}
{% set suppress_no_violations_line = true %}

{% block title %}Discover (only new){% endblock %}

{% block body %}
Only report findings that are NOT already listed in the embedded supplements above.
This includes additional instances under existing properties, new categories under existing properties, or entirely new issues not covered by current properties.

Perform an open-ended code quality review within the scope.
Find both violations of the properties below and any other significant issues not already covered by properties or supplements.
Run the detected analysis tools first in the suggested order, then do targeted manual review.
{% endblock %}
