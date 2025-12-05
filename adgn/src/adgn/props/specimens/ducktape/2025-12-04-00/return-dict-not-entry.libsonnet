local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The get_tree_files function returns dict[str, tuple[pygit2.Oid, int]], forcing callers
    to destructure tuples when they need the oid or filemode. It should instead return
    dict[Path, pygit2.TreeEntry] (where Path is the key type, not str). This gives callers
    direct access to the TreeEntry object with its oid and filemode attributes, avoiding
    tuple unpacking. The prefix parameter should remain str for composition purposes.
  |||,
  filesToRanges={'adgn/src/adgn/props/cli_app/cmd_build_bundle.py': [[47, 62]]},
)
