# SkillX Cosight

> 通用评测-优化循环编排器（Harness），把业务方评测命令包成「评测 → 缺口分析 → 优化 → 再评测」闭环。

**SkillX Cosight** 是 skillx-alpha-agents 的入口，集成 orchestrator + 16 个子 Agent + 静态/动态优化全部功能，可装到 **Claude Code / Cosight / Codex / DSH** 四种 runtime。

## 功能

- `/skill_optimize` — 静态优化：多维评分 + 多轮 hill-climb + 触顶 break；`--mode refactor` 结构层重构
- `/skill_evolve` — 评测驱动：业务方 eval-cmd + 缺口分析 + 优化（推荐使用 `--pipeline-base-dir` + `--pipeline-eval-cmd` 简化入参；纯 shell 命令可用 `--pipeline-eval-sh` 跳过自动 wrap）
- `/skill_create` — 从规格说明书创建新 Skill

## 安装

### 前置要求

- Python 3.8+ 与 `pip3`（`scripts/requirements.txt` 的依赖由 install.sh 自动安装，可用 `--no-pip` 跳过）
- 目标 runtime 的 CLI 已安装并被 `PATH` 发现（Claude Code `claude` / Cosight `cosight` / Codex `codex` / DSH `dsh`）

### 方式一：打包分发安装（推荐，多机/多用户）

```bash
cd skill-optimizer

# 1) 打成可分发包
./scripts/pack.sh      # → dist/skill-optimizer-v<version>-<utc-ts>.tar.gz

# 2) 安装（默认装到 Claude Code）
./scripts/install.sh --from dist/skill-optimizer-v<version>-<utc-ts>.tar.gz
```

### 方式二：从源码安装（本仓库直接装）

```bash
# Claude Code（默认，官方插件机制）
./scripts/install.sh

# 指定 runtime
./scripts/install.sh --runtime claude    # Claude Code 官方插件
./scripts/install.sh --runtime cosight   # Cosight 原生宿主（marketplace 注册 + .cosight 快照）
./scripts/install.sh --runtime codex     # Codex 插件（market 即本仓库）
./scripts/install.sh --runtime dsh       # DSH 同步 + 无头命令
./scripts/install.sh --runtime all       # 自动探测已装 CLI，分别安装
```

### 方式三：开发模式（marketplace 直指本仓库，改动即时生效）

```bash
./scripts/install.sh --dev
```

### 常用参数

```bash
./scripts/install.sh --scope project     # 装到项目 scope（默认 user，仅 claude）
./scripts/install.sh --no-pip            # 跳过 python 依赖安装
DEST=/tmp/cache ./scripts/install.sh     # 离线 cp 到指定根（CI/测试场景，仅 claude）
```

> 安装脚本每次会先清空目标中的旧目录再复制，与源码保持一致。**安装完成后需重启 Claude Code / Cosight 会话**，命令才会出现在面板里。

## 使用

```bash
# 单 Skill 优化（插件 slash command）
/skill_optimize /path/to/SKILL.md

# 评测驱动优化（业务方提供 eval-cmd）
/skill_evolve --skill-paths /path/to/SKILL.md \
  --pipeline-base-dir /path/to/eval \
  --pipeline-eval-cmd 'python3 scripts/run_batch.py RAN-123'

# 从规格说明书创建新 Skill（0→1，4 阶段流水线）
/skill_create --requirement "把 Excel 转成 Markdown 的 Skill" \
  --skill-name excel-to-markdown
```

三个入口构成闭环：`/skill_create`（0→1 创建）→ `/skill_optimize`（静态评分/重构）→ `/skill_evolve`（评测驱动拉满）。

## Python 依赖

```bash
pip3 install -r scripts/requirements.txt
```

（`install.sh` 默认自动安装，此处仅用于手动安装场景。）

## 模型配置

