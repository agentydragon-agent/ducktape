local I = import '../../specimens/lib.libsonnet';

// iss-062: Fold config file read/parse/validate into pathlib oneliner
I.issueOneOccurrence(
  rationale='Fold file/read/parse/validate into a concise pathlib oneliner using Pydantic model_validate: `config_file = ConfigFile.model_validate(yaml.safe_load(config_path.read_text()))`; handle ValidationError as before. Suggested rewrite: `config_file = ConfigFile.model_validate(yaml.safe_load(config_path.read_text()))` (keep try/except ValidationError handling).',
  // properties=['pathlib'],
  filesToRanges={
    'wt/wt/shared/configuration.py': [[126, 132]],
  },
)
