import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  createMCPClient,
  readResource,
  callTool,
  subscribeToResource,
  MCPClientError,
  type MCPClientConfig,
} from './client';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

// Mock the SDK modules
vi.mock('@modelcontextprotocol/sdk/client/index.js', () => ({
  Client: vi.fn(),
}));

vi.mock('@modelcontextprotocol/sdk/client/streamableHttp.js', () => ({
  StreamableHTTPClientTransport: vi.fn(),
}));

describe('MCP Client Wrapper', () => {
  let mockClient: any;
  let mockTransport: any;

  beforeEach(() => {
    // Reset mocks before each test
    vi.clearAllMocks();

    // Create mock client
    mockClient = {
      connect: vi.fn().mockResolvedValue(undefined),
      readResource: vi.fn(),
      callTool: vi.fn(),
      subscribeResource: vi.fn(),
    };

    // Create mock transport
    mockTransport = {};

    // Setup constructor mocks
    (Client as any).mockImplementation(() => mockClient);
    (StreamableHTTPClientTransport as any).mockImplementation(() => mockTransport);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('createMCPClient', () => {
    it('creates client with correct configuration', async () => {
      const config: MCPClientConfig = {
        name: 'test-client',
        url: 'http://localhost:8080',
        token: 'test-token-123',
      };

      const client = await createMCPClient(config);

      // Verify Client constructor was called with correct params
      expect(Client).toHaveBeenCalledWith(
        {
          name: 'test-client',
          version: '1.0.0',
        },
        {
          capabilities: {},
        }
      );

      // Verify transport was created with URL and auth header
      expect(StreamableHTTPClientTransport).toHaveBeenCalledWith(
        expect.any(URL),
        {
          requestInit: {
            headers: {
              Authorization: 'Bearer test-token-123',
            },
          },
        }
      );

      // Verify connect was called
      expect(mockClient.connect).toHaveBeenCalledWith(mockTransport);

      // Verify returned client
      expect(client).toBe(mockClient);
    });

    it('creates transport with correct URL object', async () => {
      const config: MCPClientConfig = {
        name: 'test-client',
        url: 'https://example.com:3000/mcp',
        token: 'token',
      };

      await createMCPClient(config);

      const urlArg = (StreamableHTTPClientTransport as any).mock.calls[0][0];
      expect(urlArg).toBeInstanceOf(URL);
      expect(urlArg.toString()).toBe('https://example.com:3000/mcp');
    });

    it('throws MCPClientError when URL is invalid', async () => {
      const config: MCPClientConfig = {
        name: 'test-client',
        url: 'not-a-valid-url',
        token: 'token',
      };

      await expect(createMCPClient(config)).rejects.toThrow(MCPClientError);
      await expect(createMCPClient(config)).rejects.toThrow(/Failed to create MCP client/);
    });

    it('throws MCPClientError when connection fails', async () => {
      const config: MCPClientConfig = {
        name: 'test-client',
        url: 'http://localhost:8080',
        token: 'token',
      };

      mockClient.connect.mockRejectedValue(new Error('Connection refused'));

      await expect(createMCPClient(config)).rejects.toThrow(MCPClientError);
      await expect(createMCPClient(config)).rejects.toThrow(/Connection refused/);
    });

    it('wraps non-Error exceptions in MCPClientError', async () => {
      const config: MCPClientConfig = {
        name: 'test-client',
        url: 'http://localhost:8080',
        token: 'token',
      };

      mockClient.connect.mockRejectedValue('string error');

      await expect(createMCPClient(config)).rejects.toThrow(MCPClientError);
      await expect(createMCPClient(config)).rejects.toThrow(/string error/);
    });
  });

  describe('readResource', () => {
    it('reads resource and returns contents', async () => {
      const expectedContents = [{ uri: 'test://resource', text: 'content' }];
      mockClient.readResource.mockResolvedValue({ contents: expectedContents });

      const result = await readResource(mockClient, 'test://resource');

      expect(mockClient.readResource).toHaveBeenCalledWith({ uri: 'test://resource' });
      expect(result).toEqual(expectedContents);
    });

    it('throws MCPClientError when read fails', async () => {
      mockClient.readResource.mockRejectedValue(new Error('Resource not found'));

      await expect(readResource(mockClient, 'test://missing')).rejects.toThrow(
        MCPClientError
      );
      await expect(readResource(mockClient, 'test://missing')).rejects.toThrow(
        /Failed to read resource test:\/\/missing/
      );
    });

    it('handles non-Error exceptions', async () => {
      mockClient.readResource.mockRejectedValue('unexpected error');

      await expect(readResource(mockClient, 'test://resource')).rejects.toThrow(
        MCPClientError
      );
      await expect(readResource(mockClient, 'test://resource')).rejects.toThrow(
        /unexpected error/
      );
    });
  });

  describe('callTool', () => {
    it('calls tool with correct arguments', async () => {
      const expectedResult = { content: [{ type: 'text', text: 'result' }] };
      mockClient.callTool.mockResolvedValue(expectedResult);

      const args = { param1: 'value1', param2: 42 };
      const result = await callTool(mockClient, 'test-tool', args);

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'test-tool',
        arguments: args,
      });
      expect(result).toEqual(expectedResult);
    });

    it('handles empty arguments', async () => {
      mockClient.callTool.mockResolvedValue({ content: [] });

      const result = await callTool(mockClient, 'no-args-tool', {});

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'no-args-tool',
        arguments: {},
      });
      expect(result).toEqual({ content: [] });
    });

    it('throws MCPClientError when tool call fails', async () => {
      mockClient.callTool.mockRejectedValue(new Error('Tool execution failed'));

      await expect(callTool(mockClient, 'failing-tool', {})).rejects.toThrow(
        MCPClientError
      );
      await expect(callTool(mockClient, 'failing-tool', {})).rejects.toThrow(
        /Failed to call tool failing-tool/
      );
    });

    it('preserves complex argument types', async () => {
      mockClient.callTool.mockResolvedValue({ content: [] });

      const complexArgs = {
        nested: { deep: { value: 123 } },
        array: [1, 2, 3],
        bool: true,
        null: null,
      };

      await callTool(mockClient, 'complex-tool', complexArgs);

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'complex-tool',
        arguments: complexArgs,
      });
    });
  });

  describe('subscribeToResource', () => {
    it('subscribes to resource successfully', async () => {
      mockClient.subscribeResource.mockResolvedValue({});

      await subscribeToResource(mockClient, 'test://resource');

      expect(mockClient.subscribeResource).toHaveBeenCalledWith({
        uri: 'test://resource',
      });
    });

    it('throws MCPClientError when subscription fails', async () => {
      mockClient.subscribeResource.mockRejectedValue(
        new Error('Subscription not supported')
      );

      await expect(subscribeToResource(mockClient, 'test://resource')).rejects.toThrow(
        MCPClientError
      );
      await expect(subscribeToResource(mockClient, 'test://resource')).rejects.toThrow(
        /Failed to subscribe to resource test:\/\/resource/
      );
    });

    it('handles various URI formats', async () => {
      mockClient.subscribeResource.mockResolvedValue({});

      await subscribeToResource(mockClient, 'resource://server/path/to/resource');

      expect(mockClient.subscribeResource).toHaveBeenCalledWith({
        uri: 'resource://server/path/to/resource',
      });
    });
  });

  describe('MCPClientError', () => {
    it('creates error with message and cause', () => {
      const cause = new Error('Original error');
      const error = new MCPClientError('Wrapped error', cause);

      expect(error.message).toBe('Wrapped error');
      expect(error.cause).toBe(cause);
      expect(error.name).toBe('MCPClientError');
    });

    it('creates error without cause', () => {
      const error = new MCPClientError('Simple error');

      expect(error.message).toBe('Simple error');
      expect(error.cause).toBeUndefined();
      expect(error.name).toBe('MCPClientError');
    });

    it('is instanceof Error', () => {
      const error = new MCPClientError('Test');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(MCPClientError);
    });
  });
});
