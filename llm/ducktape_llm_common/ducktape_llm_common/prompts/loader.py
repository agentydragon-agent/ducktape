"""Enhanced prompt loading and discovery system.

This module provides advanced features for prompt management including
discovery, validation, template support, and error handling.
"""

import re
from pathlib import Path
from string import Template
from typing import Any


class PromptError(Exception):
    """Base exception for prompt-related errors."""


class PromptNotFoundError(PromptError):
    """Raised when a requested prompt cannot be found."""


class PromptValidationError(PromptError):
    """Raised when a prompt fails validation."""


class PromptVariableError(PromptError):
    """Raised when there are issues with prompt variables."""


class PromptLoader:
    """Advanced prompt loader with caching, validation, and template support."""

    def __init__(self, prompt_dirs: list[Path] | None = None):
        """Initialize the prompt loader.

        Args:
            prompt_dirs: Optional list of directories to search for prompts.
                        If None, uses default locations.
        """
        if prompt_dirs is None:
            # Default locations
            package_dir = Path(__file__).parent
            self.prompt_dirs = [
                package_dir,  # Package prompts
                Path.home() / ".ducktape" / "prompts",  # User prompts
                Path.cwd() / ".prompts",  # Project prompts
            ]
        else:
            self.prompt_dirs = prompt_dirs

        self._cache: dict[str, str] = {}
        self._discovered_prompts: dict[str, Path] | None = None

    def discover_prompts(self, force_refresh: bool = False) -> dict[str, Path]:
        """Discover all available prompts across all prompt directories.

        Args:
            force_refresh: Force refresh of the prompt discovery cache

        Returns:
            Dictionary mapping prompt names to their file paths
        """
        if self._discovered_prompts is not None and not force_refresh:
            return self._discovered_prompts

        prompts = {}

        for prompt_dir in self.prompt_dirs:
            if not prompt_dir.exists():
                continue

            # Find all .md files
            for prompt_file in prompt_dir.glob("*.md"):
                if prompt_file.name.startswith("_"):
                    # Skip private prompts
                    continue

                prompt_name = prompt_file.stem

                # Later directories override earlier ones
                prompts[prompt_name] = prompt_file

        self._discovered_prompts = prompts
        return prompts

    def list_prompts(self, include_paths: bool = False) -> list[str] | list[tuple[str, str]]:
        """List all available prompts.

        Args:
            include_paths: If True, returns tuples of (name, path)

        Returns:
            List of prompt names or tuples of (name, path)
        """
        prompts = self.discover_prompts()

        if include_paths:
            return [(name, str(path)) for name, path in sorted(prompts.items())]
        return sorted(prompts.keys())

    def load_prompt(
        self,
        prompt_name: str,
        variables: dict[str, Any] | None = None,
        allow_missing_vars: bool = False,
        use_cache: bool = True,
    ) -> str:
        """Load a prompt with advanced template support.

        Args:
            prompt_name: Name of the prompt (without .md extension)
            variables: Optional dictionary of variables to substitute
            allow_missing_vars: If True, missing variables are left as placeholders
            use_cache: If True, uses cached prompts when available

        Returns:
            The processed prompt content

        Raises:
            PromptNotFoundError: If the prompt doesn't exist
            PromptVariableError: If required variables are missing
        """
        # Check cache
        if use_cache and prompt_name in self._cache and variables is None:
            return self._cache[prompt_name]

        # Find the prompt file
        prompts = self.discover_prompts()
        if prompt_name not in prompts:
            available = ", ".join(sorted(prompts.keys()))
            raise PromptNotFoundError(f"Prompt '{prompt_name}' not found. Available prompts: {available}")

        prompt_path = prompts[prompt_name]

        # Load the prompt content
        try:
            content = prompt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise PromptError(f"Failed to read prompt '{prompt_name}': {e}") from e

        # Cache the raw content
        if use_cache:
            self._cache[prompt_name] = content

        # Process variables if provided
        if variables:
            content = self._process_variables(content, variables, allow_missing_vars, prompt_name)

        return content

    def _process_variables(self, content: str, variables: dict[str, Any], allow_missing: bool, prompt_name: str) -> str:
        """Process template variables in prompt content.

        Supports multiple template formats:
        - Python format strings: {variable}
        - Template strings: $variable or ${variable}
        - Custom delimiters: {{variable}}
        """
        # Try Python format strings first
        try:
            return content.format(**variables)
        except KeyError as e:
            if not allow_missing:
                missing_var = str(e).strip("'")
                raise PromptVariableError(f"Missing required variable '{missing_var}' in prompt '{prompt_name}'") from e

        # Fall back to Template for more flexible substitution
        try:
            template = Template(content)
            if allow_missing:
                # Use safe_substitute to leave missing variables as-is
                return template.safe_substitute(**variables)
            return template.substitute(**variables)
        except KeyError as e:
            missing_var = str(e).strip("'")
            raise PromptVariableError(f"Missing required variable '{missing_var}' in prompt '{prompt_name}'") from e

    def validate_prompt(self, prompt_name: str) -> list[str]:
        """Validate a prompt for common issues.

        Args:
            prompt_name: Name of the prompt to validate

        Returns:
            List of validation warnings/errors (empty if valid)
        """
        issues = []

        try:
            content = self.load_prompt(prompt_name, use_cache=False)
        except PromptNotFoundError:
            return [f"Prompt '{prompt_name}' not found"]
        except (OSError, UnicodeDecodeError) as e:
            return [f"Failed to load prompt: {e}"]

        # Check for common issues

        # 1. Check for unmatched variables
        format_vars = re.findall(r"\{(\w+)\}", content)
        template_vars = re.findall(r"\$\{?(\w+)\}?", content)
        all_vars = set(format_vars + template_vars)

        if all_vars:
            issues.append(
                f"Found template variables: {', '.join(sorted(all_vars))}. "
                "Make sure to provide these when loading the prompt."
            )

        # 2. Check for very short prompts
        if len(content.strip()) < 50:
            issues.append("Prompt seems very short. Consider adding more detail.")

        # 3. Check for missing structure
        if not any(marker in content for marker in ["#", "##", "###", "-", "*", "1."]):
            issues.append("Prompt lacks structure (no headers or lists detected)")

        # 4. Check for TODO/FIXME markers
        if "TODO" in content or "FIXME" in content:
            issues.append("Prompt contains TODO/FIXME markers")

        return issues

    def get_prompt_metadata(self, prompt_name: str) -> dict[str, Any]:
        """Extract metadata from a prompt file.

        Looks for YAML frontmatter or special comment blocks.

        Args:
            prompt_name: Name of the prompt

        Returns:
            Dictionary of metadata (empty if none found)
        """
        try:
            content = self.load_prompt(prompt_name, use_cache=False)
        except (OSError, UnicodeDecodeError, PromptNotFoundError):
            return {}

        metadata = {}

        # Check for YAML frontmatter
        if content.startswith("---"):
            lines = content.split("\n")
            end_index = -1
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    end_index = i
                    break

            if end_index > 0:
                # Parse the frontmatter (simplified - real implementation would use YAML)
                for line in lines[1:end_index]:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip()

        # Check for special comments
        for line in content.split("\n"):
            if line.startswith("<!-- ") and line.endswith(" -->"):
                comment = line[5:-4].strip()
                if ":" in comment:
                    key, value = comment.split(":", 1)
                    metadata[key.strip()] = value.strip()

        return metadata

    def clear_cache(self) -> None:
        """Clear all cached prompts."""
        self._cache.clear()
        self._discovered_prompts = None


