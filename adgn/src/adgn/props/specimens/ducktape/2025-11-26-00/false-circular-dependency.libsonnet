local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 179-182 have inline imports with comment claiming "circular dependency with registry setup", but no circular dependency exists. Investigation shows mcp_bridge modules do NOT import from app.py.

    Move imports to top of file (standard import organization), delete misleading comment, remove noqa PLC0415 suppressions. If a circular dependency actually existed, the correct fix would be architecture refactoring, not hidden inline imports.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [179, 182],  // Misleading circular dependency comment and inline imports
    ],
  },
)
