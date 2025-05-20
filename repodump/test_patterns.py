import pytest

from .patterns import path_match, path_pattern_to_regex


def test_path_pattern_to_regex_basic():
    """
    Verify the single '*' doesn't cross directories and '?' matches exactly one char.
    """
    # "boxes/*.py" => matches "boxes/foo.py", not "boxes/subdir/bar.py"
    pattern = path_pattern_to_regex("boxes/*.py")
    assert pattern.match("boxes/foo.py")
    assert not pattern.match("boxes/subdir/bar.py")

    # Single '?' => one non-slash character
    # "src/?.py" => matches "src/a.py" or "src/b.py",
    # but not "src/abc.py" or "src//.py"
    pat_q = path_pattern_to_regex("src/?.py")
    assert pat_q.match("src/a.py")
    assert pat_q.match("src/x.py")
    assert not pat_q.match("src/abc.py")
    assert not pat_q.match("src/.py")


def test_path_pattern_to_regex_doublestar():
    """
    Verify '**' crosses subdirectories.
    """
    # "boxes/**/*.py" => matches deeper subdirs
    pattern = path_pattern_to_regex("boxes/**/*.py")
    assert pattern.match("boxes/foo.py")  # zero subdirectories
    assert pattern.match("boxes/sub/bar.py")  # one level
    assert pattern.match("boxes/sub/deeper/thing.py")  # multiple levels
    assert not pattern.match("stuff/boxes/foo.py")  # doesn't start with boxes/
    assert not pattern.match("boxes/foo.pyc")  # extension mismatch


def test_path_pattern_to_regex_mixed_segments():
    """
    Mixed usage: "boxes/*/bar/*.py" => exactly one subdir after boxes, then "bar" dir, then .py
    """
    pattern = path_pattern_to_regex("boxes/*/bar/*.py")
    # Should match "boxes/something/bar/test.py"
    assert pattern.match("boxes/something/bar/test.py")
    # Should not match if there's an extra subdir
    assert not pattern.match("boxes/something/bar/extra/test.py")
    # Should not match if missing "bar"
    assert not pattern.match("boxes/something/else/test.py")


@pytest.mark.parametrize(
    "pattern,path,should_match",
    [
        # Single star won't cross subdir
        ("boxes/*.py", "boxes/foo.py", True),
        ("boxes/*.py", "boxes/subdir/foo.py", False),
        # Double star does cross
        ("boxes/**/*.py", "boxes/foo.py", True),
        ("boxes/**/*.py", "boxes/subdir/foo.py", True),
        # If pattern has no slash => automatically prepends **/
        ("*.md", "readme.md", True),  # top-level
        ("*.md", "example/readme.md", True),  # subdir
        ("*.md", "example/subdir/readme.md", True),
        ("*.md", "example/subdir/readme.txt", False),
        # '?' => single char
        ("boxes/?.py", "boxes/a.py", True),
        ("boxes/?.py", "boxes/abc.py", False),
    ],
)
def test_path_match(pattern, path, should_match):
    result = path_match(path, [pattern])
    assert result == should_match, (
        f"{pattern=} with {path=} => {result}, expected {should_match}"
    )


def test_multiple_patterns():
    """
    If any pattern matches => True.
    """
    pats = ["boxes/*.py", "*.md"]
    # "boxes/foo.py" => matches first pattern
    assert path_match("boxes/foo.py", pats)
    # "example/readme.md" => matches second pattern (since no slash => auto **/*.md)
    assert path_match("example/readme.md", pats)

    # "nothing.jpg" => neither pattern => false
    assert not path_match("nothing.jpg", pats)
