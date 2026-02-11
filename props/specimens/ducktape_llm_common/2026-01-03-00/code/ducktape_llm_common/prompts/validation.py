"""Validation utilities for prompts."""

import re
from pathlib import Path

import yaml

from .constants import PROMPT_FILE_EXTENSION
from .loader import discover_prompts, load_prompt


class PromptValidator:
    """Validator for prompt files and content."""

    def __init__(self):
        """Initialize the validator."""
        self.validation_rules = {
            "structure": self._validate_structure,
            "variables": self._validate_variables,
            "metadata": self._validate_metadata,
            "content": self._validate_content,
            "references": self._validate_references,
        }

    def validate_prompt(self, prompt_name: str, rules: list[str] | None = None) -> dict[str, list[str]]:
        """Validate a prompt against specified rules.

        Args:
            prompt_name: Name of the prompt to validate
            rules: Optional list of rules to apply (uses all if None)

        Returns:
            Dictionary mapping rule names to lists of issues found
        """
        if rules is None:
            rules = list(self.validation_rules.keys())

        results = {}

        # Load the prompt content
        try:
            content = load_prompt(prompt_name, use_cache=False)
        except (FileNotFoundError, OSError, UnicodeDecodeError) as e:
            return {"loading": [f"Failed to load prompt: {e}"]}

        # Find the prompt file path
        prompts = discover_prompts()
        prompt_path = prompts.get(prompt_name)

        # Apply each validation rule
        for rule in rules:
            if rule in self.validation_rules:
                issues = self.validation_rules[rule](content, prompt_path)
                if issues:
                    results[rule] = issues

        return results

    def validate_all_prompts(self, rules: list[str] | None = None) -> dict[str, dict[str, list[str]]]:
        """Validate all discovered prompts.

        Args:
            rules: Optional list of rules to apply

        Returns:
            Dictionary mapping prompt names to validation results
        """
        results = {}
        prompts = discover_prompts()

        for prompt_name in prompts:
            validation_result = self.validate_prompt(prompt_name, rules)
            if validation_result:
                results[prompt_name] = validation_result

        return results

    def _validate_structure(self, content: str, prompt_path: Path | None) -> list[str]:
        """Validate the structural elements of a prompt."""
        issues = []

        lines = content.split("\n")

        # Check for headers
        headers = [line for line in lines if line.startswith("#")]
        if not headers:
            issues.append("No headers found - consider adding structure with # headers")

        # Check for empty content
        non_empty_lines = [line for line in lines if line.strip()]
        if len(non_empty_lines) < 5:
            issues.append("Prompt is very short - consider adding more detail")

        # Check for lists
        list_items = [line for line in lines if line.strip().startswith(("-", "*", "1."))]
        if not list_items and len(non_empty_lines) > 10:
            issues.append("No lists found - consider using lists for clarity")

        # Check for code blocks
        if "```" not in content and any(
            keyword in content.lower() for keyword in ["code", "example", "command", "script"]
        ):
            issues.append("Mentions code/commands but no code blocks found")

        return issues

    def _validate_variables(self, content: str, prompt_path: Path | None) -> list[str]:
        """Validate template variables in the prompt."""
        issues = []

        # Find all variables
        format_vars = re.findall(r"\{(\w+)\}", content)
        template_vars = re.findall(r"\$\{?(\w+)\}?", content)
        all_vars = set(format_vars + template_vars)

        if all_vars:
            # Check for common variable patterns
            undefined_vars = []
            for var in all_vars:
                # Check if variable is mentioned elsewhere in the prompt
                if content.count(var) == 1:  # Only appears in template
                    undefined_vars.append(var)

            if undefined_vars:
                issues.append(f"Variables used but not described: {', '.join(sorted(undefined_vars))}")

            # Check for inconsistent variable styles
            if format_vars and template_vars:
                issues.append("Mixed variable styles found - use consistent format ({var} or ${var})")

        return issues

    def _validate_metadata(self, content: str, prompt_path: Path | None) -> list[str]:
        """Validate metadata in the prompt."""
        issues = []

        # Check for frontmatter
        if content.startswith("---"):
            try:
                # Extract frontmatter
                lines = content.split("\n")
                end_index = -1
                for i, line in enumerate(lines[1:], 1):
                    if line.strip() == "---":
                        end_index = i
                        break

                if end_index > 0:
                    frontmatter_lines = lines[1:end_index]
                    frontmatter_text = "\n".join(frontmatter_lines)

                    # Try to parse as YAML
                    try:
                        metadata = yaml.safe_load(frontmatter_text)

                        # Check for recommended fields
                        recommended = ["title", "description", "variables", "category"]
                        missing = [f for f in recommended if f not in metadata]
                        if missing:
                            issues.append(f"Metadata missing recommended fields: {', '.join(missing)}")
                    except yaml.YAMLError as e:
                        issues.append(f"Invalid YAML in frontmatter: {e}")
                else:
                    issues.append("Unclosed frontmatter block")
            except (ValueError, TypeError) as e:
                issues.append(f"Error parsing metadata: {e}")

        return issues

    def _validate_content(self, content: str, prompt_path: Path | None) -> list[str]:
        """Validate the content quality of the prompt."""
        issues = []

        # Check for TODO/FIXME markers
        todo_patterns = ["TODO", "FIXME", "XXX", "HACK", "BUG"]
        for pattern in todo_patterns:
            if pattern in content:
                issues.append(f"Contains {pattern} marker - incomplete prompt?")

        # Check for placeholder text
        placeholder_patterns = [
            "lorem ipsum",
            "placeholder",
            "fill in",
            "to be added",
            "coming soon",
            "[insert",
            "<add",
        ]
        content_lower = content.lower()
        for pattern in placeholder_patterns:
            if pattern in content_lower:
                issues.append(f"Contains placeholder text: '{pattern}'")

        # Check for excessive whitespace
        if "\n\n\n" in content:
            issues.append("Contains excessive blank lines")

        # Check for trailing whitespace
        lines_with_trailing = [i + 1 for i, line in enumerate(content.split("\n")) if line.endswith((" ", "\t"))]
        if lines_with_trailing:
            issues.append(
                f"Trailing whitespace on lines: {lines_with_trailing[:5]}"
                + (" and more" if len(lines_with_trailing) > 5 else "")
            )

        return issues

    def _validate_references(self, content: str, prompt_path: Path | None) -> list[str]:
        """Validate references to other prompts or files."""
        issues = []

        # Check for references to other prompts
        prompt_refs = re.findall(r'(?:see|refer to|load)\s+["\']?(\w+_prompt)["\']?', content, re.IGNORECASE)
        if prompt_refs:
            available_prompts = set(discover_prompts().keys())
            for ref in prompt_refs:
                ref_name = ref.replace("_prompt", "")
                if ref_name not in available_prompts:
                    issues.append(f"References non-existent prompt: '{ref_name}'")

        # Check for file references
        file_refs = re.findall(r'(?:file|path):\s*["\']?([^"\'\s]+)["\']?', content)
        for ref in file_refs:
            if not ref.startswith(("{", "$", "<")):  # Skip variables
                ref_path = Path(ref)
                if ref_path.is_absolute() and not ref_path.exists():
                    issues.append(f"References non-existent file: '{ref}'")

        return issues