# Global prompt loader instance
_default_loader = PromptLoader()


def discover_prompts(force_refresh: bool = False) -> dict[str, Path]:
    """Discover all available prompts.

    Args:
        force_refresh: Force refresh of the discovery cache

    Returns:
        Dictionary mapping prompt names to their paths
    """
    return _default_loader.discover_prompts(force_refresh)


def list_prompts(include_paths: bool = False) -> list[str] | list[tuple[str, str]]:
    """List all available prompts.

    Args:
        include_paths: If True, include file paths in the output

    Returns:
        List of prompt names or tuples of (name, path)
    """
    return _default_loader.list_prompts(include_paths)


def load_prompt(
    prompt_name: str, variables: dict[str, Any] | None = None, allow_missing_vars: bool = False, use_cache: bool = True
) -> str:
    """Load a prompt by name with variable substitution.

    Args:
        prompt_name: Name of the prompt to load
        variables: Optional variables to substitute
        allow_missing_vars: If True, missing variables are left as placeholders

    Returns:
        The processed prompt content

    Raises:
        PromptNotFoundError: If the prompt doesn't exist
        PromptVariableError: If required variables are missing
    """
    return _default_loader.load_prompt(prompt_name, variables, allow_missing_vars, use_cache)


def validate_prompt(prompt_name: str) -> list[str]:
    """Validate a prompt for common issues.

    Args:
        prompt_name: Name of the prompt to validate

    Returns:
        List of validation issues (empty if valid)
    """
    return _default_loader.validate_prompt(prompt_name)


def get_prompt_metadata(prompt_name: str) -> dict[str, Any]:
    """Get metadata for a prompt.

    Args:
        prompt_name: Name of the prompt

    Returns:
        Dictionary of metadata
    """
    return _default_loader.get_prompt_metadata(prompt_name)


def clear_prompt_cache() -> None:
    """Clear the global prompt cache."""
    _default_loader.clear_cache()
