// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";

import type { AgentCommand, AgentSkill } from "../../../api/agent-api";
import {
  buildEngineSlashCommands,
  buildSlashCommands,
  commandLabel,
  filterSlashCommands,
  groupSlashCommands,
  slashContextAt,
} from "../slash-commands";

function command(name: string, description = ""): AgentCommand {
  return {
    name,
    namespace: "",
    description,
    path: `/ws/.claude/commands/${name}.md`,
    updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

function skill(name: string, description = ""): AgentSkill {
  return {
    name,
    displayName: name,
    description,
    path: `/ws/.claude/skills/${name}`,
    updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

const commands = [command("build", "构建项目并跑全量校验"), command("test", "跑测试")];
const skills = [skill("weather-query", "城市天气查询"), skill("csv-statistics-export", "")];
const items = buildSlashCommands(commands, skills);

describe("slashContextAt", () => {
  it("detects a bare slash at the end", () => {
    expect(slashContextAt("/", 1)).toEqual({ start: 0, query: "" });
  });

  it("detects the query after the slash", () => {
    expect(slashContextAt("/bu", 3)).toEqual({ start: 0, query: "bu" });
  });

  it("allows leading whitespace (send trims it)", () => {
    expect(slashContextAt("  /bu", 5)).toEqual({ start: 2, query: "bu" });
    expect(slashContextAt("\n/bu", 4)).toEqual({ start: 1, query: "bu" });
  });

  it("rejects a slash in the middle of the message", () => {
    expect(slashContextAt("请用 /build", 9)).toBeNull();
  });

  it("rejects once arguments follow the command", () => {
    expect(slashContextAt("/build --fast", 13)).toBeNull();
    expect(slashContextAt("/build ", 7)).toBeNull();
  });

  it("rejects URLs and ordinary text", () => {
    expect(slashContextAt("https://example.com", 19)).toBeNull();
    expect(slashContextAt("and/or", 7)).toBeNull();
  });

  it("only checks the text before the caret", () => {
    expect(slashContextAt("/bu xxx", 3)).toEqual({ start: 0, query: "bu" });
  });
});

describe("buildSlashCommands", () => {
  it("lists commands before skills", () => {
    expect(items.map((item) => `${item.kind}:${item.name}`)).toEqual([
      "command:build",
      "command:test",
      "skill:weather-query",
      "skill:csv-statistics-export",
    ]);
  });

  it("keeps the command when a skill has the same name", () => {
    const merged = buildSlashCommands([command("build", "命令")], [skill("build", "技能")]);
    expect(merged).toEqual([{ kind: "command", name: "build", description: "命令" }]);
  });

  it("skips empty names", () => {
    expect(buildSlashCommands([command("")], [skill("")])).toEqual([]);
  });
});

describe("buildEngineSlashCommands", () => {
  it("maps engine entries to the command group", () => {
    expect(
      buildEngineSlashCommands([
        { name: "task-monitor", description: "监控" },
        { name: "omni-rsdd:sdd", description: "SDD" },
      ]),
    ).toEqual([
      { kind: "command", name: "task-monitor", description: "监控" },
      { kind: "command", name: "omni-rsdd:sdd", description: "SDD" },
    ]);
  });

  it("skips empty and duplicate names", () => {
    expect(
      buildEngineSlashCommands([
        { name: "", description: "空" },
        { name: "dup", description: "第一次" },
        { name: "dup", description: "第二次" },
      ]),
    ).toEqual([{ kind: "command", name: "dup", description: "第一次" }]);
  });

  it("tolerates a missing list", () => {
    expect(buildEngineSlashCommands()).toEqual([]);
  });
});

describe("filtering", () => {
  it("returns everything for an empty query", () => {
    expect(filterSlashCommands(items, "")).toEqual(items);
  });

  it("ranks name prefix first, then name contains, then description", () => {
    const list = buildSlashCommands(
      [command("rebuild"), command("build"), command("deploy", "build helper")],
      []
    );

    expect(filterSlashCommands(list, "build").map((item) => item.name)).toEqual([
      "build",
      "rebuild",
      "deploy",
    ]);
  });

  it("matches skill names and descriptions too", () => {
    expect(filterSlashCommands(items, "weather").map((item) => item.name)).toEqual([
      "weather-query",
    ]);
    expect(filterSlashCommands(items, "城市").map((item) => item.name)).toEqual([
      "weather-query",
    ]);
  });

  it("keeps command and skill groups separate when filtering", () => {
    const list = buildSlashCommands(
      [command("build"), command("weather")],
      [skill("weather-query"), skill("build-helper")]
    );

    expect(
      groupSlashCommands(list, "weather").map((item) => `${item.kind}:${item.name}`)
    ).toEqual(["command:weather", "skill:weather-query"]);
  });

  it("returns an empty list when nothing matches", () => {
    expect(filterSlashCommands(items, "zzz")).toEqual([]);
  });
});

describe("commandLabel", () => {
  it("uses the name only", () => {
    expect(commandLabel({ name: "test" })).toBe("/test");
    expect(commandLabel({ name: "weather-query" })).toBe("/weather-query");
  });
});