推荐在**用户级** `~/.claude/settings.json` 的 `env` 段配置模型（runtime 自动加载并注入到子进程环境变量；项目内用 `.claude/settings.local.json` 亦可，仅对该项目生效）：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic",
    "ANTHROPIC_MODEL": "MiniMax-M3",
    "ANTHROPIC_AUTH_TOKEN": "<your-token>"
  }
}
```

也可使用任意 **Anthropic Messages 兼容端点**（已在三环境实验中实测）。例如火山引擎方舟：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://ark.cn-beijing.volces.com/api/plan",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_API_KEY": "<your-ark-key>"
  }
}
```

> 该端点必须支持 `POST <base>/v1/messages`（Anthropic 协议），而不是仅 OpenAI 兼容的 `/chat/completions`。

不同 runtime 的凭证要求：

| runtime | 配置方式 |
|---|---|
| claude | `~/.claude/settings.json` 的 `env` 段（如上） |
| codex | `~/.codex/config.toml` 的 provider/model（或其上游网关） |
| dsh | `~/.dsh/settings.yaml` 的 provider `baseURL` + 环境变量 `ANTHROPIC_API_KEY` |

## 业务方配置

`config/evolve-user-config.yaml` / `optimize-user-config.yaml` / `create-user-config.yaml` 是**业务方唯一配置入口**。

路径配置统一从 `SKILLX_ROOT` 环境变量派生（`evolution_workspace` / `sandbox` 等子路径自动拼接），避免硬编码绝对路径。

## 实战示例：goldeval 评测驱动进化（三环境实测）

以下例子即三环境（Claude Code / Codex / DSH）验证所用的完整链路，可直接照抄。

### 1. 准备实验目录

```
exp/
├── skill/SKILL.md          # 待优化 Skill（含已知缺陷）
├── 数据/extract_v2.jsonl   # 黄金数据集（input / expected_output）
└── eval_extract.py         # 评测命令
```

数据集每行至少含 `input`、`expected_output`；评测命令负责"用当前 Skill 生成 output → 用 goldeval 打分"。

### 2. 评测命令 `eval_extract.py`

核心三步：① 用 SKILL.md + `claude -p` 逐条生成 `output`；② `goldeval run` 评测；③ 汇总成 `summary.json`。

