local I = import '../../specimens/lib.libsonnet';

// iss-021: Use pathlib for path writes (avoid open(...))
I.issueOneOccurrence(
  rationale=|||
    Use pathlib API to reduce this to a oneliner: `config_path.write_text(yaml.dump(config_file.model_dump()))`.
    (This may not be appropriate in huge or perf-critical cases as it loads the whole file into a str, but neither of these are the case here.)
  |||,
  // properties=['pathlib'],
  filesToRanges={
    'wt/tests/conftest.py': [[422, 423]],
  },
)
