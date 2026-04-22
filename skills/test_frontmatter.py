from pathlib import Path

import pytest
import pytest_bazel

from skills.frontmatter_validation import validate_skill_frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"


@pytest.mark.parametrize(
    "skill_path",
    sorted(path for path in SKILLS_DIR.glob("*/SKILL.md") if path.is_file()),
    ids=lambda path: path.parent.name,
)
def test_frontmatter_description_length(skill_path: Path) -> None:
    try:
        validate_skill_frontmatter(skill_path)
    except ValueError as exc:
        raise AssertionError(f"{skill_path}: {exc}") from exc


if __name__ == "__main__":
    pytest_bazel.main()
