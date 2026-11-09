**中文** | [English](README.md)

# CoSight Viewer

CoSight Viewer 是 Co-Sight Harness 的**会话监控组件**：实时查看 Claude Code 的会话活动、事件流和运行状态。通过 Hook 机制自动捕获 Claude Code 的执行过程，提供 Web 界面进行可视化监控。

## 核心能力

| 能力     | 说明                                           |
| -------- | ---------------------------------------------- |
| 会话列表 | 查看所有 Claude Code 会话，支持搜索和过滤      |
| 会话详情 | 查看单个会话的完整事件流、工具调用、Token 消耗 |
| 实时监控 | WebSocket 推送，实时更新会话状态               |
| 项目监控 | 自动捕获项目路径（cwd），按项目分组查看        |

## 快速开始

```bash
# 方式 1：一键启动（推荐）
./scripts/start.sh

# 方式 2：手动启动
npm install        # 安装依赖（会自动启动服务）
npm run start      # 如果服务未启动，手动启动
```

访问地址：http://localhost:4830

**说明**：

- `npm install` 会触发 `postinstall` 脚本，自动构建客户端并启动服务
- `./scripts/start.sh` 会检查依赖状态，未安装则执行 `npm install`，已安装则直接启动

## 命令与脚本

### NPM 命令

| 命令                      | 作用                            |
| ------------------------- | ------------------------------- |
| `npm run setup`         | 安装所有依赖（服务端 + 客户端） |
| `npm run build`         | 构建客户端（生成 dist）         |
| `npm run start`         | 启动服务（后台运行）            |
| `npm run stop`          | 停止服务                        |
| `npm run install-hooks` | 安装 Claude Code hooks          |
| `npm run selfcheck`     | 环境诊断                        |

### CLI 命令

```bash
# 启动服务
npx co-sight-viewer start

# 停止服务
npx co-sight-viewer stop

# 查看状态
npx co-sight-viewer status

# 环境诊断
npx co-sight-viewer selfcheck

# 完整卸载
npx co-sight-viewer uninstall
```

### 独立脚本

| 脚本                         | 作用                              |
| ---------------------------- | --------------------------------- |
| `scripts/start.sh`         | 一键启动（检查依赖 → 安装/启动） |
| `scripts/cli.js`           | CLI 入口                          |
| `scripts/install-hooks.js` | 安装 hooks                        |
| `scripts/selfcheck.js`     | 环境诊断                          |
| `scripts/uninstall.js`     | 完整卸载                          |

## 配置

### 环境变量

| 变量              | 默认值   | 说明     |
| ----------------- | -------- | -------- |
| `CO_SIGHT_PORT` | `4830` | 服务端口 |

## 数据存储

CoSight Viewer 的数据保存在以下目录：

**数据目录：**

```
~/.cosight-harness/cosight-viewer/
```

**文件结构：**

```
~/.cosight-harness/cosight-viewer/
├── dashboard.db          # 主数据库（会话、事件、Token 等）
├── settings.json         # viewer 配置（自动清理等，按功能分段便于扩展）
├── state.json            # 运行状态（如上次自动清理结果）
└── transcripts/          # 转录快照（导入会话的备份）
```

**说明：**

- 目录不存在时会自动创建
- 数据库文件：`dashboard.db`
- 与 Claude Code（`~/.claude/`）的数据目录平级

## 停止与卸载

```bash
# 停止服务
npm run stop

# 完整卸载（清理 hooks、数据、日志）
npx co-sight-viewer uninstall
```

## 致谢

本项目的设计与实现，参考并复用了开源项目 [**Claude-Code-Agent-Monitor**](https://github.com/hoangsonww/Claude-Code-Agent-Monitor) 的部分代码，谨向该项目及其作者、社区致以谢意。

- 上游许可证：MIT
- 上游版权：Copyright (c) 2026 - Now, Son Nguyen
- 按 MIT 许可证要求，上游版权声明与许可声明已完整保留于 [NOTICE](NOTICE)。

## 许可证

本项目以 [Apache License 2.0](LICENSE) 许可发布。

本项目部分内容派生自 [Claude-Code-Agent-Monitor](https://github.com/hoangsonww/Claude-Code-Agent-Monitor)（MIT 许可）。上游版权声明与许可声明已完整保留于 [NOTICE](NOTICE)。
