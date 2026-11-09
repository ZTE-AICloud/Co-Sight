# SkillX Alpha 使用指南

> 插件根目录：安装后为 `~/plugins/marketplaces/skillx-alpha/`。文中相对路径均相对该根目录解析。

## 一句话

把业务方的「评测命令」包成 **评测 → 缺口分析 → 优化 → 再评测** 的闭环迭代，自动循环直到达标或达到最大轮次。

## 三个命令入口

### `/skill_evolve` — 评测驱动优化

有评测管道时使用。将评测命令拆成 `--pipeline-base-dir` + `--pipeline-eval-cmd`：

```bash
/skill_evolve \
  --skill-paths /path/to/SKILL.md \
  --pipeline-base-dir /path/to/SDD评测 \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123 --nodes 特性域变更分析'
```

常用参数：`--rounds N`、`--candidates N`、`--runs N`、`--agent-name NAME`、`--consume-lib-path DIR`、`--expert-guidance TEXT`。

### `/skill_optimize` — 静态优化 / 结构重构

无评测命令时使用。`--mode` 二选一：

```bash
# LLM 9 维评分 + 多轮 hill-climb（内容质量）
/skill_optimize --mode optimize --skill-path /path/to/SKILL.md --rounds 3

# 结构层重构（plan-mode 人机协同，必走 EnterPlanMode 两次）
/skill_optimize --mode refactor --skill-path /path/to/SKILL.md
```

### `/skill_create` — 从规格说明书创建新 Skill

```bash
/skill_create --requirement "做一个把 Excel 转 Markdown 的 Skill" --skill-name excel-to-markdown
```

## 模型配置

`~/.claude/settings.json` 的 `env` 段配置（等同 claude 用 `.claude/settings.local.json`）：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
    "ANTHROPIC_MODEL": "MiniMax-M3",
    "ANTHROPIC_AUTH_TOKEN": "<your-token>"
  }
}
```

## 路径规则

- 路径配置统一从 `SKILLX_ROOT` 环境变量派生（`evolution_workspace` / `sandbox` 等子路径自动拼接）
- 业务方配置唯一入口：`config/evolve-user-config.yaml` / `optimize-user-config.yaml` / `create-user-config.yaml`
- framework 内部配置：`framework_configs/*.yaml`
- 全部编排逻辑在 `scripts/orchestrator.py`，命令只负责解析参数并调用

## 自测

```bash
cd <插件根目录>
python3 scripts/test_postfix_bugs.py      # 6/6
python3 scripts/test_eval_time_copy.py    # 7/7
```

## 详见

- [README.md](./README.md) — 插件总览与安装
- `COSIGHT.md` — cosight 唤起入口完整文档（架构边界、状态机、目录结构、约束）
- `docs/` — 产品手册 / 用户手册 / 重构原则
