import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  SubscriptionManager,
  createSubscriptionManager,
  SubscriptionError,
  type ResourceCallback,
} from './subscriptions';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import * as clientModule from './client';

// Mock the client module
vi.mock('./client', async () => {
  const actual = await vi.importActual('./client');
  return {
    ...actual,
    readResource: vi.fn(),
    subscribeToResource: vi.fn(),
    MCPClientError: actual.MCPClientError,
  };
});

describe('SubscriptionManager', () => {
  let mockClient: any;
  let manager: SubscriptionManager;

  beforeEach(() => {
    vi.clearAllMocks();

    // Create mock client with necessary methods
    mockClient = {
      subscribeResource: vi.fn().mockResolvedValue({}),
      unsubscribeResource: vi.fn().mockResolvedValue({}),
      setNotificationHandler: vi.fn(),
    };

    // Mock client module functions
    vi.mocked(clientModule.subscribeToResource).mockResolvedValue();
    vi.mocked(clientModule.readResource).mockResolvedValue([
      { uri: 'test://resource', text: 'content' },
    ]);

    manager = new SubscriptionManager(mockClient);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('constructor', () => {
    it('creates a new SubscriptionManager with empty subscriptions', () => {
      const newManager = new SubscriptionManager(mockClient);

      expect(newManager.getSubscribedUris()).toEqual([]);
      expect(newManager).toBeInstanceOf(SubscriptionManager);
    });
  });

  describe('subscribe', () => {
    it('subscribes to a new resource and registers notification handler', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);

      expect(clientModule.subscribeToResource).toHaveBeenCalledWith(
        mockClient,
        'test://resource1'
      );
      expect(mockClient.setNotificationHandler).toHaveBeenCalledTimes(1);
      expect(manager.isSubscribed('test://resource1')).toBe(true);
    });

    it('fetches and calls callback with initial resource data', async () => {
      const callback = vi.fn();
      const expectedData = [{ uri: 'test://resource', text: 'initial content' }];
      vi.mocked(clientModule.readResource).mockResolvedValue(expectedData);

      await manager.subscribe('test://resource1', callback);

      expect(clientModule.readResource).toHaveBeenCalledWith(mockClient, 'test://resource1');
      expect(callback).toHaveBeenCalledWith(expectedData);
      expect(callback).toHaveBeenCalledTimes(1);
    });

    it('registers notification handler only once for multiple subscriptions', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource2', callback2);

      expect(mockClient.setNotificationHandler).toHaveBeenCalledTimes(1);
    });

    it('allows multiple callbacks for the same URI', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      expect(manager.getCallbackCount('test://resource1')).toBe(2);
      expect(clientModule.subscribeToResource).toHaveBeenCalledTimes(1); // Only subscribe once
    });

    it('calls all callbacks when multiple are registered', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();
      const expectedData = [{ uri: 'test://resource', text: 'data' }];
      vi.mocked(clientModule.readResource).mockResolvedValue(expectedData);

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      // Both should be called with initial data
      expect(callback1).toHaveBeenCalledWith(expectedData);
      expect(callback2).toHaveBeenCalledWith(expectedData);
    });

    it('throws SubscriptionError when subscribeToResource fails', async () => {
      const callback = vi.fn();
      const error = new Error('Network error');
      vi.mocked(clientModule.subscribeToResource).mockRejectedValue(error);

      await expect(manager.subscribe('test://resource1', callback)).rejects.toThrow(
        SubscriptionError
      );
      await expect(manager.subscribe('test://resource1', callback)).rejects.toThrow(
        /Network error/
      );
    });

    it('cleans up callback on subscription failure', async () => {
      const callback = vi.fn();
      vi.mocked(clientModule.subscribeToResource).mockRejectedValue(new Error('Failed'));

      await expect(manager.subscribe('test://resource1', callback)).rejects.toThrow();

      expect(manager.isSubscribed('test://resource1')).toBe(false);
      expect(manager.getCallbackCount('test://resource1')).toBe(0);
    });

    it('handles readResource failure after successful subscription', async () => {
      const callback = vi.fn();
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      vi.mocked(clientModule.readResource).mockRejectedValue(new Error('Read failed'));

      // Should not throw, but should handle gracefully by calling callback with error data
      await manager.subscribe('test://resource1', callback);

      expect(manager.isSubscribed('test://resource1')).toBe(true);
      expect(callback).toHaveBeenCalledWith({
        error: true,
        message: 'Read failed',
      });

      consoleErrorSpy.mockRestore();
    });
  });

  describe('unsubscribe', () => {
    it('removes a specific callback from a resource', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      await manager.unsubscribe('test://resource1', callback1);

      expect(manager.getCallbackCount('test://resource1')).toBe(1);
      expect(manager.isSubscribed('test://resource1')).toBe(true);
    });

    it('removes all callbacks when no specific callback provided', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      await manager.unsubscribe('test://resource1');

      expect(manager.getCallbackCount('test://resource1')).toBe(0);
      expect(manager.isSubscribed('test://resource1')).toBe(false);
    });

    it('unsubscribes from server when last callback is removed', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);
      await manager.unsubscribe('test://resource1', callback);

      expect(mockClient.unsubscribeResource).toHaveBeenCalledWith({
        uri: 'test://resource1',
      });
    });

    it('does not unsubscribe from server when other callbacks remain', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      await manager.unsubscribe('test://resource1', callback1);

      expect(mockClient.unsubscribeResource).not.toHaveBeenCalled();
    });

    it('handles unsubscribe for non-existent URI gracefully', async () => {
      await expect(manager.unsubscribe('test://nonexistent')).resolves.toBeUndefined();

      expect(mockClient.unsubscribeResource).not.toHaveBeenCalled();
    });

    it('logs warning but does not throw when server unsubscribe fails', async () => {
      const callback = vi.fn();
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      mockClient.unsubscribeResource.mockRejectedValue(new Error('Server error'));

      await manager.subscribe('test://resource1', callback);
      await manager.unsubscribe('test://resource1', callback);

      expect(consoleWarnSpy).toHaveBeenCalled();
      expect(manager.isSubscribed('test://resource1')).toBe(false);

      consoleWarnSpy.mockRestore();
    });
  });

  describe('handleNotification', () => {
    it('extracts URI from notification and refreshes resource', async () => {
      const callback = vi.fn();
      await manager.subscribe('test://resource1', callback);

      callback.mockClear();
      vi.mocked(clientModule.readResource).mockResolvedValue([
        { uri: 'test://resource1', text: 'updated content' },
      ]);

      manager.handleNotification({
        method: 'notifications/resources/updated',
        params: { uri: 'test://resource1' },
      });

      // Wait for async refresh
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(clientModule.readResource).toHaveBeenCalledWith(mockClient, 'test://resource1');
      expect(callback).toHaveBeenCalledWith([
        { uri: 'test://resource1', text: 'updated content' },
      ]);
    });

    it('logs warning when notification has no URI', () => {
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      manager.handleNotification({
        method: 'notifications/resources/updated',
        params: {},
      });

      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('without URI'),
        expect.any(Object)
      );

      consoleWarnSpy.mockRestore();
    });

    it('does not throw when notification handling fails', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      expect(() => {
        manager.handleNotification(null);
      }).not.toThrow();

      consoleErrorSpy.mockRestore();
    });

    it('ignores notifications for unsubscribed resources', async () => {
      const callback = vi.fn();
      await manager.subscribe('test://resource1', callback);
      callback.mockClear();

      manager.handleNotification({
        method: 'notifications/resources/updated',
        params: { uri: 'test://other-resource' },
      });

      // Wait a bit
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(callback).not.toHaveBeenCalled();
    });
  });

  describe('refreshResource', () => {
    it('fetches resource and calls all callbacks', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();
      const expectedData = [{ uri: 'test://resource', text: 'fresh data' }];

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      callback1.mockClear();
      callback2.mockClear();
      vi.mocked(clientModule.readResource).mockResolvedValue(expectedData);

      await manager.refreshResource('test://resource1');

      expect(clientModule.readResource).toHaveBeenCalledWith(mockClient, 'test://resource1');
      expect(callback1).toHaveBeenCalledWith(expectedData);
      expect(callback2).toHaveBeenCalledWith(expectedData);
    });

    it('does nothing when refreshing unsubscribed resource', async () => {
      await manager.refreshResource('test://nonexistent');

      expect(clientModule.readResource).not.toHaveBeenCalled();
    });

    it('continues calling other callbacks if one throws', async () => {
      const callback1 = vi.fn().mockImplementation(() => {
        throw new Error('Callback error');
      });
      const callback2 = vi.fn();
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      callback1.mockClear();
      callback2.mockClear();

      await manager.refreshResource('test://resource1');

      expect(callback1).toHaveBeenCalled();
      expect(callback2).toHaveBeenCalled();
      expect(consoleErrorSpy).toHaveBeenCalled();

      consoleErrorSpy.mockRestore();
    });

    it('calls callbacks with error data when resource fetch fails', async () => {
      const callback = vi.fn();
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      await manager.subscribe('test://resource1', callback);
      callback.mockClear();

      vi.mocked(clientModule.readResource).mockRejectedValue(new Error('Fetch failed'));

      await manager.refreshResource('test://resource1');

      expect(callback).toHaveBeenCalledWith({
        error: true,
        message: 'Fetch failed',
      });

      consoleErrorSpy.mockRestore();
    });
  });

  describe('getSubscribedUris', () => {
    it('returns empty array when no subscriptions', () => {
      expect(manager.getSubscribedUris()).toEqual([]);
    });

    it('returns all subscribed URIs', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);
      await manager.subscribe('test://resource2', callback);

      const uris = manager.getSubscribedUris();
      expect(uris).toHaveLength(2);
      expect(uris).toContain('test://resource1');
      expect(uris).toContain('test://resource2');
    });

    it('updates when subscriptions are added and removed', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);
      expect(manager.getSubscribedUris()).toEqual(['test://resource1']);

      await manager.unsubscribe('test://resource1');
      expect(manager.getSubscribedUris()).toEqual([]);
    });
  });

  describe('isSubscribed', () => {
    it('returns false for unsubscribed URIs', () => {
      expect(manager.isSubscribed('test://resource1')).toBe(false);
    });

    it('returns true for subscribed URIs', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);

      expect(manager.isSubscribed('test://resource1')).toBe(true);
    });

    it('returns false after unsubscribing', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);
      await manager.unsubscribe('test://resource1');

      expect(manager.isSubscribed('test://resource1')).toBe(false);
    });
  });

  describe('getCallbackCount', () => {
    it('returns 0 for unsubscribed URIs', () => {
      expect(manager.getCallbackCount('test://resource1')).toBe(0);
    });

    it('returns correct count for single callback', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);

      expect(manager.getCallbackCount('test://resource1')).toBe(1);
    });

    it('returns correct count for multiple callbacks', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();
      const callback3 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);
      await manager.subscribe('test://resource1', callback3);

      expect(manager.getCallbackCount('test://resource1')).toBe(3);
    });

    it('decreases when callbacks are removed', async () => {
      const callback1 = vi.fn();
      const callback2 = vi.fn();

      await manager.subscribe('test://resource1', callback1);
      await manager.subscribe('test://resource1', callback2);

      expect(manager.getCallbackCount('test://resource1')).toBe(2);

      await manager.unsubscribe('test://resource1', callback1);

      expect(manager.getCallbackCount('test://resource1')).toBe(1);
    });
  });

  describe('cleanup', () => {
    it('unsubscribes from all resources', async () => {
      const callback = vi.fn();

      await manager.subscribe('test://resource1', callback);
      await manager.subscribe('test://resource2', callback);

      await manager.cleanup();

      expect(manager.getSubscribedUris()).toEqual([]);
      expect(mockClient.unsubscribeResource).toHaveBeenCalledWith({
        uri: 'test://resource1',
      });
      expect(mockClient.unsubscribeResource).toHaveBeenCalledWith({
        uri: 'test://resource2',
      });
    });

    it('handles cleanup when no subscriptions exist', async () => {
      await expect(manager.cleanup()).resolves.toBeUndefined();

      expect(mockClient.unsubscribeResource).not.toHaveBeenCalled();
    });

    it('continues cleanup even if some unsubscribes fail', async () => {
      const callback = vi.fn();
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      await manager.subscribe('test://resource1', callback);
      await manager.subscribe('test://resource2', callback);

      mockClient.unsubscribeResource.mockRejectedValueOnce(new Error('Failed'));

      await manager.cleanup();

      expect(manager.getSubscribedUris()).toEqual([]);
      expect(consoleWarnSpy).toHaveBeenCalled();

      consoleWarnSpy.mockRestore();
    });
  });

  describe('createSubscriptionManager', () => {
    it('creates a new SubscriptionManager instance', () => {
      const newManager = createSubscriptionManager(mockClient);

      expect(newManager).toBeInstanceOf(SubscriptionManager);
      expect(newManager.getSubscribedUris()).toEqual([]);
    });

    it('creates independent instances', () => {
      const manager1 = createSubscriptionManager(mockClient);
      const manager2 = createSubscriptionManager(mockClient);

      expect(manager1).not.toBe(manager2);
    });
  });

  describe('SubscriptionError', () => {
    it('creates error with message and cause', () => {
      const cause = new Error('Original error');
      const error = new SubscriptionError('Wrapped error', cause);

      expect(error.message).toBe('Wrapped error');
      expect(error.cause).toBe(cause);
      expect(error.name).toBe('SubscriptionError');
    });

    it('creates error without cause', () => {
      const error = new SubscriptionError('Simple error');

      expect(error.message).toBe('Simple error');
      expect(error.cause).toBeUndefined();
      expect(error.name).toBe('SubscriptionError');
    });

    it('is instanceof Error', () => {
      const error = new SubscriptionError('Test');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(SubscriptionError);
    });
  });
});
