local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 293-301 type the snapshot parameter as nullable (`specimen_str: str | None`)
    but immediately check for None and exit with an error. This is a misleading type
    signature that should be replaced with a required parameter, and checking for presence
    should be left up to Typer.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/cli_app/cmd_detector.py': [[293, 301]],
  },
)
