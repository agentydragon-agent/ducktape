local I = import '../../lib.libsonnet';

// Policy proposal_id: database is int but APIs use str with runtime conversion

I.issueMulti(
  rationale=|||
    Policy proposal_id (models.py:149) database column is int, but all APIs
    accept str and convert with try/except int() at runtime. 13 locations have
    identical conversion logic.

    Using domain types provides:
    - Type safety: can't mix different ID types
    - Semantic clarity: not just any string/int, but specific identifier
    - No runtime conversions/validation
    - Clear type contracts in signatures
  |||,
  occurrences=[
    {
      note: 'Database model uses int for proposal_id',
      files: {
        'adgn/src/adgn/agent/persist/models.py': [149],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/models.py']],
    },
    {
      note: 'SQLite layer converts str to int with try/except',
      files: {
        'adgn/src/adgn/agent/persist/sqlite.py': [223, 259, [280, 289], [311, 321]],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/sqlite.py']],
    },
    {
      note: 'Protocol interface uses str return/param types',
      files: {
        'adgn/src/adgn/agent/persist/__init__.py': [202, 204, 205, 206],
      },
      expect_caught_from: [['adgn/src/adgn/agent/persist/__init__.py']],
    },
    {
      note: 'Approvals module uses str proposal_id',
      files: {
        'adgn/src/adgn/agent/approvals.py': [211, 237, 254],
      },
      expect_caught_from: [['adgn/src/adgn/agent/approvals.py']],
    },
    {
      note: 'MCP tool uses str proposal_id',
      files: {
        'adgn/src/adgn/agent/mcp_bridge/servers/agents.py': [747],
      },
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/servers/agents.py']],
    },
    {
      note: 'Resources module uses str proposal_id',
      files: {
        'adgn/src/adgn/agent/mcp_bridge/resources.py': [67],
      },
      expect_caught_from: [['adgn/src/adgn/agent/mcp_bridge/resources.py']],
    },
  ],
)
