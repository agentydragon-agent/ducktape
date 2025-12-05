local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 380 converts self.workspace_path (str) to Path, but this field should already be typed as Path at the class definition level. The conversion is redundant if the model properly validates the field type on construction.
  |||,
  filesToRanges={'adgn/src/adgn/inop/engine/models.py': [380]},
)
