// SPDX-License-Identifier: Apache-2.0
/**
 * @file useNotifications.ts
 * @description Defines a custom React hook for managing browser notifications in the agent dashboard application. The hook subscribes to the event bus to listen for specific events such as new sessions, session errors, session completions, and subagent spawns. Based on user preferences stored in localStorage, it triggers browser notifications to keep users informed of important updates without needing to actively monitor the dashboard. The hook should be called once at the root level of the application to ensure notifications are handled globally.
 */

import { useEffect } from "react";
import i18n from "../i18n";
import { eventBus } from "../lib/eventBus";
import { subscribeToPush } from "../lib/push";
import { API_BASE } from "../lib/config";
import type { WSMessage, Session, Agent, DashboardEvent } from "../lib/types";

const NOTIF_KEY = "co-sight-viewer-notifications";

interface NotifPrefs {
  enabled: boolean;
  onNewSession: boolean;
  onSessionError: boolean;
  onSessionComplete: boolean;
  onSubagentSpawn: boolean;
}

function loadPrefs(): NotifPrefs {
  try {
    const raw = localStorage.getItem(NOTIF_KEY);
    if (!raw)
      return {
        enabled: false,
        onNewSession: true,
        onSessionError: true,
        onSessionComplete: false,
        onSubagentSpawn: false,
      };
    return {
      enabled: false,
      onNewSession: true,
      onSessionError: true,
      onSessionComplete: false,
      onSubagentSpawn: false,
      ...JSON.parse(raw),
    };
  } catch {
    return {
      enabled: false,
      onNewSession: true,
      onSessionError: true,
      onSessionComplete: false,
      onSubagentSpawn: false,
    };
  }
}

async function notify(title: string, body: string) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    await fetch(`${API_BASE}/push/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body }),
    });
  } catch {
    // Server unreachable — fall back to local notification
    try {
      if ("serviceWorker" in navigator) {
        const registration = await navigator.serviceWorker.ready;
        await registration.showNotification(title, { body, icon: "/favicon.ico", silent: false });
      } else {
        new Notification(title, { body, icon: "/favicon.ico" });
      }
    } catch {
      // Silently ignore
    }
  }
}

export function useNotifications() {
  useEffect(() => {
    const prefs = loadPrefs();
    if (prefs.enabled && "Notification" in window && Notification.permission === "granted") {
      subscribeToPush().catch(() => {});
    }

    return eventBus.subscribe((msg: WSMessage) => {
      const prefs = loadPrefs();
      if (!prefs.enabled) return;

      switch (msg.type) {
        case "session_created": {
          if (!prefs.onNewSession) return;
          const s = msg.data as Session;
          notify(
            i18n.t("errors.notifications.newSession"),
            s.name || `${i18n.t("errors.notifications.sessionDefault")}${s.id.slice(0, 8)}`
          );
          break;
        }
        case "session_updated": {
          const s = msg.data as Session;
          if (s.status === "error" && prefs.onSessionError) {
            notify(
              i18n.t("errors.notifications.sessionError"),
              s.name || `${i18n.t("errors.notifications.sessionDefault")}${s.id.slice(0, 8)}`
            );
          }
          break;
        }
        case "agent_created": {
          if (!prefs.onSubagentSpawn) return;
          const a = msg.data as Agent;
          if (a.type === "subagent") {
            notify(i18n.t("errors.notifications.subagentSpawned"), a.name);
          }
          break;
        }
        case "new_event": {
          const ev = msg.data as DashboardEvent;
          if (ev.event_type === "Stop" && prefs.onSessionComplete) {
            notify(
              i18n.t("errors.notifications.finishedResponding"),
              ev.summary || i18n.t("errors.notifications.readyForInput")
            );
          } else if (ev.event_type === "SessionEnd" && prefs.onSessionComplete) {
            notify(
              i18n.t("errors.notifications.sessionCompleted"),
              ev.summary || i18n.t("errors.notifications.sessionClosed")
            );
          } else if (ev.event_type === "Notification") {
            notify(
              i18n.t("errors.notifications.defaultTitle"),
              ev.summary || i18n.t("errors.notifications.defaultBody")
            );
          }
          break;
        }
      }
    });
  }, []);
}
