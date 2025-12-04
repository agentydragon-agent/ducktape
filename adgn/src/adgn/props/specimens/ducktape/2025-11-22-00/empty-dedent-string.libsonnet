local I = import '../../lib.libsonnet';

// iss-040: Empty dedent string creates useless constant

I.issue(
  rationale= |||
    The `_APPROVALS_AND_TOOLS` constant is defined as `dedent("").strip()`, which
    always evaluates to an empty string. This creates dead code and adds unnecessary
    string concatenation overhead.

    **Problem: Empty string processed as if it contains content**

    **Current implementation (system_message.py, lines 27-28):**
    ```python
    # Tooling and approvals behavior as surfaced in the UI
    _APPROVALS_AND_TOOLS = dedent("").strip()
    ```

    **Then used in composition (system_message.py, line 56):**
    ```python
    def get_ui_system_message() -> str:
        """Return composed system message for HTML UI agent.

        Pure function; no environment or storage reads. Update constants above to
        change behavior.
        """
        return "\n\n".join([_BASE, _APPROVALS_AND_TOOLS, _OUTPUT_STYLE, _HOUSE_RULES])
    ```

    **Why this is problematic:**

    1. **Dead constant**: `dedent("").strip()` is always `""`, no processing needed
    2. **Unnecessary join**: `"\n\n".join([a, "", c, d])` produces `"a\n\nc\n\nd"` with no benefit from empty element
    3. **Misleading code**: Suggests content exists or will be added later
    4. **String allocation waste**: Minimal, but still allocates and processes empty string
    5. **Extra newlines**: When join includes empty strings, you get `"\n\n"` separators even where no content exists

    **The correct approach:**

    Remove the empty constant entirely:

    ```python
    # Core, short instructions tailored to the web UI experience
    _BASE = dedent(
        """
        You are a code agent operating via a web chat UI.
        - Be concise and actionable. Prefer bullet points over long prose.
        - Use tools when appropriate and clearly label what was executed.
        - When returning code, use fenced blocks with language hints (```python).
        """
    ).strip()

    # Remove: _APPROVALS_AND_TOOLS = dedent("").strip()

    # Output format expectations consistent with UI renderers (markdown + terminals)
    _OUTPUT_STYLE = dedent(
        """
        Use Markdown formatting as appropriate - fenced code blocks, inline code
        (for inline variables, filesystem paths and other short code), emphasis,
        tables, headings, etc.
        """
    ).strip()

    # House rules to keep turns efficient
    _HOUSE_RULES = dedent(
        """
        House rules
        - Ask targeted clarification questions when requirements are ambiguous.
        - Avoid speculative fixes; verify by reading available files or running tools.
        - Fail fast on programming errors; do not hide exceptions behind generic text.
        """
    ).strip()


    def get_ui_system_message() -> str:
        """Return composed system message for HTML UI agent.

        Pure function; no environment or storage reads. Update constants above to
        change behavior.
        """
        return "\n\n".join([_BASE, _OUTPUT_STYLE, _HOUSE_RULES])
    ```

    **Why this pattern happened:**

    Likely evolution:
    1. Started with content in `_APPROVALS_AND_TOOLS`
    2. Content was removed/moved elsewhere
    3. Constant was left as empty placeholder "in case we need it later"
    4. Empty string kept in join list

    **When to keep placeholder constants:**

    Empty constants are acceptable when:
    - Loaded from external source that might be empty (file, config, env var)
    - Computed dynamically based on runtime conditions
    - Part of plugin/extension point where content might be injected

    **Not acceptable when:**
    - Hardcoded as literal empty string `""`
    - Result of `dedent("")` or similar no-op transformations
    - No clear path to non-empty value
    - Just "might add content later" thinking

    **Related cleanup:**

    Check if other similar patterns exist:
    ```python
    # Other potential issues:
    parts = [header, "", footer]  # Why the empty string?
    text = sep.join([a, "", c])   # Does "" add value?
    config = {"key": None}        # Is None key used?
    ```

    **Performance consideration:**

    While `dedent("").strip()` is trivial overhead (empty string operations are cheap),
    it's still unnecessary work:
    - `dedent("")` allocates a new string
    - `.strip()` creates another string
    - `join` includes it in the list
    - Final string concatenation processes it

    The real issue is code clarity: why does this exist?

    **Migration:**

    1. Remove `_APPROVALS_AND_TOOLS` definition
    2. Remove it from `join()` list
    3. Verify output is identical (except for removing double newlines from empty content)
    4. Update tests if they hardcode expected output

    **Alternative: If content is truly coming later**

    If approvals/tools documentation is planned and just not implemented yet:
    ```python
    # TODO(username): Add approvals/tools documentation when policy UI is complete
    _APPROVALS_AND_TOOLS = ""  # Planned: describe approval flow

    def get_ui_system_message() -> str:
        parts = [_BASE, _OUTPUT_STYLE, _HOUSE_RULES]
        if _APPROVALS_AND_TOOLS:
            parts.insert(1, _APPROVALS_AND_TOOLS)
        return "\n\n".join(parts)
    ```

    But this should have a clear TODO with owner and reason, not just an empty placeholder.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/system_message.py': [
      [28, 28],   // dedent("").strip() creates empty constant
      [56, 56],   // Empty constant included in join
    ],
  },
)
