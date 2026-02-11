# {% block title %}{% endblock %}

{% if include_properties|default(true) %}
## Properties

We have a set of formal properties that good code should meet, defined in Markdown.
Identify them by their *filenames*: a property stored in `foo/bar.md` is named `bar`.

Quote only what's necessary (≤ ~15 lines) to support applicability or non‑applicability of a property.

When unclear, prefer to not apply a property to an issue over stretching the definition.

### Decide property applicability by exact wording of definition

Apply properties strictly by the exact predicate wording.
Do not stretch, infer, or generalize beyond what the definition actually says.

#### No domain/scope stretching:

"Never assemble SQL by string concatenation" does not apply to string-building of JavaScript.

#### No location/direction mismatches

Examples:
- A rule about doing something in pyproject does not apply to analogous issues in module code.
- "All dependencies must be declared in pyproject" is not "No declared dependencies may be unused." These are different predicates.

#### No "similar-topic" generalization:

A rule about signed integers for memory sizes does not apply to a general unsigned arithmetic overflow.
That would require a different property.

A rule saying "Lengths must be in meters" is not violated by a temperature in Fahrenheit.
A broader wording like "All units must be SI" (or equivalent) would cover that — but only if that's what the definition *actually says*.

#### Names vs definitions

Property names are not authoritative; the definition text is.

Assuming an example property `no-user-code-execution.md` stating:

```
Never call eval(api-input-string)
```

This property *would not* be violated by `subprocess.call(api_input_string)` - it's *`subprocess.call`*, not `eval`.
If the definition said "never call `eval` or analogous execution methods on user/api inputs", then it would be violated.
{% endif %}

## Line anchors

Identify occurrences by exact 1-based line ranges that manifest (or do not manifest) the given issue.

## Environment

- Workspace: mounted read-only at {{ wiring.working_dir }} (analysis only)
- Scratch/caches/logs: write under /tmp (do not modify files under the workspace)
- Property definitions: {% if wiring.definitions_container_dir %}mounted read-only at {{ wiring.definitions_container_dir }}{% else %}not mounted{% endif %}

{% if header_schema_names %}

## Input Schemas:

{% for name in header_schema_names %}
- {{ name }}
```json
{{ schemas_json[name] | tojson(indent=2) }}
```
{% endfor %}
{% endif %}

{% from "_partials.j2" import constraints_read_only, supplemental_section_md, tools_section, reporting_requirements %}

## Files in scope

{% for file in files %}
- {{ file }}
{% endfor %}

{% if read_only %}{{ constraints_read_only() }}{% endif %}

{% if include_reporting %}{{ reporting_requirements(no_empty_reports=suppress_no_violations_line|default(true)) }}{% endif %}

{{ supplemental_section_md(supplemental_text) }}

{% if include_tools %}{{ tools_section(available_tools) }}{% endif %}

{% block body %}{% endblock %}
