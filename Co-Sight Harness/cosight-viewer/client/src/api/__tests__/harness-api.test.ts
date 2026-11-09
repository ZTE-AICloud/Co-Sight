// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import {
  fetchAgentPage,
  fetchEngineCommands,
  fetchModelsAsOptions,
  fetchServiceAgent,
  HARNESS_API_BASE,
  resolveServiceAssetUrl,
} from "../harness-api";
import { AGENT_RUNTIME_API_URL } from "../../config/api-config";

/**
 * 适配层的行为约定:模型来自**框架**,智能体来自 **smart-factory**。
 *
 * 模型最重要的两条:
 *   1. **请求打在浏览器面 `/api/models` 上**,不是模块面 `/api/framework/v1/models`
 *      (后者对带 `Origin` 的请求一律 403,浏览器调不通),也不是 `/models/active`
 *      —— 那个只回单个模型,当年被当成数组用,是选择器空的根因。
 *   2. 默认项 = `isActive` 那条;没有生效模型时给 `null`,**不**回落到第一项。
 *
 * 智能体:裸 JSON(`{items,total}`,没有信封)、分页 + `keyword`/`source`。
 */

const fetchMock = vi.fn();

/** 一次成功的信封响应。`data` 就是 `ModelConfig[]`(浏览器面契约)。 */
function respond(models: unknown): unknown {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => ({ success: true, data: models, error: null, meta: null }),
  };
}

