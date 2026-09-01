from pathlib import Path


def test_capture_production_sources_do_not_import_haku() -> None:
    root = Path(__file__).parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text()
        if "import haku" in text or "from haku" in text:
            offenders.append(path.relative_to(root).as_posix())
    assert offenders == []


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()
