import re


def path_pattern_to_regex(pat: str) -> re.Pattern:
    """
    Convert a shell-like path pattern into a regex, with these rules:
      1) If the pattern has NO slash => treat it as if "**/" was prepended
         (so "*.md" becomes "**/*.md"), meaning it can match at any directory level.
      2) A single '*' does NOT cross directories. We interpret '*' as [^/]*,
         '?' as [^/], and '**' as a multi-directory wildcard.
         - '**' => match zero or more subdirectories (including possibly none).
    Examples:
      "boxes/*.py" => only matches "boxes/foo.py" at exactly one level,
                      not "boxes/subdir/bar.py".
      "boxes/**/*.py" => matches deeper subdirs too.
      "*.md" => matches "readme.md" or "example/readme.md" at any depth.
    """

    # If no slash in the pattern, treat it as matching any subdirectory
    # e.g. "*.md" => "**/*.md"
    if "/" not in pat:
        pat = "**/" + pat

    segments = pat.split("/")
    regex_parts = []

    for _i, seg in enumerate(segments):
        if seg == "**":
            # '**' => zero or more directories, so:
            # This means "match 0 or more segments of the form 'something/'"
            # We'll use a capturing group like '(?:[^/]*/)*', but also allow ZERO of them (so it's optional).
            # In regex: (?:[^/]*/)* => matches "dir/" repeated. For zero occurrences, we prefix (?: ... )?
            # We'll do: '(?:[^/]+/)*' but also allow empty => '(?:[^/]+/)*'?
            # Actually we can allow zero with a question mark? We can do:
            #   '(?:[^/]*/)*' means "any # of subdirectories". That already allows zero times, because it's '*'
            # So let's do:
            regex_parts.append("(?:[^/]*/)*")
        else:
            # For normal segments, interpret '*' and '?' in a single directory
            seg_escaped = re.escape(seg)
            # Re‐interpret escaped `\*` => [^/]*, `\?` => [^/]
            seg_escaped = seg_escaped.replace("\\*", "[^/]*")
            seg_escaped = seg_escaped.replace("\\?", "[^/]")
            # This segment must match exactly once at this directory level
            regex_parts.append(seg_escaped)

        # If this isn't the last segment, AND the current segment isn't '**',
        # we need to require a slash afterward. Because "boxes/*.py" => "boxes/" plus filename.
        # But if segment == '**', we've already allowed multiple subdirs, so the next segment
        # might come immediately after the subdirs. We'll handle that by inserting a slash if next segment
        # isn't empty. Actually let's wait and insert slashes in a second pass: we can do it right here though:

        # We'll do it in the final join. The logic is simpler if we keep them separate and join with no slash,
        # because we already embedded slash in the '**' pattern. Let's do a different approach:
        # We'll store them in a list, then combine at the end.

    # Now we combine them. We must ensure that consecutive normal segments
    # are joined by a slash. Meanwhile, consecutive '**' segments are effectively ".*" expansions.

    # Actually, simpler approach: We just join them with a slash, except if the segment is the
    # '.*' from above. But we used a direct insertion of '(?:[^/]*/)*' with no slash needed.
    #
    # So let's do something like this: we already appended for each segment. We just do a "look at the next segment" approach. But let's keep it simpler:
    #
    # We'll do:
    #   '^' + ''.join(...) + '$'
    # Because each segment is either '(?:[^/]*/)*' or a literal pattern that doesn't contain a slash. We do need an actual slash if we see a normal segment that isn't the last one.
    #
    # Let's do it in a single pass building a single string. We'll rewrite:

    # We'll do a second pass now that we have regex_parts in an array, but we don't know which are subdir expansions or normal segments. Let's just do it in one pass:

    # Instead, let's rewrite the code so we build up the final regex in one pass.

    # We'll do the simpler approach: create a function that assembles them:

    return _assemble_pattern_regex(segments)


def _assemble_pattern_regex(segs):
    """
    Turn the list of segments (with '**' or normal) into a single regex
    that matches the entire path from start to finish.
    """
    regex = "^"
    for i, seg in enumerate(segs):
        if seg == "**":
            # zero or more subdirs:
            regex += "(?:[^/]*/)*"
        else:
            # normal segment
            seg_escaped = re.escape(seg)
            seg_escaped = seg_escaped.replace("\\*", "[^/]*")
            seg_escaped = seg_escaped.replace("\\?", "[^/]")
            # add that segment
            regex += seg_escaped

            # if not last segment, add a slash
            if i < len(segs) - 1:
                # look ahead: if the next seg is '**', we do no slash,
                # because '**' begins with '.*' pattern that can handle its own slash
                if segs[i + 1] != "**":
                    regex += "/"
    regex += "$"
    return re.compile(regex)


def path_match(rel_path: str, patterns) -> bool:
    """
    Return True if rel_path matches any pattern from 'patterns',
    using the above custom logic that:
      - '*' doesn't cross dirs
      - '**' crosses any number of dirs
      - no slash => automatically means '**/' prepended
    """
    for pat in patterns:
        r = path_pattern_to_regex(pat)
        if r.match(rel_path):
            return True
    return False
