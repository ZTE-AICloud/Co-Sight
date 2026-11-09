# SkillX Cosight 自测指南

## 核心自测：skill 静态优化功能

### 步骤 1：启动 mock LLM server（可选，无 API key 时）

```bash
cd /media/vdb/skillx-alpha/cosight-agent-core/extensions/skillx-cosight
python3 scripts/mock_llm_server.py --port 18080
```

### 步骤 2：确认 config 指向 mock 或真实 LLM

- 默认 `config/optimize-user-config.yaml` 含真实 API key（公司内网 ccr）
- 如用 mock，编辑 `config/optimize-user-config.yaml` 改 `llm_api.model.base_url` 为 `http://127.0.0.1:18080`

### 步骤 3：跑端到端单 Skill 模式

```bash
python3 scripts/orchestrator.py \
  --mode static \
  --skill-path tests/fixtures/mock-skill/SKILL.md \
  --max-rounds 3 \
  --break-threshold 0.5 \
  --non-interactive
```

**预期产物**：
- `evolution_workspace/skill_optimize_taskid_*/` 完整目录
- `best_skill/<Skill名>/SKILL.md`
- `skill_optimize_report.html`

### 步骤 4：跑多 Skill 模式

```bash
python3 scripts/orchestrator.py \
  --mode static \
  --agent-path tests/fixtures/mock-skill-agent \
  --max-rounds 1 --per-skill-rounds 1 --break-threshold 0.5 --non-interactive
```

## Python 单元测试

```bash
python3 scripts/test_postfix_bugs.py       # 6/6
python3 scripts/test_eval_time_copy.py     # 7/7
```

## cosight 集成（需 cosight 大仓 build）

```bash
cd /media/vdb/skillx-alpha/cosight-agent-core
pnpm test:contracts:plugins
node openclaw.mjs status --json
node openclaw.mjs qa suite --provider-mode mock-openai \
  --scenario plugin-skillx-cosight-optimize
node openclaw.mjs skillx-cosight optimize <SKILL.md>
```

## Known limitations

- 本环境无 typescript / tsc / pnpm install 慢，cosight 集成测试需在能 build cosight 的环境跑
- mock LLM 的修改提议需要 old_text 精确匹配 SKILL.md，否则 mods=0（不影响流程跑通）