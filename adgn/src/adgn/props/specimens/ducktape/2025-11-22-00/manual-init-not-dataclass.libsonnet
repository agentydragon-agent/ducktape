local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Class (container.py:17-46) uses manual `__init__` for simple field
    initialization. The constructor does assignment-only initialization
    with no complex logic, perfect candidate for `@dataclass`.

    Benefits of dataclass: less boilerplate (no manual assignments), free
    `__repr__` for debugging, free `__eq__` for testing, type annotations
    serve as field declarations, standard Python idiom for data-holding
    classes. Use `__post_init__` if complex initialization needed.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/container.py': [
      [17, 46],  // Manual __init__ instead of @dataclass
    ],
  },
)
