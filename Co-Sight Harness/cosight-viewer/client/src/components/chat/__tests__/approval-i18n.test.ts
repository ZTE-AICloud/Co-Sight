// SPDX-License-Identifier: Apache-2.0
import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";

import { approvalOptionLabel, approvalTitle } from "../approval-i18n";

/** 极简 i18n：只覆盖本模块用到的键，并支持 `{{param}}` 插值。 */
const TABLE: Record<string, string> = {
  "run.approve": "允许",
  "run.approveAll": "本会话全部允许",
  "run.reject": "拒绝",
  "run.approvalTitle": "允许执行 {{toolName}}？",
  "run.needApproval": "需要审批",
};

const t = ((key: string, params?: Record<string, string>) => {
  const value = TABLE[key] ?? key;
  return value.replace(/\{\{(\w+)\}\}/g, (_match, name: string) => params?.[name] ?? "");
}) as unknown as TFunction;

describe("approvalOptionLabel", () => {
  const options = [
    { value: "approved", label: "允许", enLabel: "Allow" },
    { value: "approved_all", label: "本会话全部允许", enLabel: "Allow all" },
    { value: "rejected", label: "拒绝", enLabel: "Reject" },
  ];

  it("已知语义值一律走 i18n，不依赖服务端下发的中英文", () => {
    const keys: Record<string, string> = {
      approved: "run.approve",
      approved_all: "run.approveAll",
      rejected: "run.reject",
    };
    for (const option of options) {
      expect(approvalOptionLabel(option, "en-US", t)).toBe(TABLE[keys[option.value]!]);
    }
  });

  it("未知语义值在英文界面优先 enLabel，缺省回退服务端原文", () => {
    expect(approvalOptionLabel({ value: "custom", label: "自定义", enLabel: "Custom" }, "en", t)).toBe(
      "Custom"
    );
    expect(approvalOptionLabel({ value: "custom", label: "自定义" }, "en", t)).toBe("自定义");
    expect(approvalOptionLabel({ value: "custom", label: "自定义" }, "zh-CN", t)).toBe("自定义");
  });
});

describe("approvalTitle", () => {
  it("识别服务端默认标题并用本地模板重渲染", () => {
    expect(approvalTitle("允许执行 Read？", t)).toBe("允许执行 Read？");
    expect(approvalTitle("允许执行 Bash？", t)).toContain("Bash");
  });

  it("agent 自定义标题原样保留", () => {
    expect(approvalTitle("需要写入配置文件", t)).toBe("需要写入配置文件");
  });

  it("空标题回落到 needApproval", () => {
    expect(approvalTitle("", t)).toBe("需要审批");
    expect(approvalTitle(undefined, t)).toBe("需要审批");
  });
});
