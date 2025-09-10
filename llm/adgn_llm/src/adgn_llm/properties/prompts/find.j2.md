{% extends "_base.j2.md" %}
{% set header_schema_names = ["Occurrence", "LineRange"] %}
{% set read_only = true %}
{% set include_reporting = true %}
{% set include_tools = true %}

{% block title %}Find violations{% endblock %}

{% block body %}
Analyze the codebase for violations of the properties defined below. Do not modify any files. Output only violations; do not list properties/files with 'No violations'. Produce a concise structured report.
{% endblock %}
