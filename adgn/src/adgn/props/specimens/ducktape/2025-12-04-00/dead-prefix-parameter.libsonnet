local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The `prefix` parameter in both `mount_server()` and `mount_inproc()` is completely dead code with multiple issues:

    **Issue 1: Never passed as non-None**
    A ripgrep search shows all call sites use only two arguments (name and spec/server). No call site ever passes a custom prefix value. The parameter defaults to `None` in all actual usage.

    **Issue 2: Computed value is ignored**
    Both methods compute `prefix = prefix or name` (lines 255 and 284), normalizing the parameter to equal `name`. However, this computed `prefix` variable is then completely ignored! The actual `self.mount()` calls at lines 277 and 302 use `prefix=name` directly, not the computed `prefix` variable.

    **In mount_server (lines 251-278)**:
    - Line 251: `prefix: str | None = None` parameter defined
    - Line 255: `prefix = prefix or name` - computes prefix
    - Line 277: `self.mount(proxy, prefix=name)` - **IGNORES computed prefix, uses name directly**

    **In mount_inproc (lines 280-309)**:
    - Line 280: `prefix: str | None = None` parameter defined
    - Line 284: `prefix = prefix or name` - computes prefix
    - Line 302: `self.mount(proxy, prefix=name)` - **IGNORES computed prefix, uses name directly**

    **The fix**: Remove the `prefix` parameter entirely from both methods and delete lines 255 and 284. The behavior will be identical since prefix always equals name anyway and the computed value is unused.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [
        [251, 251],  // mount_server signature with dead prefix parameter
        [255, 255],  // Computed but ignored prefix assignment
        [277, 277],  // self.mount call that ignores computed prefix
      ]},
      note: 'mount_server: prefix parameter and computation are dead code',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/compositor/server.py': [
        [280, 280],  // mount_inproc signature with dead prefix parameter
        [284, 284],  // Computed but ignored prefix assignment
        [302, 302],  // self.mount call that ignores computed prefix
      ]},
      note: 'mount_inproc: prefix parameter and computation are dead code',
      expect_caught_from: [['adgn/src/adgn/mcp/compositor/server.py']],
    },
  ],
)
