# SkillX Alpha 插件

> 通用评测-优化循环编排器（Harness）：把业务方评测命令包成「评测 → 缺口分析 → 优化 → 再评测」闭环。

**SkillX Alpha** 是 skillx-alpha-agents 的 cosight 插件入口，集成 orchestrator + 15 个子 Agent + 静态/动态优化全部功能。安装后即可在任意项目中使用 `/skill_create`、`/skill_evolve`、`/skill_optimize`。

## 快速上手

### 方式一：随 npm 包自动安装（推荐）

本插件随 `@zte/cosight-cli` 打包，`npm install` 完成后由 `postinstall.cjs` 自动安装到 `~/plugins/marketplaces/skillx-alpha/`，无需手动操作。

### 方式二：手动安装

```bash
cd dist/skillx-alpha-plugin
./install.sh
```

安装脚本会：
1. 把插件组件复制到 `~/plugins/marketplaces/skillx-alpha/`
2. 注册本地 marketplace（`known_marketplaces.json`，幂等）
3. 注册插件（`installed_plugins.json`，幂等）
4. 在 `~/.claude/settings.json` 的 `enabledPlugins` 中启用 `skillx-alpha@skillx-alpha`（幂等）

重装安全：install.sh 每次会先清空旧目录再复制，保证与插件源完全一致。

## 功能

| 命令 | 用途 | 何时用 |
|------|------|--------|
| `/skill_evolve` | 评测驱动优化：评测 → 缺口分析 → 优化 → 循环直到达标 | 业务方有完整评测管道（`--pipeline-base-dir` + `--pipeline-eval-cmd`） |
| `/skill_optimize --mode optimize` | LLM 多维评分 + 多轮 hill-climb | 无 eval-cmd，用 LLM judge 打分 |
| `/skill_optimize --mode refactor` | 结构层重构（plan-mode 人机协同） | Skill 文件结构乱/超长/引用断裂 |
| `/skill_create` | 从规格说明书创建新 Skill | 0→1 创建 Skill |

## Python 依赖

```bash
pip install -r <插件根目录>/requirement.txt
```

- `jinja2` / `PyYAML` / `json_repair` / `matplotlib`（详情见 requirement.txt）

## 模型配置

在 `~/.claude/settings.json` 的 `env` 段配置模型（等同 claude 用 `.claude/settings.local.json`）：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
    "ANTHROPIC_MODEL": "MiniMax-M3",
    "ANTHROPIC_AUTH_TOKEN": "<your-token>"
  }
}
```

cosight CLI 自动加载并注入到子进程环境变量。

## 业务方配置

`config/evolve-user-config.yaml` / `optimize-user-config.yaml` / `create-user-config.yaml` 是**业务方唯一配置入口**。路径配置统一从环境变量 `SKILLX_ROOT` 派生，避免硬编码绝对路径。

## 目录结构

```
skillx-alpha-plugin/
├── install.sh              # 安装脚本（手动安装入口）
├── .cosight-plugin/        # 插件元数据
│   ├── marketplace.json
│   ├── plugin.json
│   ├── README.md
│   └── SKILLX.md
├──                # cosight 组件（commands / agents / skills / rules）
├── scripts/                # Python 编排代码（orchestrator.py 等）
├── config/                 # 业务方配置入口
├── framework_configs/      # framework 配置（评分模板、提案 schema）
├── docs/                   # 设计/重构/用户文档
├── COSIGHT.md              # cosight 唤起入口文档
└── requirement.txt         # Python 依赖
```

> 安装后所有相对路径（`scripts/…`、`config/…`、`framework_configs/…`）均相对**插件根目录**解析，install.sh 会把占位符替换为实际安装路径。

## 自测

```bash
cd <插件根目录>

# Python 单元测试
python3 scripts/test_postfix_bugs.py       # 6/6
python3 scripts/test_eval_time_copy.py     # 7/7

# 端到端单 Skill（mock LLM）
python3 scripts/mock_llm_server.py --port 18080 &
python3 scripts/orchestrator.py --mode static \
  --skill-path tests/fixtures/mock-skill/SKILL.md --max-rounds 1 --non-interactive
```

## 版本

- **版本**: 1.0.0
- **License**: MIT
