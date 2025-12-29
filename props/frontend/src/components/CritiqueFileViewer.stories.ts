/* eslint-disable @typescript-eslint/no-explicit-any */
import type { Meta, StoryObj } from '@storybook/svelte';
import CritiqueFileViewer from './CritiqueFileViewer.svelte';

// Mock file content with realistic code
const mockFileContent: any = {
  path: 'src/auth/login.py',
  content: `"""User authentication module."""
import hashlib
from typing import Optional

from db import execute_query


def authenticate_user(username: str, password: str) -> bool:
    """Authenticate user with username and password.

    WARNING: This has SQL injection and weak password hashing vulnerabilities!
    """
    # SQL injection vulnerability - direct string concatenation
    query = f"SELECT * FROM users WHERE username = '{username}'"
    result = execute_query(query)

    if not result:
        return False

    # Weak password hashing - MD5 is not secure
    password_hash = hashlib.md5(password.encode()).hexdigest()

    return result[0]['password_hash'] == password_hash


def get_user_profile(user_id: int) -> Optional[dict]:
    """Get user profile data."""
    # Safe parameterized query
    query = "SELECT * FROM profiles WHERE user_id = ?"
    return execute_query(query, [user_id])
`,
  line_count: 30,
};

// Mock ground truth TPs
const mockTPs: any = [
  {
    tp_id: 'tp-sql-injection',
    rationale: 'SQL injection vulnerability via string concatenation in query',
    occurrences: [
      {
        occurrence_id: 'occ-tp-sql-001',
        files: [
          {
            path: 'src/auth/login.py',
            ranges: [
              { start_line: 13, end_line: 14, note: 'String interpolation creates SQL injection vector' },
              { start_line: 20, end_line: 20, note: 'Query execution with unsanitized input' },
            ],
          },
        ],
        note: 'User input directly concatenated into SQL query without parameterization',
        critic_scopes_expected_to_recall: [['security', 'sql-injection']],
        graders_match_only_if_reported_on: null,
      },
    ],
  },
];

// Mock ground truth FPs
const mockFPs: any = [
  {
    fp_id: 'fp-false-alarm',
    rationale: 'Flagged as SQL injection but actually uses parameterized queries',
    occurrences: [
      {
        occurrence_id: 'occ-fp-001',
        files: [
          {
            path: 'src/auth/login.py',
            ranges: [{ start_line: 27, end_line: 28 }],
          },
        ],
        note: 'This is actually safe - uses question mark parameterization',
        relevant_files: ['src/db/connection.py'],
        graders_match_only_if_reported_on: null,
      },
    ],
  },
];

// Mock critique issues from agent run
const mockCritiqueIssues: any = [
  {
    id: 'critique-sql-001',
    rationale: 'Potential SQL injection: User input concatenated into query string',
    note: 'The username parameter is directly interpolated into the SQL query',
    ranges: [{ start_line: 13, end_line: 14 }],
    allFiles: [{ path: 'src/auth/login.py', ranges: [{ start_line: 13, end_line: 14 }] }],
  },
  {
    id: 'critique-hash-001',
    rationale: 'Weak cryptographic hash function: MD5 should not be used for passwords',
    note: null,
    ranges: [{ start_line: 20, end_line: 20 }],
    allFiles: [{ path: 'src/auth/login.py', ranges: [{ start_line: 20, end_line: 20 }] }],
  },
];

// Mock grading edges (critique matched to ground truth)
const mockGradingEdges: any = [
  {
    critique_issue_id: 'critique-sql-001',
    target: {
      kind: 'tp',
      tp_id: 'tp-sql-injection',
      occurrence_id: 'occ-tp-sql-001',
      credit: 1.0,
    },
    rationale: 'Critique correctly identified the SQL injection vulnerability',
  },
  {
    critique_issue_id: 'critique-hash-001',
    target: {
      kind: 'none',
    },
    rationale: 'Novel finding - MD5 usage not in ground truth',
  },
];

const meta = {
  title: 'Components/CritiqueFileViewer',
  component: CritiqueFileViewer,
  tags: ['autodocs'],
  parameters: {
    layout: 'padded',
  },
} satisfies Meta<CritiqueFileViewer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithAllIssueTypes: Story = {
  args: {
    file: mockFileContent,
    tps: mockTPs,
    fps: mockFPs,
    critiqueIssues: mockCritiqueIssues,
    gradingEdges: mockGradingEdges,
  },
};

export const OnlyGroundTruth: Story = {
  args: {
    file: mockFileContent,
    tps: mockTPs,
    fps: mockFPs,
    critiqueIssues: [],
    gradingEdges: [],
  },
};

export const OnlyCritique: Story = {
  args: {
    file: mockFileContent,
    tps: [],
    fps: [],
    critiqueIssues: mockCritiqueIssues,
    gradingEdges: mockGradingEdges,
  },
};

export const EmptyFile: Story = {
  args: {
    file: mockFileContent,
    tps: [],
    fps: [],
    critiqueIssues: [],
    gradingEdges: [],
  },
};