def validate_prompt_file(prompt_path: Path) -> list[str]:
    """Validate a prompt file for basic issues.

    Args:
        prompt_path: Path to the prompt file

    Returns:
        List of validation issues
    """
    issues = []

    # Check file exists
    if not prompt_path.exists():
        return ["File does not exist"]

    # Check file extension
    if prompt_path.suffix != PROMPT_FILE_EXTENSION:
        issues.append(f"Wrong file extension - should be {PROMPT_FILE_EXTENSION}")

    # Check file size
    size = prompt_path.stat().st_size
    if size == 0:
        issues.append("File is empty")
    elif size < 100:
        issues.append("File seems too small for a useful prompt")
    elif size > 50000:
        issues.append("File is very large - consider splitting into multiple prompts")

    # Check encoding
    try:
        prompt_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        issues.append("File is not valid UTF-8")

    return issues


def validate_prompt_collection(prompt_dir: Path) -> dict[str, list[str]]:
    """Validate all prompts in a directory.

    Args:
        prompt_dir: Directory containing prompt files

    Returns:
        Dictionary mapping file names to lists of issues
    """
    results = {}

    if not prompt_dir.exists():
        return {"directory": ["Directory does not exist"]}

    if not prompt_dir.is_dir():
        return {"directory": ["Path is not a directory"]}

    # Validate each prompt file
    for prompt_file in prompt_dir.glob(f"*{PROMPT_FILE_EXTENSION}"):
        if prompt_file.name.startswith("_"):
            continue  # Skip private prompts

        issues = validate_prompt_file(prompt_file)
        if issues:
            results[prompt_file.name] = issues

    return results
