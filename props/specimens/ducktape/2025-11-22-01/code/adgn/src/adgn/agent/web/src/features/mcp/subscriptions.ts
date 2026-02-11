import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import {
  readResource,
  subscribeToResource,
  MCPClientError,
} from './client';
import { ResourceUpdatedNotificationSchema } from '@modelcontextprotocol/sdk/types.js';

/**
 * Callback function invoked when a subscribed resource is updated
 */
export type ResourceCallback = (data: any) => void;

/**
 * Represents a subscription to an MCP resource
 */
export interface ResourceSubscription {
  /** The resource URI being subscribed to */
  uri: string;
  /** Callback to invoke when the resource is updated */
  callback: ResourceCallback;
}

/**
 * Error thrown when subscription operations fail
 */
export class SubscriptionError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'SubscriptionError';
  }
}

/**
 * Manages subscriptions to MCP resources with automatic UI updates
 *
 * Features:
 * - Multiple callbacks per resource URI
 * - Automatic notification handling
 * - Error recovery on resource fetch failures
 * - Unsubscribe cleanup
 */
export class SubscriptionManager {
  private subscriptions: Map<string, Set<ResourceCallback>>;
  private client: Client;
  private notificationHandlerRegistered: boolean;

  /**
   * Create a new SubscriptionManager
   *
   * @param client - Connected MCP client
   */
  constructor(client: Client) {
    this.client = client;
    this.subscriptions = new Map();
    this.notificationHandlerRegistered = false;
  }

  /**
   * Subscribe to updates for a resource URI
   *
   * @param uri - Resource URI to subscribe to
   * @param callback - Function to call when resource is updated
   * @throws SubscriptionError if subscription setup fails
   */
  async subscribe(uri: string, callback: ResourceCallback): Promise<void> {
    try {
      // Register notification handler on first subscription
      if (!this.notificationHandlerRegistered) {
        this.registerNotificationHandler();
        this.notificationHandlerRegistered = true;
      }

      // Track callback for this URI
      if (!this.subscriptions.has(uri)) {
        this.subscriptions.set(uri, new Set());

        // Subscribe to resource updates on the server
        await subscribeToResource(this.client, uri);
      }

      this.subscriptions.get(uri)!.add(callback);

      // Immediately fetch current resource state and invoke callback
      await this.refreshResource(uri);
    } catch (error) {
      // Clean up partial state on error
      const callbacks = this.subscriptions.get(uri);
      if (callbacks) {
        callbacks.delete(callback);
        if (callbacks.size === 0) {
          this.subscriptions.delete(uri);
        }
      }

      throw new SubscriptionError(
        `Failed to subscribe to resource ${uri}: ${error instanceof Error ? error.message : String(error)}`,
        error
      );
    }
  }

  /**
   * Unsubscribe from updates for a resource URI
   *
   * @param uri - Resource URI to unsubscribe from
   * @param callback - Optional specific callback to remove. If not provided, removes all callbacks for the URI.
   */
  async unsubscribe(uri: string, callback?: ResourceCallback): Promise<void> {
    const callbacks = this.subscriptions.get(uri);
    if (!callbacks) {
      return;
    }

    if (callback) {
      // Remove specific callback
      callbacks.delete(callback);
    } else {
      // Remove all callbacks for this URI
      callbacks.clear();
    }

    // Clean up if no more callbacks
    if (callbacks.size === 0) {
      this.subscriptions.delete(uri);

      // Unsubscribe from server
      try {
        await this.client.unsubscribeResource({ uri });
      } catch (error) {
        // Log but don't throw - cleanup is best effort
        console.warn(`Failed to unsubscribe from ${uri}:`, error);
      }
    }
  }

  /**
   * Handle a notification from the MCP server
   *
   * This method is called automatically when the server sends a
   * notifications/resources/updated notification.
   *
   * @param notification - The notification from the server
   */
  handleNotification(notification: any): void {
    try {
      // Extract URI from notification params
      const uri = notification.params?.uri;
      if (!uri) {
        console.warn('Received resource updated notification without URI', notification);
        return;
      }

      // Refresh the resource (fetch latest and call callbacks)
      this.refreshResource(uri).catch((error) => {
        console.error(`Failed to refresh resource ${uri} after notification:`, error);
      });
    } catch (error) {
      console.error('Error handling notification:', error);
    }
  }

  /**
   * Re-fetch a resource and invoke all registered callbacks
   *
   * @param uri - Resource URI to refresh
   * @throws SubscriptionError if resource fetch fails
   */
  async refreshResource(uri: string): Promise<void> {
    const callbacks = this.subscriptions.get(uri);
    if (!callbacks || callbacks.size === 0) {
      return;
    }

    try {
      // Fetch latest resource data
      const data = await readResource(this.client, uri);

      // Invoke all callbacks with the fresh data
      for (const callback of callbacks) {
        try {
          callback(data);
        } catch (error) {
          console.error(`Error in subscription callback for ${uri}:`, error);
          // Continue with other callbacks even if one fails
        }
      }
    } catch (error) {
      // Don't throw - allow retries and keep subscriptions alive
      console.error(`Failed to refresh resource ${uri}:`, error);

      // Still invoke callbacks with error indicator
      const errorData = {
        error: true,
        message: error instanceof Error ? error.message : String(error),
      };

      for (const callback of callbacks) {
        try {
          callback(errorData);
        } catch (callbackError) {
          console.error(`Error in error-handling callback for ${uri}:`, callbackError);
        }
      }
    }
  }

  /**
   * Get all currently subscribed URIs
   *
   * @returns Array of subscribed resource URIs
   */
  getSubscribedUris(): string[] {
    return Array.from(this.subscriptions.keys());
  }

  /**
   * Check if a URI is currently subscribed
   *
   * @param uri - Resource URI to check
   * @returns true if subscribed, false otherwise
   */
  isSubscribed(uri: string): boolean {
    const callbacks = this.subscriptions.get(uri);
    return callbacks !== undefined && callbacks.size > 0;
  }

  /**
   * Get the number of callbacks registered for a URI
   *
   * @param uri - Resource URI to check
   * @returns Number of callbacks, or 0 if not subscribed
   */
  getCallbackCount(uri: string): number {
    const callbacks = this.subscriptions.get(uri);
    return callbacks ? callbacks.size : 0;
  }

  /**
   * Unsubscribe from all resources and clean up
   */
  async cleanup(): Promise<void> {
    const uris = Array.from(this.subscriptions.keys());

    // Unsubscribe from all resources
    await Promise.all(uris.map((uri) => this.unsubscribe(uri)));

    this.subscriptions.clear();
  }

  /**
   * Register the notification handler with the MCP client
   * @private
   */
  private registerNotificationHandler(): void {
    this.client.setNotificationHandler(
      ResourceUpdatedNotificationSchema,
      (notification) => {
        this.handleNotification(notification);
      }
    );
  }
}

/**
 * Create a new SubscriptionManager instance
 *
 * @param client - Connected MCP client
 * @returns New SubscriptionManager instance
 */
export function createSubscriptionManager(client: Client): SubscriptionManager {
  return new SubscriptionManager(client);
}
