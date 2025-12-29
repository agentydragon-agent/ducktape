/* eslint-disable @typescript-eslint/no-explicit-any */
// Mock data for Storybook stories
// Using any types to avoid schema mismatches since these are just visual examples

export const mockOverview: any = {
  definitions: [
    {
      definition_id: 'def-001',
      description: 'Check for SQL injection vulnerabilities',
      critic_type: 'security',
      agent_type: 'code_analyzer',
      enabled: true,
    },
    {
      definition_id: 'def-002',
      description: 'Detect XSS vulnerabilities in templates',
      critic_type: 'security',
      agent_type: 'code_analyzer',
      enabled: true,
    },
    {
      definition_id: 'def-003',
      description: 'Check for hardcoded credentials',
      critic_type: 'security',
      agent_type: 'code_analyzer',
      enabled: false,
    },
  ],
  example_counts: {
    'def-001': { train: 45, test: 12, validation: 8 },
    'def-002': { train: 23, test: 6, validation: 4 },
    'def-003': { train: 67, test: 18, validation: 11 },
  },
  total_definitions: 3,
};

export const mockSnapshotDetail: any = {
  slug: 'project-snapshot-v1.0',
  split: 'test',
  created_at: '2025-01-10T14:00:00Z',
  true_positives: [
    {
      tp_id: 'tp-001',
      rationale: 'SQL injection vulnerability in user input handling',
      occurrences: [
        {
          occurrence_id: 'occ-tp-001',
          files: [{ path: 'src/db/queries.py', ranges: [{ start_line: 45, end_line: 50 }] }],
          note: 'Direct string concatenation with user input',
          critic_scopes_expected_to_recall: [['security', 'sql-injection']],
          graders_match_only_if_reported_on: null,
        },
      ],
    },
    {
      tp_id: 'tp-002',
      rationale: 'XSS vulnerability in template rendering',
      occurrences: [
        {
          occurrence_id: 'occ-tp-002',
          files: [{ path: 'templates/user_profile.html', ranges: [{ start_line: 23, end_line: 25 }] }],
          note: null,
          critic_scopes_expected_to_recall: [['security', 'xss']],
          graders_match_only_if_reported_on: null,
        },
      ],
    },
  ],
  false_positives: [
    {
      fp_id: 'fp-001',
      rationale: 'Flagged as SQL injection but uses parameterized queries',
      occurrences: [
        {
          occurrence_id: 'occ-fp-001',
          files: [{ path: 'src/db/safe_queries.py', ranges: [{ start_line: 67, end_line: 70 }] }],
          note: 'Actually safe - uses ORM query builder',
          relevant_files: ['src/db/models.py'],
          graders_match_only_if_reported_on: null,
        },
      ],
    },
  ],
};

export const mockSnapshotTree: any = {
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
            {
              name: 'safe_queries.py',
              path: 'src/db/safe_queries.py',
              is_dir: false,
              tp_count: 0,
              fp_count: 1,
            },
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

export const mockSnapshotsList = [
  {
    slug: 'project-snapshot-v1.0',
    split: 'test' as const,
    tp_count: 24,
    fp_count: 3,
    created_at: '2025-01-15T10:00:00Z',
  },
  {
    slug: 'project-snapshot-v0.9',
    split: 'valid' as const,
    tp_count: 18,
    fp_count: 2,
    created_at: '2025-01-10T14:30:00Z',
  },
  {
    slug: 'baseline-snapshot',
    split: 'train' as const,
    tp_count: 156,
    fp_count: 12,
    created_at: '2025-01-01T00:00:00Z',
  },
];

export const mockExampleDetail: any = null;