```python
#!/usr/bin/env python3
"""评测命令：SKILL.md 生成 output → goldeval 评测 → data/phase3-eval/summary.json"""
import json, os, subprocess, sys, glob, argparse

GOLEVAL_DIR = "/path/to/agent-evaluator/skills/goldeval"

def call_claude(prompt: str) -> str:
    res = subprocess.run(["claude", "-p", prompt, "--output-format", "json"],
                         capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        raise RuntimeError(res.stderr[-500:])
    out = json.loads(res.stdout)
    return out.get("result", "") if isinstance(out, dict) else res.stdout

def strip_fence(t: str) -> str:
    t = t.strip()
    if t.startswith("```"):
        lines = t.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="./skill/SKILL.md")
    ap.add_argument("--dataset", default="./数据/extract_v2.jsonl")
    ap.add_argument("--out", default="./data/phase3-eval")
    args = ap.parse_args()

    skill = open(args.skill, encoding="utf-8").read()
    rows = [json.loads(l) for l in open(args.dataset, encoding="utf-8")]
    os.makedirs(args.out, exist_ok=True)
    outputs = os.path.join(args.out, "outputs.jsonl")

    with open(outputs, "w", encoding="utf-8") as fo:
        for row in rows:
            prompt = f"{skill}\n\n---\n需求文本：\n{row['input']}\n\n只输出 JSON 产物。"
            row["output"] = strip_fence(call_claude(prompt))
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
            fo.flush()

    gdir = os.path.normpath(os.path.join(args.out, "..", "goldeval"))
    os.makedirs(gdir, exist_ok=True)
    r = subprocess.run(["node", "scripts/run.ts",
                        "--dataset", os.path.abspath(outputs),
                        "--evaluators", "f1_score,precision,recall",
                        "--outputs", os.path.abspath(gdir)],
                       cwd=GOLEVAL_DIR, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr); sys.exit(1)

    latest = sorted(glob.glob(os.path.join(gdir, "eval_results", "*")),
                    key=os.path.getmtime)[-1]
    per_case = {}
    for line in open(os.path.join(latest, "f1_score_results.jsonl"), encoding="utf-8"):
        rec = json.loads(line)
        per_case[str(rec["data_id"])] = round(rec.get("score", 0) * 100, 2)
    summary = {
        "result_score": round(sum(per_case.values()) / len(per_case), 2) if per_case else 0.0,
        "result_score_per_case": per_case,
    }
    json.dump(summary, open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[summary] result_score={summary['result_score']}")

if __name__ == "__main__":
    main()
```

### 3. 业务方配置（`config/evolve-user-config.yaml`）

```yaml
paths:
  root: /path/to/exp
  need_cleaned_dir:
    - /path/to/exp/data          # 每轮评测前清空，防读到上次产物

filter:
  case_ids: []                   # 空 = 全量跑

score_extraction:
  structure: |
    产物在 data/phase3-eval/ 下：
    - summary.json：{"result_score": 0~100, "result_score_per_case": {case_id: 0~100}}
  extraction: |
    读取 summary.json 的 result_score 与 result_score_per_case。
  handling: |
    summary.json 缺失 → 记 0 分并在 zero_root_cause 记录原因。
```

### 4. 启动（同一份代码，切换 runtime）

```bash
# Claude Code
SKILLX_ROOT=/path/to/exp python3 <plugin>/scripts/orchestrator.py --mode eval \
  --skill-path /path/to/exp/skill/SKILL.md \
  --pipeline-base-dir /path/to/exp \
  --pipeline-eval-sh 'python3 eval_extract.py' \
  --max-rounds 1 --eval-runs-per-candidate 1 --non-interactive

# Codex（需要 codex CLI 与其模型链路可用）
SKILLX_AGENT_CLI=codex SKILLX_ROOT=/path/to/exp python3 <plugin>/scripts/orchestrator.py ...

# DSH（需要 ANTHROPIC_API_KEY 与 ~/.dsh/settings.yaml 的 baseURL）
SKILLX_AGENT_CLI=dsh ANTHROPIC_API_KEY=<key> SKILLX_ROOT=/path/to/exp python3 <plugin>/scripts/orchestrator.py ...
```

### 5. 预期输出

```
[baseline] 基线平均: 64.8
Round 1: 候选 1 = 100.0
✅ 候选 c1 达到目标分 100，本轮结束后终止迭代
最终状态: achieved   总轮次: 1   最佳得分: 100.0
```

产物在 `evolution_workspace/taskid_*/`：`baseline/`（基线评测）、`round_1/`（候选 + 提案）、`skill/`（最终 Skill）、`审查报告.md`、`score_history.md`。

> 实测结果（req-extract / 5 case / goldeval F1）：Claude Code 64.8→100、Codex 63.6→100、DSH 46.6→100，均 `achieved`。

## 自测

```bash
cd <项目根目录>

# Python 单元测试
python3 scripts/test_postfix_bugs.py       # 6/6
python3 scripts/test_eval_time_copy.py     # 7/7

# 端到端单 Skill（mock LLM）
python3 scripts/mock_llm_server.py --port 18080 &
python3 scripts/orchestrator.py --mode static \
  --skill-path tests/fixtures/mock-skill/SKILL.md --max-rounds 1 --non-interactive

# 真实 LLM（需 ANTHROPIC_* env 或 config 内 api_key）
python3 scripts/orchestrator.py --mode static \
  --skill-path /path/to/real/SKILL.md --max-rounds 3 --break-threshold 2.0 --non-interactive
```

