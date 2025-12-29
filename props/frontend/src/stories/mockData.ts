// Mock data for Storybook stories
// Using generated schema types for type safety

import type { components } from '../lib/api/schema';

type OverviewResponse = components['schemas']['OverviewResponse'];
type SnapshotDetailResponse = components['schemas']['SnapshotDetailResponse'];
type FileTreeResponse = components['schemas']['FileTreeResponse'];
type SnapshotSummary = components['schemas']['SnapshotSummary'];

export const mockOverview: OverviewResponse = {
  definitions: [
    {
      definition_id: 'def-001',
      created_at: '2025-01-15T10:00:00Z',
      stats: {
        train: {
          whole_snapshot: {
            recall_stats: { n: 10, mean: 0.75, min: 0.5, max: 1.0, lcb95: 0.65, ucb95: 0.85 },
            n_examples: 10,
            zero_count: 1,
            status_counts: { completed: 8, in_progress: 2 },
            total_available: 45,
          },
        },
        valid: {
          whole_snapshot: {
            recall_stats: { n: 5, mean: 0.68, min: 0.4, max: 0.9, lcb95: 0.55, ucb95: 0.81 },
            n_examples: 5,
            zero_count: 0,
            status_counts: { completed: 5 },
            total_available: 8,
          },
        },
      },
    },
    {
      definition_id: 'def-002',
      created_at: '2025-01-10T14:30:00Z',
      stats: {
        train: {
          file_set: {
            recall_stats: { n: 15, mean: 0.82, min: 0.6, max: 1.0, lcb95: 0.75, ucb95: 0.89 },
            n_examples: 15,
            zero_count: 2,
            status_counts: { completed: 15 },
            total_available: 23,
          },
        },
      },
    },
    {
      definition_id: 'def-003',
      created_at: '2025-01-01T00:00:00Z',
      stats: {},
    },
  ],
  example_counts: {
    train: { whole_snapshot: 45, file_set: 23 },
    valid: { whole_snapshot: 8, file_set: 4 },
  },
  total_definitions: 3,
};

export const mockSnapshotDetail: SnapshotDetailResponse = {
  slug: 'project/snapshot-v1',
  split: 'test',
  created_at: '2025-01-10T14:00:00Z',
  true_positives: [
    {
      tp_id: 'tp-001',
      rationale: 'SQL injection vulnerability in user input handling',
      occurrences: [
        {
          occurrence_id: 'occ-tp-001',
          files: [{ path: 'src/db/queries.py', ranges: [{ start_line: 45, end_line: 50, note: null }] }],
          note: 'Direct string concatenation with user input',
          critic_scopes_expected_to_recall: [['security', 'sql-injection']],
          graders_match_only_if_reported_on: null,
        },
      ],
      created_at: '2025-01-10T14:00:00Z',
    },
    {
      tp_id: 'tp-002',
      rationale: 'XSS vulnerability in template rendering',
      occurrences: [
        {
          occurrence_id: 'occ-tp-002',
          files: [{ path: 'templates/user_profile.html', ranges: [{ start_line: 23, end_line: 25, note: null }] }],
          note: null,
          critic_scopes_expected_to_recall: [['security', 'xss']],
          graders_match_only_if_reported_on: null,
        },
      ],
      created_at: '2025-01-10T14:00:00Z',
    },
  ],
  false_positives: [
    {
      fp_id: 'fp-001',
      rationale: 'Flagged as SQL injection but uses parameterized queries',
      occurrences: [
        {
          occurrence_id: 'occ-fp-001',
          files: [{ path: 'src/db/safe_queries.py', ranges: [{ start_line: 67, end_line: 70, note: null }] }],
          note: 'Actually safe - uses ORM query builder',
          relevant_files: ['src/db/models.py'],
          graders_match_only_if_reported_on: null,
        },
      ],
      created_at: '2025-01-10T14:00:00Z',
    },
  ],
};

export const mockSnapshotTree: FileTreeResponse = {
  tree: [
    {
      name: 'src',
      path: 'src',
      is_dir: true,
      tp_count: 2,
      fp_count: 1,
      children: [
        {
          name: 'db',
          path: 'src/db',
          is_dir: true,
          tp_count: 1,
          fp_count: 1,
          children: [
            { name: 'queries.py', path: 'src/db/queries.py', is_dir: false, tp_count: 1, fp_count: 0 },
            { name: 'safe_queries.py', path: 'src/db/safe_queries.py', is_dir: false, tp_count: 0, fp_count: 1 },
          ],
        },
      ],
    },
    {
      name: 'templates',
      path: 'templates',
      is_dir: true,
      tp_count: 1,
      fp_count: 0,
      children: [
        {
          name: 'user_profile.html',
          path: 'templates/user_profile.html',
          is_dir: false,
          tp_count: 1,
          fp_count: 0,
        },
      ],
    },
  ],
};

