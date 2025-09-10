# {% block title %}{% endblock %}

- Properties are formal rules in Markdown; apply them strictly by the exact predicate wording. Do not stretch, infer, or generalize beyond what the definition actually says.
- No domain/scope stretching:
  - “Never assemble SQL by string concatenation” does not apply to string-building of JavaScript.
- No location/direction mismatches (two distinct examples):
  - (a) A rule about doing something in pyproject does not apply to analogous issues in module code.
  - (b) “All dependencies must be declared in pyproject” is not “No declared dependencies may be unused.” These are different predicates.
- No “similar-topic” generalization:
  - A rule about signed integers for memory sizes does not apply to an unsigned arithmetic overflow; that would require a different property.
  - A rule “Lengths must be in meters” is not violated by a temperature in Fahrenheit; a broader wording like “All units must be SI” (or equivalent) would cover that — but only if that’s what the definition actually says.
- Names vs definitions: property names are not authoritative; the definition text is. Example: a property named “no-user-code-execution” with definition “Never call eval(api-input-string)” does not apply to `subprocess.call(api_input_string)`. If the definition said “never call exec or analogous execution methods on user/api inputs”, that would.
- Anchors: Identify the exact 1-based line ranges that manifest (or do not manifest) the predicate. If provided anchors miss, suggest corrected minimal ranges.
- Evidence: Quote only what’s necessary (≤ ~15 lines) to support applicability or non‑applicability. When unclear, prefer “not applicable / mislabeled” over stretching the definition.

Environment:
- Property definitions: {% if wiring.definitions_container_dir %}mounted read-only at {{ wiring.definitions_container_dir }}{% else %}not mounted{% endif %}


{% if header_schema_names %}
Input Schemas:
{% for name in header_schema_names %}
- {{ name }}
```json
{{ schemas_json[name] | tojson(indent=2) }}
```
{% endfor %}
{% endif %}

{% from "_partials.j2" import scope_block, constraints_read_only, supplemental_section_md, tools_section, reporting_requirements %}

{{ scope_block(scope_text, static_action, ambiguity_tail) }}

{% if read_only %}{{ constraints_read_only() }}{% endif %}

{% if include_reporting %}{{ reporting_requirements(no_empty_reports=suppress_no_violations_line|default(true)) }}{% endif %}

{{ supplemental_section_md(supplemental_text) }}

{% if include_tools %}{{ tools_section(available_tools) }}{% endif %}

{% block body %}{% endblock %}
