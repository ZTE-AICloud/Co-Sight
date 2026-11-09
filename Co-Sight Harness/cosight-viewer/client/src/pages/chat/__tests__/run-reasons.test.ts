// SPDX-License-Identifier: Apache-2.0
import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";

import { localizeRunReason } from "../run-reasons";

const TABLE: Record<string, string> = {
  "run.serverRestart": "the service restarted",
  "run.userAborted": "the user aborted",
};

const t = ((key: string) => TABLE[key] ?? key) as unknown as TFunction;

describe("localizeRunReason", () => {
  it("翻译已知的服务端固定原因", () => {
    expect(localizeRunReason("服务重启", t)).toBe("the service restarted");
    expect(localizeRunReason(" 用户中止 ", t)).toBe("the user aborted");
  });

  it("未知原因原样透出，不吞诊断信息", () => {
    expect(localizeRunReason("engine crashed: OOM", t)).toBe("engine crashed: OOM");
  });

  it("空值返回 null，由调用方决定兜底文案", () => {
    expect(localizeRunReason(undefined, t)).toBeNull();
    expect(localizeRunReason(null, t)).toBeNull();
    expect(localizeRunReason("   ", t)).toBeNull();
    expect(localizeRunReason(42, t)).toBeNull();
  });
});
