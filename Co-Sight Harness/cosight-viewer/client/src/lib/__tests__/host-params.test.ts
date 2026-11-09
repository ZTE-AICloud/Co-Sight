// SPDX-License-Identifier: Apache-2.0
/**
 * @file host-params.test.ts
 * @description 宿主入口翻译：能力 → 路由、参数 → 哈希查询串。
 *
 * 重点是「最近」依赖的那条：宿主把会话 id 拼在 iframe 地址的 `?` 上，
 * 而页面层读哈希里的查询串，漏搬一次就会表现为"点会话没有恢复、停在新会话空态"。
 */

import { describe, expect, it } from "vitest";
import { applyHostEntry } from "../host-params";

/** 摆好当前地址；`applyHostEntry` 只看 `location`。 */
function prepare(url: string): void {
  window.history.replaceState(null, "", url);
}

describe("applyHostEntry", () => {
  it("capability=conversation 落到 #/chat，并透传 agentRuntimeSessionId", () => {
    prepare("/?locale=zh-CN&capability=conversation&agentRuntimeSessionId=sess_abc");

    applyHostEntry();

    expect(window.location.hash).toBe("#/chat?agentRuntimeSessionId=sess_abc");
  });

  it("capability=observability 落到 #/sessions", () => {
    prepare("/?capability=observability");

    applyHostEntry();

    expect(window.location.hash).toBe("#/sessions");
  });

  it("expert 改写为 agentId，且与恢复参数共存", () => {
    prepare(
      "/?capability=conversation&expert=agt_1&agentRuntimeSessionId=sess_1&resumeSessionId=rsm_1"
    );

    applyHostEntry();

    const params = new URLSearchParams(window.location.hash.split("?")[1]);
    expect(params.get("agentId")).toBe("agt_1");
    expect(params.get("agentRuntimeSessionId")).toBe("sess_1");
    expect(params.get("resumeSessionId")).toBe("rsm_1");
  });

  it("哈希里已有同名参数时不覆盖（站内导航优先）", () => {
    prepare("/?capability=conversation&agentRuntimeSessionId=sess_host#/chat?agentRuntimeSessionId=sess_inner");

    applyHostEntry();

    expect(window.location.hash).toBe("#/chat?agentRuntimeSessionId=sess_inner");
  });

  it("已有哈希路由时不按 capability 重摆，但仍透传参数", () => {
    prepare("/?capability=observability&agentRuntimeSessionId=sess_x#/chat");

    applyHostEntry();

    expect(window.location.hash).toBe("#/chat?agentRuntimeSessionId=sess_x");
  });

  it("空串参数不写进哈希", () => {
    prepare("/?capability=conversation&agentRuntimeSessionId=");

    applyHostEntry();

    expect(window.location.hash).toBe("#/chat");
  });
});
