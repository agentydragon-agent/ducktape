local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 27 in transcript_handler.py contains a false comment: "The parent directory must already exist
    (created by run managers)." This is contradicted by lines 36-37 which explicitly create the parent
    directory with `mkdir(parents=True, exist_ok=True)`. The comment should be removed as it's inaccurate.
  |||,
  filesToRanges={'adgn/src/adgn/agent/transcript_handler.py': [27]},
)
