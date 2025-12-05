local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 139-140 and 155-156 extract mcp_config_obj and immediately use it once to
    create uvicorn.Server. This single-use intermediate variable should be inlined.

    Pattern at both locations: create Config, assign to mcp_config_obj, pass to Server
    constructor. Variable name adds no semantic clarity beyond the constructor call itself.

    Inline to: uvicorn.Server(uvicorn.Config(app=mcp_app, host=host, port=mcp_port,
    log_level="info")). Still readable because parameters are self-documenting and
    nesting is clear. Standard pattern: Config is just a parameter to Server, no need
    to name it separately unless reused.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/mcp_bridge/cli.py': [
      [139, 141],  // mcp_config_obj in single-agent mode
      [155, 158],  // mcp_config_obj in multi-agent mode
    ],
  },
)
