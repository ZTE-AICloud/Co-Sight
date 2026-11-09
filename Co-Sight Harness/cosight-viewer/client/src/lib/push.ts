// SPDX-License-Identifier: Apache-2.0
/**
 * @file push.ts
 * @description Provides functions for managing push notifications in the agent dashboard application. It includes utilities for subscribing and unsubscribing to push notifications using the Push API and Service Workers. The module handles the conversion of VAPID public keys, manages push subscriptions, and communicates with the backend API to register or unregister push endpoints. This allows the application to send real-time notifications to users about important events or updates.
 */

import { API_BASE } from "./config";

function urlBase64ToUint8Array(base64String: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let index = 0; index < rawData.length; index++) {
    outputArray[index] = rawData.charCodeAt(index);
  }
  return outputArray.buffer;
}

export async function subscribeToPush(): Promise<void> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;

  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  if (existing) return;

  const res = await fetch(`${API_BASE}/push/vapid-public-key`);
  const { publicKey } = await res.json();

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });

  await fetch(`${API_BASE}/push/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
}
