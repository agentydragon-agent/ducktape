local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 360-364 build a dictionary using imperative append-style code (initialize
    empty dict, then loop with assignment). This pattern should use a dict comprehension
    for clarity and conciseness:

    Current:
      extra_volumes = {}
      for slug, path in train_specimens.items():
          extra_volumes[str(path.resolve())] = {"bind": f"/snapshots/train/{slug}", "mode": "ro"}

    Preferred:
      extra_volumes = {
          str(path.resolve()): {"bind": f"/snapshots/train/{slug}", "mode": "ro"}
          for slug, path in train_specimens.items()
      }

    Dict comprehensions are more idiomatic Python for building dictionaries from
    iterations, reduce line count, and make the intent clearer.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/prompt_optimizer.py': [[360, 364]],
  },
)
