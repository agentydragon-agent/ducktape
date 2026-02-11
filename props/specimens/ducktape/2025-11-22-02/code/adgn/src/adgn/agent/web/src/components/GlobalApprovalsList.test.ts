import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte'
import GlobalApprovalsList from './GlobalApprovalsList.svelte'
import type { Client } from '@modelcontextprotocol/sdk/client/index.js'
import type { PendingApproval } from '../generated/types'

// Mock the MCP client module
vi.mock('../features/mcp/client', () => ({
  createMCPClient: vi.fn(),
  readResource: vi.fn(),
  callTool: vi.fn(),
  subscribeToResource: vi.fn(),
}))

// Mock the token module
vi.mock('../shared/token', () => ({
  getOrExtractToken: vi.fn(),
}))

// Mock JsonDisclosure component
vi.mock('./JsonDisclosure.svelte', () => ({
  default: vi.fn(() => ({
    $set: vi.fn(),
    $destroy: vi.fn(),
    $on: vi.fn(),
  })),
}))

import { createMCPClient, readResource, callTool, subscribeToResource } from '../features/mcp/client'
import { getOrExtractToken } from '../shared/token'

describe('GlobalApprovalsList', () => {
  let mockClient: Partial<Client>
  let mockReadResource: ReturnType<typeof vi.fn>
  let mockCallTool: ReturnType<typeof vi.fn>
  let mockCreateMCPClient: ReturnType<typeof vi.fn>
  let mockGetOrExtractToken: ReturnType<typeof vi.fn>

  beforeEach(() => {
    // Reset all mocks
    vi.clearAllMocks()

    // Setup mock client
    mockClient = {}

    // Cast mocked functions
    mockReadResource = readResource as ReturnType<typeof vi.fn>
    mockCallTool = callTool as ReturnType<typeof vi.fn>
    mockCreateMCPClient = createMCPClient as ReturnType<typeof vi.fn>
    mockGetOrExtractToken = getOrExtractToken as ReturnType<typeof vi.fn>

    // Default mock implementations
    mockGetOrExtractToken.mockReturnValue('test-token')
    mockCreateMCPClient.mockResolvedValue(mockClient)
    mockReadResource.mockResolvedValue([])
    mockCallTool.mockResolvedValue({ success: true })

    // Mock setInterval/clearInterval
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should render loading state initially', () => {
    mockCreateMCPClient.mockImplementation(() => new Promise(() => {})) // Never resolves

    render(GlobalApprovalsList)

    expect(screen.getByText('Loading...')).toBeTruthy()
  })

  it('should render empty state when no approvals', async () => {
    mockReadResource.mockResolvedValue([])

    render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('No pending approvals')).toBeTruthy()
    })
  })

  it('should display error when token is missing', async () => {
    mockGetOrExtractToken.mockReturnValue(null)

    render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText(/No authentication token available/)).toBeTruthy()
    })
  })

  it('should display error when MCP connection fails', async () => {
    mockCreateMCPClient.mockRejectedValue(new Error('Connection failed'))

    render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText(/Failed to connect to MCP server/)).toBeTruthy()
    })
  })

  it('should display approvals grouped by agent', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          tool_call: { name: 'read_file', call_id: 'call-1', args_json: '{"path": "/test.txt"}' },
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
      {
        uri: 'resource://approvals/2',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          tool_call: { name: 'write_file', call_id: 'call-2', args_json: '{"path": "/out.txt"}' },
          timestamp: '2025-01-01T00:01:00Z',
        }),
      },
      {
        uri: 'resource://approvals/3',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-2',
          tool_call: { name: 'exec', call_id: 'call-3', args_json: '{"command": "ls"}' },
          timestamp: '2025-01-01T00:02:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    render(GlobalApprovalsList)

    await waitFor(() => {
      // Check agent groups
      expect(screen.getByText(/Agent: agent-1/)).toBeTruthy()
      expect(screen.getByText(/Agent: agent-2/)).toBeTruthy()

      // Check count
      expect(screen.getByText(/2 pending/)).toBeTruthy()
      expect(screen.getByText(/1 pending/)).toBeTruthy()

      // Check tool names
      expect(screen.getByText('read_file')).toBeTruthy()
      expect(screen.getByText('write_file')).toBeTruthy()
      expect(screen.getByText('exec')).toBeTruthy()
    })
  })

  it('should call approve tool when approve button is clicked', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          tool_call: { name: 'test_tool', call_id: 'call-1', args_json: '{}' },
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Find and click approve button
    const approveButton = container.querySelector('.btn-approve')
    expect(approveButton).toBeTruthy()

    if (approveButton) {
      await fireEvent.click(approveButton)
    }

    await waitFor(() => {
      expect(mockCallTool).toHaveBeenCalledWith(
        mockClient,
        'approve_tool_call',
        {
          agent_id: 'agent-1',
          call_id: 'call-1',
        }
      )
    })
  })

  it('should open reject dialog when reject button is clicked', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          tool_call: { name: 'test_tool', call_id: 'call-1', args_json: '{}' },
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Find and click reject button
    const rejectButton = container.querySelector('.btn-reject')
    expect(rejectButton).toBeTruthy()

    if (rejectButton) {
      await fireEvent.click(rejectButton)
    }

    await waitFor(() => {
      expect(screen.getByText('Reject Tool Call')).toBeTruthy()
      expect(screen.getByText(/Agent: agent-1/)).toBeTruthy()
      expect(screen.getByText(/Call ID: call-1/)).toBeTruthy()
    })
  })

  it('should require rejection reason to be non-empty', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'test_tool',
          args: {},
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Open reject dialog
    const rejectButton = container.querySelector('.btn-reject')
    if (rejectButton) {
      await fireEvent.click(rejectButton)
    }

    await waitFor(() => {
      expect(screen.getByText('Reject Tool Call')).toBeTruthy()
    })

    // Find confirm button - should be disabled
    const confirmButton = container.querySelector('.btn-primary')
    expect(confirmButton).toBeTruthy()
    expect(confirmButton?.hasAttribute('disabled')).toBe(true)
  })

  it('should enable confirm button when rejection reason is provided', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'test_tool',
          args: {},
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Open reject dialog
    const rejectButton = container.querySelector('.btn-reject')
    if (rejectButton) {
      await fireEvent.click(rejectButton)
    }

    await waitFor(() => {
      expect(screen.getByText('Reject Tool Call')).toBeTruthy()
    })

    // Enter rejection reason
    const textarea = container.querySelector('#reject-reason') as HTMLTextAreaElement
    expect(textarea).toBeTruthy()

    if (textarea) {
      await fireEvent.input(textarea, { target: { value: 'Security concern' } })
    }

    await waitFor(() => {
      const confirmButton = container.querySelector('.btn-primary')
      expect(confirmButton?.hasAttribute('disabled')).toBe(false)
    })
  })

  it('should call reject tool with reason when confirmed', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'test_tool',
          args: {},
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Open reject dialog
    const rejectButton = container.querySelector('.btn-reject')
    if (rejectButton) {
      await fireEvent.click(rejectButton)
    }

    await waitFor(() => {
      expect(screen.getByText('Reject Tool Call')).toBeTruthy()
    })

    // Enter rejection reason
    const textarea = container.querySelector('#reject-reason') as HTMLTextAreaElement
    if (textarea) {
      await fireEvent.input(textarea, { target: { value: 'Security risk detected' } })
    }

    // Click confirm
    await waitFor(() => {
      const confirmButton = container.querySelector('.btn-primary')
      expect(confirmButton).toBeTruthy()
      if (confirmButton) {
        fireEvent.click(confirmButton)
      }
    })

    await waitFor(() => {
      expect(mockCallTool).toHaveBeenCalledWith(
        mockClient,
        'reject_tool_call',
        {
          agent_id: 'agent-1',
          call_id: 'call-1',
          reason: 'Security risk detected',
        }
      )
    })
  })

  it('should close reject dialog when cancel is clicked', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'test_tool',
          args: {},
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Open reject dialog
    const rejectButton = container.querySelector('.btn-reject')
    if (rejectButton) {
      await fireEvent.click(rejectButton)
    }

    await waitFor(() => {
      expect(screen.getByText('Reject Tool Call')).toBeTruthy()
    })

    // Click cancel
    const cancelButton = container.querySelector('.btn-secondary')
    expect(cancelButton).toBeTruthy()
    if (cancelButton) {
      await fireEvent.click(cancelButton)
    }

    await waitFor(() => {
      expect(screen.queryByText('Reject Tool Call')).toBeNull()
    })
  })

  it('should toggle args expansion when expand button is clicked', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'test_tool',
          args: { key: 'value' },
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Find expand toggle
    const expandToggle = container.querySelector('.expand-toggle')
    expect(expandToggle).toBeTruthy()
    expect(expandToggle?.textContent).toContain('▶')

    // Click to expand
    if (expandToggle) {
      await fireEvent.click(expandToggle)
    }

    await waitFor(() => {
      expect(expandToggle?.textContent).toContain('▼')
    })
  })

  it('should refresh approvals on interval', async () => {
    mockReadResource.mockResolvedValue([])

    render(GlobalApprovalsList)

    await waitFor(() => {
      expect(mockReadResource).toHaveBeenCalledTimes(1)
    })

    // Advance timer by 5 seconds (refresh interval)
    vi.advanceTimersByTime(5000)

    await waitFor(() => {
      expect(mockReadResource).toHaveBeenCalledTimes(2)
    })

    // Advance again
    vi.advanceTimersByTime(5000)

    await waitFor(() => {
      expect(mockReadResource).toHaveBeenCalledTimes(3)
    })
  })

  it('should update approvals list when new approvals arrive', async () => {
    // Start with empty list
    mockReadResource.mockResolvedValueOnce([])

    const { rerender } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('No pending approvals')).toBeTruthy()
    })

    // Simulate new approval arriving via polling
    const newApproval = {
      uri: 'resource://approvals/1',
      mimeType: 'application/json',
      text: JSON.stringify({
        agent_id: 'agent-1',
        call_id: 'call-1',
        tool: 'new_tool',
        args: {},
        timestamp: '2025-01-01T00:00:00Z',
      }),
    }
    mockReadResource.mockResolvedValueOnce([newApproval])

    // Advance timer to trigger refresh
    vi.advanceTimersByTime(5000)

    await waitFor(() => {
      expect(screen.getByText('new_tool')).toBeTruthy()
    })
  })

  it('should handle subscription failures gracefully', async () => {
    const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const mockSubscribe = subscribeToResource as ReturnType<typeof vi.fn>
    mockSubscribe.mockRejectedValue(new Error('Subscription not supported'))

    render(GlobalApprovalsList)

    await waitFor(() => {
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        'Subscription not supported, will use polling:',
        expect.any(Error)
      )
    })

    consoleWarnSpy.mockRestore()
  })

  it('should handle malformed approval data gracefully', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: 'invalid json{',
      },
      {
        uri: 'resource://approvals/2',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'valid_tool',
          args: {},
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource.mockResolvedValue(mockApprovals)

    render(GlobalApprovalsList)

    await waitFor(() => {
      // Should render the valid approval
      expect(screen.getByText('valid_tool')).toBeTruthy()
      // Should log error for invalid one
      expect(consoleErrorSpy).toHaveBeenCalled()
    })

    consoleErrorSpy.mockRestore()
  })

  it('should clean up interval on component destroy', async () => {
    mockReadResource.mockResolvedValue([])

    const { unmount } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(mockReadResource).toHaveBeenCalledTimes(1)
    })

    // Unmount component
    unmount()

    // Advance timer - should not trigger more fetches
    vi.advanceTimersByTime(10000)

    // Should still be just 1 call
    expect(mockReadResource).toHaveBeenCalledTimes(1)
  })

  it('should remove approval from list after successful approve', async () => {
    const mockApprovals = [
      {
        uri: 'resource://approvals/1',
        mimeType: 'application/json',
        text: JSON.stringify({
          agent_id: 'agent-1',
          call_id: 'call-1',
          tool: 'test_tool',
          args: {},
          timestamp: '2025-01-01T00:00:00Z',
        }),
      },
    ]

    mockReadResource
      .mockResolvedValueOnce(mockApprovals)
      .mockResolvedValueOnce([]) // After approve, list is empty

    const { container } = render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText('test_tool')).toBeTruthy()
    })

    // Click approve
    const approveButton = container.querySelector('.btn-approve')
    if (approveButton) {
      await fireEvent.click(approveButton)
    }

    await waitFor(() => {
      expect(screen.getByText('No pending approvals')).toBeTruthy()
    })
  })

  it('should display helpful message when backend endpoint is missing', async () => {
    const error404 = new Error('Failed to connect')
    error404.message = 'Failed to connect to MCP server: 404'
    mockCreateMCPClient.mockRejectedValue(error404)

    render(GlobalApprovalsList)

    await waitFor(() => {
      expect(screen.getByText(/backend MCP endpoint is not yet exposed/)).toBeTruthy()
    })
  })
})
