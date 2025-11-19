/**
 * Test file demonstrating usage of generated TypeScript types from Pydantic models
 */

import { describe, it, expect } from 'vitest'
import type {
  AgentInfo,
  PendingApproval,
  ApprovalHistoryEntry,
  ApprovalOutcome,
  ToolCall,
  Decision,
  ToolCallRecord,
  AgentMode,
} from './types'

describe('Generated Types', () => {
  describe('AgentInfo', () => {
    it('should create valid AgentInfo object', () => {
      const agentInfo: AgentInfo = {
        agent_id: 'test-agent-123',
        capabilities: {
          approvals: true,
          policy_proposals: false,
        },
        mode: 'local',
        state_uri: 'resource://agents/test-agent-123/state',
        approvals_uri: 'resource://agents/test-agent-123/approvals',
      }

      expect(agentInfo.agent_id).toBe('test-agent-123')
      expect(agentInfo.mode).toBe('local')
      expect(agentInfo.capabilities.approvals).toBe(true)
    })

    it('should allow bridge mode', () => {
      const agentInfo: AgentInfo = {
        agent_id: 'bridge-agent',
        capabilities: {},
        mode: 'bridge',
      }

      expect(agentInfo.mode).toBe('bridge')
    })

    it('should allow optional URIs', () => {
      const agentInfo: AgentInfo = {
        agent_id: 'minimal-agent',
        capabilities: {},
        mode: 'local',
      }

      expect(agentInfo.state_uri).toBeUndefined()
      expect(agentInfo.approvals_uri).toBeUndefined()
      expect(agentInfo.policy_proposals_uri).toBeUndefined()
    })
  })

  describe('PendingApproval', () => {
    it('should create valid PendingApproval object', () => {
      const pending: PendingApproval = {
        call_id: 'call-001',
        tool: 'filesystem_read',
        args: {
          path: '/etc/passwd',
        },
        timestamp: '2025-11-19T10:30:00Z',
      }

      expect(pending.call_id).toBe('call-001')
      expect(pending.tool).toBe('filesystem_read')
      expect(pending.args.path).toBe('/etc/passwd')
    })

    it('should allow arbitrary args structure', () => {
      const pending: PendingApproval = {
        call_id: 'call-002',
        tool: 'custom_tool',
        args: {
          nested: {
            deeply: {
              value: 42,
            },
          },
          array: [1, 2, 3],
        },
        timestamp: '2025-11-19T10:31:00Z',
      }

      expect(pending.args.nested.deeply.value).toBe(42)
    })
  })

  describe('ApprovalHistoryEntry', () => {
    it('should create valid approval history with user_approve outcome', () => {
      const entry: ApprovalHistoryEntry = {
        call_id: 'call-003',
        tool: 'bash_exec',
        args: {
          command: 'ls -la',
        },
        outcome: 'user_approve',
        reason: 'Safe read-only command',
        timestamp: '2025-11-19T10:32:00Z',
      }

      expect(entry.outcome).toBe('user_approve')
      expect(entry.reason).toBe('Safe read-only command')
    })

    it('should support all approval outcomes', () => {
      const outcomes: ApprovalOutcome[] = [
        'policy_allow',
        'policy_deny_continue',
        'policy_deny_abort',
        'user_approve',
        'user_deny_continue',
        'user_deny_abort',
      ]

      outcomes.forEach((outcome) => {
        const entry: ApprovalHistoryEntry = {
          call_id: `call-${outcome}`,
          tool: 'test_tool',
          args: {},
          outcome,
          timestamp: '2025-11-19T10:33:00Z',
        }

        expect(entry.outcome).toBe(outcome)
      })
    })

    it('should allow optional reason', () => {
      const entry: ApprovalHistoryEntry = {
        call_id: 'call-004',
        tool: 'test_tool',
        args: {},
        outcome: 'policy_allow',
        timestamp: '2025-11-19T10:34:00Z',
      }

      expect(entry.reason).toBeUndefined()
    })
  })

  describe('ToolCall', () => {
    it('should create valid ToolCall object', () => {
      const toolCall: ToolCall = {
        name: 'filesystem_write',
        call_id: 'tc-001',
        args_json: '{"path": "/tmp/test.txt", "content": "hello"}',
      }

      expect(toolCall.name).toBe('filesystem_write')
      expect(toolCall.call_id).toBe('tc-001')
      expect(toolCall.args_json).toBeTruthy()

      const args = JSON.parse(toolCall.args_json as string)
      expect(args.path).toBe('/tmp/test.txt')
    })

    it('should allow null args_json', () => {
      const toolCall: ToolCall = {
        name: 'no_args_tool',
        call_id: 'tc-002',
        args_json: null,
      }

      expect(toolCall.args_json).toBeNull()
    })
  })

  describe('Decision', () => {
    it('should create valid Decision object', () => {
      const decision: Decision = {
        outcome: 'user_approve',
        decided_at: '2025-11-19T10:35:00Z',
        reason: 'Verified safe operation',
      }

      expect(decision.outcome).toBe('user_approve')
      expect(decision.decided_at).toBeTruthy()
      expect(decision.reason).toBe('Verified safe operation')
    })

    it('should allow optional reason', () => {
      const decision: Decision = {
        outcome: 'policy_allow',
        decided_at: '2025-11-19T10:36:00Z',
      }

      expect(decision.reason).toBeUndefined()
    })
  })

  describe('ToolCallRecord', () => {
    it('should create pending tool call record', () => {
      const record: ToolCallRecord = {
        call_id: 'tcr-001',
        run_id: 'run-123',
        agent_id: 'agent-456',
        tool_call: {
          name: 'test_tool',
          call_id: 'tcr-001',
          args_json: '{}',
        },
        decision: null,
        execution: null,
      }

      expect(record.call_id).toBe('tcr-001')
      expect(record.decision).toBeNull()
      expect(record.execution).toBeNull()
    })

    it('should create decided tool call record', () => {
      const record: ToolCallRecord = {
        call_id: 'tcr-002',
        run_id: 'run-123',
        agent_id: 'agent-456',
        tool_call: {
          name: 'test_tool',
          call_id: 'tcr-002',
          args_json: '{}',
        },
        decision: {
          outcome: 'user_approve',
          decided_at: '2025-11-19T10:37:00Z',
        },
        execution: null,
      }

      expect(record.decision).toBeTruthy()
      expect(record.decision?.outcome).toBe('user_approve')
      expect(record.execution).toBeNull()
    })

    it('should create completed tool call record', () => {
      const record: ToolCallRecord = {
        call_id: 'tcr-003',
        run_id: 'run-123',
        agent_id: 'agent-456',
        tool_call: {
          name: 'test_tool',
          call_id: 'tcr-003',
          args_json: '{}',
        },
        decision: {
          outcome: 'user_approve',
          decided_at: '2025-11-19T10:38:00Z',
        },
        execution: {
          completed_at: '2025-11-19T10:38:05Z',
          output: {
            content: [
              {
                type: 'text',
                text: 'Operation completed successfully',
              },
            ],
          },
        },
      }

      expect(record.decision).toBeTruthy()
      expect(record.execution).toBeTruthy()
      expect(record.execution?.completed_at).toBeTruthy()
    })

    it('should allow null run_id', () => {
      const record: ToolCallRecord = {
        call_id: 'tcr-004',
        run_id: null,
        agent_id: 'agent-456',
        tool_call: {
          name: 'test_tool',
          call_id: 'tcr-004',
          args_json: null,
        },
      }

      expect(record.run_id).toBeNull()
    })
  })

  describe('Type Safety', () => {
    it('should enforce AgentMode enum', () => {
      const modes: AgentMode[] = ['local', 'bridge']

      modes.forEach((mode) => {
        const agent: AgentInfo = {
          agent_id: 'test',
          capabilities: {},
          mode,
        }
        expect(['local', 'bridge']).toContain(agent.mode)
      })
    })

    it('should enforce ApprovalOutcome enum', () => {
      const outcomes: ApprovalOutcome[] = [
        'policy_allow',
        'policy_deny_continue',
        'policy_deny_abort',
        'user_approve',
        'user_deny_continue',
        'user_deny_abort',
      ]

      outcomes.forEach((outcome) => {
        const decision: Decision = {
          outcome,
          decided_at: '2025-11-19T10:39:00Z',
        }
        expect(decision.outcome).toBe(outcome)
      })
    })
  })
})