/** 一个模型对象:只给适配层真正读的四个字段,其余字段它不看。 */
function model(id: string, label: string, isActive: boolean) {
  return { id, label, modelName: `name-${id}`, isActive };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchModelsAsOptions", () => {
  it("请求打在浏览器面的 /api/models 上", async () => {
    fetchMock.mockResolvedValue(respond([]));

    await fetchModelsAsOptions();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${HARNESS_API_BASE}/models`);
  });

  it("label 映射成下拉名,label 为空回落到 modelName", async () => {
    fetchMock.mockResolvedValue(
      respond([
        { id: "m1", label: "内部 Qwen3-32B", modelName: "qwen3-32b", isActive: false },
        { id: "m2", label: "", modelName: "glm-5.1", isActive: true },
      ])
    );

    const { options } = await fetchModelsAsOptions();

    expect(options).toEqual([
      { id: "m1", name: "内部 Qwen3-32B" },
      { id: "m2", name: "glm-5.1" },
    ]);
  });

  it("默认项 = isActive 那条,而不是列表第一项", async () => {
    // 生效的那条故意不排第一:否则"取第一项"的旧实现也能蒙对,测不出差别
    fetchMock.mockResolvedValue(
      respond([model("m1", "甲", false), model("m2", "乙", true), model("m3", "丙", false)])
    );

    const { defaultModelId } = await fetchModelsAsOptions();

    expect(defaultModelId).toBe("m2");
  });

  it("没有生效模型时列表照常给、默认项为 null(不回落第一项)", async () => {
    fetchMock.mockResolvedValue(respond([model("m1", "甲", false), model("m2", "乙", false)]));

    const { options, defaultModelId } = await fetchModelsAsOptions();

    expect(options).toHaveLength(2);
    expect(defaultModelId).toBeNull();
  });

  it("一个模型都没配(data: null)是空集,不是错误", async () => {
    fetchMock.mockResolvedValue(respond(null));

    const { options, defaultModelId } = await fetchModelsAsOptions();

    expect(options).toEqual([]);
    expect(defaultModelId).toBeNull();
  });

  it("HTTP 非 2xx 抛错,由调用方兜底成空列表", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, statusText: "Internal Server Error" });

    await expect(fetchModelsAsOptions()).rejects.toThrow("HTTP 500");
  });

  it("信封里 success: false 抛错并带上后端的话", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        success: false,
        data: null,
        error: { code: "BOOM", message: "读取模型配置失败" },
        meta: null,
      }),
    });

    await expect(fetchModelsAsOptions()).rejects.toThrow("读取模型配置失败");
  });
});

/** 造 `count` 位专家(只给选择器真正读的字段,序号用于断言取到的是哪几页)。 */
/** smart-factory 的裸 JSON 响应(成功时没有 `{success,data}` 信封)。 */
function respondBare(body: unknown): unknown {
  return { ok: true, status: 200, statusText: "OK", json: async () => body };
}

/** 造 `count` 个 agent(只给适配层真正读的字段)。 */
function agents(count: number, offset = 0): unknown[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `agt_${String(offset + index)}`,
    workspaceId: "ws-1",
    name: `智能体${String(offset + index)}`,
    description: "",
    tags: [],
    icon: "",
    source: "user",
    status: "completed",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
  }));
}

/**
 * 逐页取的契约:页码/筛选要跟着走,`hasMore` 用响应的 `total` 判断。
 *
 * 判错两端都难查:判成 false 会**少给**(用户以为"就这么几位"),判成 true 会无限往下滚。
 * 这里刻意用 `total` 而不是"这一页满员" —— 服务端会把 pageSize 夹到上限,满页推断会误判。
 */
/**
 * 封面图地址补全。
 *
 * 服务端给的是 `/api/smart-factory/v1/files/...`（相对它自己的源），而 chat 页面跑在
 * 4830 的 iframe 里；原样塞进 `<img src>` 会打到 viewer 自己 → 404。
 */
describe("resolveServiceAssetUrl", () => {
  it("把 /api 开头的相对地址补成 smart-factory 的绝对地址", () => {
    const origin = new URL(AGENT_RUNTIME_API_URL).origin;

    expect(resolveServiceAssetUrl("/api/smart-factory/v1/files/fil_1.png")).toBe(
      `${origin}/api/smart-factory/v1/files/fil_1.png`,
    );
  });

  it("emoji / 文本 / 绝对地址原样返回", () => {
    for (const value of ["🤖", "文件", "https://cdn.example.com/a.png", "data:image/png;base64,AA"]) {
      expect(resolveServiceAssetUrl(value)).toBe(value);
    }
  });

  it("分页接口返回的图标已经补全", async () => {
    const origin = new URL(AGENT_RUNTIME_API_URL).origin;
    fetchMock.mockResolvedValueOnce(
      respondBare({
        items: [
          { ...(agents(1, 0)[0] as Record<string, unknown>), icon: "/api/smart-factory/v1/files/a.png" },
        ],
        total: 1,
      }),
    );

    const result = await fetchAgentPage();

    expect(result.items[0]?.icon).toBe(`${origin}/api/smart-factory/v1/files/a.png`);
  });
});

describe("fetchAgentPage 的分页", () => {
  const BASE = `${AGENT_RUNTIME_API_URL}/agents`;

  it("页码与筛选条件都带上,并按 total 判断还有下一页", async () => {
    // 共 180 条:第 2 页(60..119)之后还有一页,所以 hasMore 应为 true
    fetchMock.mockResolvedValueOnce(respondBare({ items: agents(60, 60), total: 180 }));

    const result = await fetchAgentPage({ keyword: "架构", source: "builtin" }, 2);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `${BASE}?page=2&pageSize=60&keyword=${encodeURIComponent("架构")}&source=builtin`,
    );
    expect(result.items).toHaveLength(60);
    expect(result.hasMore).toBe(true);
  });

  it("已加载到 total 之后不再报告还有下一页", async () => {
    fetchMock.mockResolvedValueOnce(respondBare({ items: agents(5, 60), total: 65 }));

    const result = await fetchAgentPage({}, 2);

    expect(result.hasMore).toBe(false);
  });

  it("空结果是合法结果,不是错误(没命中就是没命中)", async () => {
    fetchMock.mockResolvedValueOnce(respondBare({ items: [], total: 0 }));

    const result = await fetchAgentPage({ keyword: "不存在的关键字" });

    expect(result.items).toEqual([]);
    expect(result.hasMore).toBe(false);
  });

  it("source=all 与空关键字不塞参数", async () => {
    fetchMock.mockResolvedValueOnce(respondBare({ items: agents(1), total: 1 }));

    await fetchAgentPage({ keyword: "", source: "all" });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${BASE}?page=1&pageSize=60`);
  });

  it("HTTP 非 2xx 抛错(由选择器兜底成错误态)", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    await expect(fetchAgentPage()).rejects.toThrow("HTTP 500");
  });

  it("带 status 时把状态筛选交给服务端", async () => {
    fetchMock.mockResolvedValueOnce(respondBare({ items: [], total: 0 }));

    await fetchAgentPage({ source: "builtin", status: "completed" }, 2);

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `${BASE}?page=2&pageSize=60&source=builtin&status=completed`,
    );
  });

  it("不传 status 时不带该参数", async () => {
    fetchMock.mockResolvedValueOnce(respondBare({ items: [], total: 0 }));

    await fetchAgentPage({ keyword: "天气" });

    expect(fetchMock.mock.calls[0]?.[0]).not.toContain("status=");
  });
});

