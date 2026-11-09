// SPDX-License-Identifier: Apache-2.0
/**
 * @file i18n.test.ts
 * @description Merged i18n tests: translation resources + sessions table column keys.
 */

import { describe, it, expect } from "vitest";
import i18n from "i18next";
import enSessions from "../locales/en/sessions.json";
import zhSessions from "../locales/zh/sessions.json";

describe("i18n resources", () => {
  it("should keep Agent terminology untranslated in zh locale", async () => {
    await i18n.changeLanguage("zh");
    expect(i18n.t("common:agent")).toBe("Agent");
    expect(i18n.t("common:subagent")).toBe("Subagent");
  });
});

// =====================================================================
// sessions.json — table column keys
// =====================================================================

describe("sessions.json — table column keys", () => {
  describe("en locale", () => {
    it("has tableStartTime key", () => {
      expect(enSessions).toHaveProperty("tableStartTime");
      expect(typeof (enSessions as any).tableStartTime).toBe("string");
    });

    it("has tableActiveTime key (renamed from tableLastActive)", () => {
      expect(enSessions).toHaveProperty("tableActiveTime");
      expect(typeof (enSessions as any).tableActiveTime).toBe("string");
    });

    it("does not have legacy tableLastActive key", () => {
      expect(enSessions).not.toHaveProperty("tableLastActive");
    });
  });

  describe("zh locale", () => {
    it("has tableStartTime key", () => {
      expect(zhSessions).toHaveProperty("tableStartTime");
      expect(typeof (zhSessions as any).tableStartTime).toBe("string");
    });

    it("has tableActiveTime key (renamed from tableLastActive)", () => {
      expect(zhSessions).toHaveProperty("tableActiveTime");
      expect(typeof (zhSessions as any).tableActiveTime).toBe("string");
    });

    it("does not have legacy tableLastActive key", () => {
      expect(zhSessions).not.toHaveProperty("tableLastActive");
    });
  });
});