export const mockSnapshotsList: SnapshotSummary[] = [
  {
    slug: 'project/snapshot-v1',
    split: 'test',
    tp_count: 24,
    fp_count: 3,
    created_at: '2025-01-15T10:00:00Z',
  },
  {
    slug: 'project/snapshot-v0',
    split: 'valid',
    tp_count: 18,
    fp_count: 2,
    created_at: '2025-01-10T14:30:00Z',
  },
  {
    slug: 'baseline/snapshot',
    split: 'train',
    tp_count: 156,
    fp_count: 12,
    created_at: '2025-01-01T00:00:00Z',
  },
];

type ExampleDetailResponse = components['schemas']['ExampleDetailResponse'];
type FileContentResponse = components['schemas']['FileContentResponse'];
type TpInfo = components['schemas']['TpInfo'];
type FpInfo = components['schemas']['FpInfo'];
type GradingEdgeInfo = components['schemas']['GradingEdgeInfo'];
type ReportedIssueInfo = components['schemas']['ReportedIssueInfo'];

// Component-level mock data for FileViewer and CritiqueFileViewer

export const mockSnapshotSlug = 'example/snapshot-v1';

export const mockFileContent: FileContentResponse = {
  path: 'src/db/queries.py',
  content: `import sqlite3
from typing import Optional

def get_user(user_id: str) -> Optional[dict]:
    """Fetch a user by ID."""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    # WARNING: SQL injection vulnerability - user_id not sanitized
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    cursor.execute(query)

    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None

def get_user_safe(user_id: str) -> Optional[dict]:
    """Fetch a user by ID using parameterized query."""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()

    # Safe: uses parameterized query
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None
`,
  line_count: 32,
};

export const mockFileTps: TpInfo[] = [
  {
    tp_id: 'tp-sql-injection-001',
    rationale: 'SQL injection vulnerability: user input is directly interpolated into SQL query',
    occurrences: [
      {
        occurrence_id: 'occ-tp-001',
        files: [
          {
            path: 'src/db/queries.py',
            ranges: [{ start_line: 10, end_line: 11, note: 'String interpolation in SQL' }],
          },
        ],
        note: 'The user_id parameter is directly inserted into the query string',
        critic_scopes_expected_to_recall: [['security', 'sql-injection']],
        graders_match_only_if_reported_on: null,
      },
    ],
    created_at: '2025-01-10T14:00:00Z',
  },
];

export const mockFileFps: FpInfo[] = [
  {
    fp_id: 'fp-safe-query-001',
    rationale: 'False positive: uses parameterized statements, safe from SQL injection',
    occurrences: [
      {
        occurrence_id: 'occ-fp-001',
        files: [
          {
            path: 'src/db/queries.py',
            ranges: [{ start_line: 23, end_line: 23, note: null }],
          },
        ],
        note: 'Uses cursor.execute with parameter tuple',
        relevant_files: null,
        graders_match_only_if_reported_on: null,
      },
    ],
    created_at: '2025-01-10T14:00:00Z',
  },
];

export const mockCritiqueIssues: ReportedIssueInfo[] = [
  {
    issue_id: 'critique-001',
    rationale: 'Potential SQL injection: string formatting used to build query',
    occurrences: [
      {
        files: [
          {
            path: 'src/db/queries.py',
            ranges: [{ start_line: 10, end_line: 11, note: null }],
          },
        ],
      },
    ],
  },
  {
    issue_id: 'critique-002',
    rationale: 'Database connection not properly managed - consider using context manager',
    occurrences: [
      {
        files: [
          {
            path: 'src/db/queries.py',
            ranges: [{ start_line: 6, end_line: 6, note: null }],
          },
        ],
      },
    ],
  },
];

export const mockGradingEdges: GradingEdgeInfo[] = [
  {
    source: {
      issue_id: 'critique-001',
      rationale: 'Potential SQL injection: string formatting used to build query',
    },
    target: {
      kind: 'tp',
      tp_id: 'tp-sql-injection-001',
      occurrence_id: 'occ-tp-001',
      credit: 1.0,
    },
    grader_rationale: 'Critique correctly identified the SQL injection vulnerability',
  },
  {
    source: {
      issue_id: 'critique-002',
      rationale: 'Database connection not properly managed',
    },
    target: {
      kind: 'none',
    },
    grader_rationale: 'Valid concern but not in ground truth',
  },
];

export const mockExampleDetail: ExampleDetailResponse = {
  snapshot_slug: 'project/snapshot-v1',
  example_kind: 'whole_snapshot',
  files_hash: null,
  split: 'valid',
  recall_denominator: 5,
  files: null,
  definitions: [
    {
      definition_id: 'def-001',
      model: 'gpt-5.1-codex-mini',
      n_runs: 3,
      status_counts: { completed: 3 },
      credit_stats: { n: 3, mean: 0.8, min: 0.6, max: 1.0, lcb95: 0.65, ucb95: 0.95 },
    },
    {
      definition_id: 'def-002',
      model: 'gpt-5.1-codex-mini',
      n_runs: 2,
      status_counts: { completed: 2 },
      credit_stats: { n: 2, mean: 0.6, min: 0.4, max: 0.8, lcb95: null, ucb95: null },
    },
  ],
  credit_stats: { n: 5, mean: 0.72, min: 0.4, max: 1.0, lcb95: 0.58, ucb95: 0.86 },
};
