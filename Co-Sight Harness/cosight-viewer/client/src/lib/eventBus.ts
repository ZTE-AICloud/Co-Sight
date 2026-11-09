// SPDX-License-Identifier: Apache-2.0
/**
 * @file eventBus.ts
 * @description Implements a simple event bus for managing WebSocket messages and connection status in the agent dashboard application. It allows components to subscribe to real-time updates from the server and react to changes in WebSocket connectivity. The event bus maintains a list of handlers for incoming messages and connection status changes, providing a clean interface for publishing events and managing subscriptions.
 */

import type { WSMessage } from "./types";

type Handler = (msg: WSMessage) => void;
type ConnectionHandler = (connected: boolean) => void;

const handlers = new Set<Handler>();
const connectionHandlers = new Set<ConnectionHandler>();
let wsConnected = false;

export const eventBus = {
  subscribe(handler: Handler): () => void {
    handlers.add(handler);
    return () => handlers.delete(handler);
  },

  publish(msg: WSMessage): void {
    handlers.forEach((handler) => handler(msg));
  },

  get connected(): boolean {
    return wsConnected;
  },

  setConnected(value: boolean): void {
    wsConnected = value;
    connectionHandlers.forEach((handler) => handler(value));
  },

  onConnection(handler: ConnectionHandler): () => void {
    connectionHandlers.add(handler);
    return () => connectionHandlers.delete(handler);
  },
};
