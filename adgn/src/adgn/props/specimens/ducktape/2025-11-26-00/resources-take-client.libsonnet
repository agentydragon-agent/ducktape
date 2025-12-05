local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 238-241 create `Client(compositor)` internally, but resources server should receive Client as parameter instead of Compositor.

    Violates "take what you need" principle (Dependency Injection): (1) server receives Compositor but only uses it to create Client, (2) creates client internally instead of receiving it, (3) harder to test (can't inject mock/test client).

    Change signature to `make_resources_server(name: str, client: Client)` and use client directly. Caller creates Client and passes it. Delete useless comments about "bypassing policy gateway" (lines 238-240); parameter docstring should explain this instead. Benefits: takes what it needs, easier to test, clearer dependencies, follows standard DI.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/resources/server.py': [
      [238, 241],  // Creates Client internally, should receive it
    ],
  },
)