describe("fetchEngineCommands", () => {
  const BASE = `${AGENT_RUNTIME_API_URL}/engine/commands/list`;

  it("不传 cwd 时只请求命令清单（自由对话的默认口径）", async () => {
    fetchMock.mockResolvedValueOnce(
      respondBare({
        engine: "claude-cli",
        cwd: "/home/me",
        items: [
          { name: "task-monitor", description: "监控", argumentHint: "" },
          { name: "omni-rsdd:sdd", description: "SDD", argumentHint: "--strict" },
        ],
      }),
    );

    const items = await fetchEngineCommands();

    expect(fetchMock.mock.calls[0]?.[0]).toBe(BASE);
    expect(items.map((item) => item.name)).toEqual(["task-monitor", "omni-rsdd:sdd"]);
  });

  it("传 cwd 时作为 query 参数发送", async () => {
    fetchMock.mockResolvedValueOnce(
      respondBare({ engine: "claude-cli", cwd: "/ws", items: [] }),
    );

    await fetchEngineCommands("F:\\code\\test");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `${BASE}?cwd=${encodeURIComponent("F:\\code\\test")}`,
    );
  });

  it("空 cwd 视为未传", async () => {
    fetchMock.mockResolvedValueOnce(respondBare({ engine: "e", cwd: "/", items: [] }));

    await fetchEngineCommands("   ");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(BASE);
  });
});

/**
 * 单条查询:选中/恢复一个智能体只该打一次详情接口。
 *
 * 旧实现是"全量翻页再 find",agent 多时一次选择要串行拉 ⌈N/60⌉ 页;
 * 这里钉住"只发一次请求、路径是单条接口"。
 */
describe("fetchServiceAgent", () => {
  const BASE = `${AGENT_RUNTIME_API_URL}/agents`;

  it("只打一次单条接口,并映射成下拉/会话用的形状", async () => {
    fetchMock.mockResolvedValueOnce(
      respondBare({
        ...(agents(1, 0)[0] as Record<string, unknown>),
        id: "agt_42",
        name: "四则运算",
        description: "帮我算数",
        icon: "",
        commands: [
          {
            name: "build",
            namespace: "",
            description: "构建项目",
            path: "/ws/.claude/commands/build.md",
            updatedAt: "2026-01-01T00:00:00.000Z",
          },
        ],
        skills: [
          {
            name: "weather-query",
            displayName: "weather-query",
            description: "城市天气查询",
            path: "/ws/.claude/skills/weather-query",
            updatedAt: "2026-01-01T00:00:00.000Z",
          },
        ],
      }),
    );

    const agent = await fetchServiceAgent("agt_42");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${BASE}/agt_42`);
    expect(agent).toMatchObject({
      id: "agt_42",
      name: "四则运算",
      // 空串封面 → undefined:组件据此落名称首字头像
      icon: undefined,
      description: "帮我算数",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:00.000Z",
      // 工作区 id 进入适配层：会话工作区根推导要用
      workspaceId: "ws-1",
      commands: [
        {
          name: "build",
          namespace: "",
          description: "构建项目",
          path: "/ws/.claude/commands/build.md",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      ],
      skills: [
        {
          name: "weather-query",
          displayName: "weather-query",
          description: "城市天气查询",
          path: "/ws/.claude/skills/weather-query",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      ],
    });
  });

  it("id 里的特殊字符会转义,不会拼出别的路径", async () => {
    fetchMock.mockResolvedValueOnce(respondBare(agents(1)[0]));

    await fetchServiceAgent("agt/../x");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${BASE}/agt%2F..%2Fx`);
  });

  it("查不到(404)返回 null,而不是把错误抛给调用方", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await expect(fetchServiceAgent("agt_missing")).resolves.toBeNull();
  });

  it("网络失败同样返回 null", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(fetchServiceAgent("agt_42")).resolves.toBeNull();
  });
});
