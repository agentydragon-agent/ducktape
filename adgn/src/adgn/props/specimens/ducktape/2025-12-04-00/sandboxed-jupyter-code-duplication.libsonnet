local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    The sandboxed_jupyter module contains multiple instances of duplicated code that should be consolidated into shared implementations.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/sandboxed_jupyter/launch.py': [[22, 26]]},
      note: 'Duplicate _pick_free_port function - canonical implementation exists in adgn.util.net.pick_free_port',
      expect_caught_from: [['adgn/src/adgn/mcp/sandboxed_jupyter/launch.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [[193, 196]]},
      note: 'Duplicate _pick_free_port function - canonical implementation exists in adgn.util.net.pick_free_port',
      expect_caught_from: [['adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py']],
    },
    {
      files: {
        'adgn/src/adgn/mcp/sandboxed_jupyter/launch.py': [[29, 80]],
        'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [[199, 249]],
      },
      note: 'Duplicate _start_jupyter_server implementations with nearly identical jupyter server command construction',
      expect_caught_from: [
        ['adgn/src/adgn/mcp/sandboxed_jupyter/launch.py', 'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py'],
      ],
    },
    {
      files: {
        'adgn/src/adgn/mcp/sandboxed_jupyter/launch.py': [[142, 161]],
        'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py': [[85, 93], [305, 324]],
      },
      note: 'Duplicate jupyter-mcp-server command construction in three places (Python and bash)',
      expect_caught_from: [
        ['adgn/src/adgn/mcp/sandboxed_jupyter/launch.py', 'adgn/src/adgn/mcp/sandboxed_jupyter/wrapper.py'],
      ],
    },
  ],
)
