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

  describe('Connection Timeouts', () => {
    it('handles connection timeout gracefully', async () => {
      const config: MCPClientConfig = {
        name: 'test-client',
        url: 'http://localhost:8080',
        token: 'token',
      };

      const timeoutError = new Error('Connection timeout after 30000ms');
      mockClient.connect.mockRejectedValue(timeoutError);

      await expect(createMCPClient(config)).rejects.toThrow(MCPClientError);
      await expect(createMCPClient(config)).rejects.toThrow(/timeout/i);
    });

    it('handles read timeout on resource read', async () => {
      const timeoutError = new Error('Read timeout');
      mockClient.readResource.mockRejectedValue(timeoutError);

      await expect(readResource(mockClient, 'test://slow-resource')).rejects.toThrow(
        MCPClientError
      );
      await expect(readResource(mockClient, 'test://slow-resource')).rejects.toThrow(
        /timeout/i
      );
    });

    it('handles tool call timeout', async () => {
      const timeoutError = new Error('Tool execution timeout');
      mockClient.callTool.mockRejectedValue(timeoutError);

      await expect(callTool(mockClient, 'slow-tool', {})).rejects.toThrow(MCPClientError);
      await expect(callTool(mockClient, 'slow-tool', {})).rejects.toThrow(/timeout/i);
    });
  });

  describe('Large Payload Handling', () => {
    it('handles large resource content', async () => {
      const largeContent = Array(10000)
        .fill(null)
        .map((_, i) => ({ uri: `test://resource/${i}`, text: 'x'.repeat(1000) }));
      mockClient.readResource.mockResolvedValue({ contents: largeContent });

      const result = await readResource(mockClient, 'test://large-resource');

      expect(result).toEqual(largeContent);
      expect(result.length).toBe(10000);
    });

    it('handles large tool arguments', async () => {
      mockClient.callTool.mockResolvedValue({ content: [{ type: 'text', text: 'ok' }] });

      const largeArgs = {
        data: Array(5000)
          .fill(null)
          .map((_, i) => ({ id: i, value: `item-${i}` })),
      };

      const result = await callTool(mockClient, 'process-data', largeArgs);

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'process-data',
        arguments: largeArgs,
      });
      expect(result).toEqual({ content: [{ type: 'text', text: 'ok' }] });
    });

    it('handles large tool response', async () => {
      const largeResponse = {
        content: Array(1000)
          .fill(null)
          .map((_, i) => ({ type: 'text', text: `Response chunk ${i}` })),
      };
      mockClient.callTool.mockResolvedValue(largeResponse);

      const result = await callTool(mockClient, 'generate-data', {});

      expect(result).toEqual(largeResponse);
      expect(result.content.length).toBe(1000);
    });
  });

  describe('Concurrent Operations', () => {
    it('handles multiple concurrent resource reads', async () => {
      const resources = ['test://r1', 'test://r2', 'test://r3', 'test://r4', 'test://r5'];

      mockClient.readResource.mockImplementation(async ({ uri }: { uri: string }) => {
        // Simulate varying response times
        await new Promise((resolve) => setTimeout(resolve, Math.random() * 10));
        return { contents: [{ uri, text: `content-${uri}` }] };
      });

      const results = await Promise.all(resources.map((uri) => readResource(mockClient, uri)));

      expect(results).toHaveLength(5);
      results.forEach((result, i) => {
        expect(result[0].uri).toBe(resources[i]);
      });
    });

    it('handles concurrent tool calls without blocking', async () => {
      const tools = ['tool1', 'tool2', 'tool3'];

      mockClient.callTool.mockImplementation(async ({ name }: { name: string }) => {
        await new Promise((resolve) => setTimeout(resolve, Math.random() * 10));
        return { content: [{ type: 'text', text: `result-${name}` }] };
      });

      const startTime = Date.now();
      const results = await Promise.all(
        tools.map((tool) => callTool(mockClient, tool, { param: 'value' }))
      );
      const duration = Date.now() - startTime;

      expect(results).toHaveLength(3);
      // Should complete concurrently, not sequentially (< 50ms vs > 30ms if sequential)
      expect(duration).toBeLessThan(50);
    });

    it('handles mixed concurrent operations', async () => {
      mockClient.readResource.mockResolvedValue({
        contents: [{ uri: 'test://r', text: 'content' }],
      });
      mockClient.callTool.mockResolvedValue({ content: [{ type: 'text', text: 'result' }] });
      mockClient.subscribeResource.mockResolvedValue({});

      const operations = [
        readResource(mockClient, 'test://r1'),
        callTool(mockClient, 't1', {}),
        subscribeToResource(mockClient, 'test://r2'),
        readResource(mockClient, 'test://r3'),
        callTool(mockClient, 't2', {}),
      ];

      const results = await Promise.all(operations);

      expect(results).toHaveLength(5);
      expect(mockClient.readResource).toHaveBeenCalledTimes(2);
      expect(mockClient.callTool).toHaveBeenCalledTimes(2);
      expect(mockClient.subscribeResource).toHaveBeenCalledTimes(1);
    });
  });

  describe('Resource URI Edge Cases', () => {
    it('handles URI with special characters', async () => {
      mockClient.readResource.mockResolvedValue({ contents: [] });

      await readResource(mockClient, 'test://path/with spaces/and&special?chars=value');

      expect(mockClient.readResource).toHaveBeenCalledWith({
        uri: 'test://path/with spaces/and&special?chars=value',
      });
    });

    it('handles URI with fragments', async () => {
      mockClient.readResource.mockResolvedValue({ contents: [] });

      await readResource(mockClient, 'resource://server/path#fragment');

      expect(mockClient.readResource).toHaveBeenCalledWith({
        uri: 'resource://server/path#fragment',
      });
    });

    it('handles very long URI', async () => {
      mockClient.readResource.mockResolvedValue({ contents: [] });

      const longPath = 'a/'.repeat(500) + 'file.txt';
      const longUri = `test://server/${longPath}`;

      await readResource(mockClient, longUri);

      expect(mockClient.readResource).toHaveBeenCalledWith({ uri: longUri });
    });

    it('handles URI with encoded characters', async () => {
      mockClient.subscribeResource.mockResolvedValue({});

      await subscribeToResource(mockClient, 'test://path/%20%21%40%23');

      expect(mockClient.subscribeResource).toHaveBeenCalledWith({
        uri: 'test://path/%20%21%40%23',
      });
    });

    it('handles empty path URI', async () => {
      mockClient.readResource.mockResolvedValue({ contents: [] });

      await readResource(mockClient, 'resource://server/');

      expect(mockClient.readResource).toHaveBeenCalledWith({
        uri: 'resource://server/',
      });
    });
  });

  describe('Complex Nested Arguments', () => {
    it('handles deeply nested object structures', async () => {
      mockClient.callTool.mockResolvedValue({ content: [] });

      const deeplyNested = {
        level1: {
          level2: {
            level3: {
              level4: {
                level5: {
                  value: 'deep',
                  array: [1, 2, { nested: true }],
                },
              },
            },
          },
        },
      };

      await callTool(mockClient, 'complex-tool', deeplyNested);

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'complex-tool',
        arguments: deeplyNested,
      });
    });

    it('handles arrays of complex objects', async () => {
      mockClient.callTool.mockResolvedValue({ content: [] });

      const complexArray = {
        items: [
          { id: 1, nested: { value: 'a', tags: ['x', 'y'] } },
          { id: 2, nested: { value: 'b', tags: ['z'] } },
          { id: 3, nested: { value: 'c', tags: [] } },
        ],
      };

      await callTool(mockClient, 'process-items', complexArray);

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'process-items',
        arguments: complexArray,
      });
    });

    it('handles mixed type structures', async () => {
      mockClient.callTool.mockResolvedValue({ content: [] });

      const mixedTypes = {
        string: 'text',
        number: 42,
        boolean: true,
        null: null,
        array: [1, 'two', { three: 3 }],
        nested: {
          date: '2024-01-01',
          coordinates: [10.5, 20.3],
        },
      };

      await callTool(mockClient, 'mixed-tool', mixedTypes);

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'mixed-tool',
        arguments: mixedTypes,
      });
    });
  });

  describe('Integration Test: Full Workflow', () => {
    it('completes full workflow: connect, read, call, subscribe, notify', async () => {
      // Step 1: Create and connect client
      const config: MCPClientConfig = {
        name: 'integration-client',
        url: 'http://localhost:8080',
        token: 'integration-token',
      };

      const client = await createMCPClient(config);
      expect(client).toBe(mockClient);
      expect(mockClient.connect).toHaveBeenCalled();

      // Step 2: Read a resource
      mockClient.readResource.mockResolvedValue({
        contents: [{ uri: 'test://config', text: '{"enabled": true}' }],
      });

      const configContents = await readResource(client, 'test://config');
      expect(configContents).toHaveLength(1);
      expect(configContents[0].text).toContain('enabled');

      // Step 3: Call a tool with data from resource
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: 'Processing complete' }],
      });

      const toolResult = await callTool(client, 'process-config', {
        config: JSON.parse(configContents[0].text),
      });
      expect(toolResult.content[0].text).toBe('Processing complete');

      // Step 4: Subscribe to resource updates
      mockClient.subscribeResource.mockResolvedValue({});

      await subscribeToResource(client, 'test://config');
      expect(mockClient.subscribeResource).toHaveBeenCalledWith({
        uri: 'test://config',
      });

      // Step 5: Simulate notification handling (verify subscription was established)
      expect(mockClient.subscribeResource).toHaveBeenCalledTimes(1);

      // Verify all operations completed successfully
      expect(mockClient.connect).toHaveBeenCalledTimes(1);
      expect(mockClient.readResource).toHaveBeenCalledTimes(1);
      expect(mockClient.callTool).toHaveBeenCalledTimes(1);
      expect(mockClient.subscribeResource).toHaveBeenCalledTimes(1);
    });
  });

  describe('Performance: Concurrent Operations', () => {
    it('concurrent operations do not block each other', async () => {
      // Setup mock to simulate processing time
      let readCount = 0;
      let toolCount = 0;

      mockClient.readResource.mockImplementation(async () => {
        readCount++;
        await new Promise((resolve) => setTimeout(resolve, 5));
        return { contents: [{ uri: 'test://r', text: `read-${readCount}` }] };
      });

      mockClient.callTool.mockImplementation(async () => {
        toolCount++;
        await new Promise((resolve) => setTimeout(resolve, 5));
        return { content: [{ type: 'text', text: `tool-${toolCount}` }] };
      });

      // Launch 10 concurrent operations (5 reads + 5 tool calls)
      const operations = [
        ...Array(5)
          .fill(null)
          .map((_, i) => readResource(mockClient, `test://r${i}`)),
        ...Array(5)
          .fill(null)
          .map((_, i) => callTool(mockClient, `tool${i}`, {})),
      ];

      const startTime = Date.now();
      const results = await Promise.all(operations);
      const duration = Date.now() - startTime;

      // All 10 operations should complete
      expect(results).toHaveLength(10);

      // Should be concurrent (< 30ms) not sequential (> 50ms)
      expect(duration).toBeLessThan(30);

      // Verify all operations were called
      expect(readCount).toBe(5);
      expect(toolCount).toBe(5);
    });

    it('handles concurrent errors without affecting other operations', async () => {
      mockClient.callTool.mockImplementation(async ({ name }: { name: string }) => {
        await new Promise((resolve) => setTimeout(resolve, 5));

        // Fail tools with even-numbered names
        const toolNum = parseInt(name.replace('tool', ''));
        if (toolNum % 2 === 0) {
          throw new Error(`Tool ${name} failed`);
        }

        return { content: [{ type: 'text', text: `success-${name}` }] };
      });

      const operations = Array(6)
        .fill(null)
        .map((_, i) => callTool(mockClient, `tool${i}`, {}).catch((e) => e));

      const results = await Promise.all(operations);

      // Should have 3 successes (odd indices: 1, 3, 5) and 3 failures (even indices: 0, 2, 4)
      const successes = results.filter((r) => !(r instanceof MCPClientError));
      const failures = results.filter((r) => r instanceof MCPClientError);

      expect(successes).toHaveLength(3);
      expect(failures).toHaveLength(3);
      expect(mockClient.callTool).toHaveBeenCalledTimes(6);
    });
  });
});
