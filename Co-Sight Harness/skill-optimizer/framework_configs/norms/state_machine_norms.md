# 状态机与 Revision Loop 通用规范

> 适用于所有 `/skill_create` 工作流生成的 Skill,尤其是**包含 LLM 断点**的 Skill。
> 不绑定任何特定业务领域。

## 为什么需要状态机

LLM 断点的 Skill 通常流程较长(8+ 步骤),且 LLM 响应**不可靠**(JSON 格式错误、字段缺失、语义不合理)。没有状态机时:

- ❌ 任意一步失败 → 必须从头重跑
- ❌ LLM 响应格式错误 → 必须从头重跑
- ❌ 校验失败 → 必须从头重跑
- ❌ 进程崩溃 → 中间产物丢失

**状态机 + revision loop 解决这些问题**:支持任意断点恢复 + 自动回退修正。

## 通用 checkpoint 命名约定

子 Agent 写 spec / impl 时,使用以下**通用** checkpoint 命名(不含业务字段):

| 状态 | 含义 |
|------|------|
| `init` | 流程启动 |
| `step{N}_done` | 步骤 N 已完成 |
| `step{N}_pending` | 步骤 N 需要 LLM 推理(已写入任务文件,等 CC) |
| `step{N}_llm_done` | 步骤 N LLM 推理完成,正在应用响应 |
| `error` | 异常终止(可恢复) |

> **N 是 spec 步骤号**,从 spec §4 推断。**不绑特定业务**。

## 通用状态持久化文件

每个有 LLM 断点的 Skill 必须包含**状态文件**,记录当前 checkpoint:

```json
{
  "checkpoint": "step7_pending",
  "last_updated": "2026-07-13T10:30:00",
  "phase_history": [
    {"phase": "init", "status": "done", "timestamp": "...", "retry_count": 0},
    {"phase": "step7_pending", "status": "running", "timestamp": "...", "retry_count": 1}
  ]
}
```

**文件命名**:`run_state.json`(约定俗成,可被 CC/外部监控脚本识别)
**存放路径**:`${workspace}/middle_content/{skill-name}/run_state.json`

## 通用 Revision Loop 模式

### 触发场景

任意校验脚本(validate_topology / validate_content / validate_output)失败 → 应**自动回退**到最近的 LLM 断点 pending 状态,允许用户修正 LLM 响应后 `--resume`。

### 通用流程(伪代码,不绑业务)

```
LLM-N 响应提交
  ↓
[校验脚本 N1]
  ├─ PASS → continue
  └─ FAIL → state.checkpoint = "stepX_pending" + save_state + exit(1)
     ↓
CC 修改 LLM 响应文件
     ↓
--resume --llm-response <path>
     ↓
应用 LLM 响应 + 重新校验
```

### 关键约束

- ✅ 每次状态变更必须 `_save_state()` 持久化
- ✅ 校验失败必须自动写**结构化错误报告**(JSON,含 hint 字段)
- ✅ `--resume` 必须支持任意 checkpoint 恢复
- ❌ 禁止"静默重试"(不暴露错误就重跑)

### Revision Loop 强制落地(治"规范有但 run.py 不实现"反模式)

> **根因**:`state_machine_norms.md` 早期版本只规定"应自动回退",但 `scripts/run.py` 由 scaffolder-agent 自由生成,**实际未调用回退逻辑**——本规范修订强制把回退代码从规范层下沉到骨架层,任何生成 `run.py` 的实现必须**直接 import** 骨架函数。

**强制要求**:
- `scripts/run.py` **必须**从 `framework_configs/knowledge/skeletons/flow_design/state_machine.template.py` 复制 `validate_or_revert()` 函数并改名为本地实现(或 `from state_machine_helpers import validate_or_revert`)
- 任何 `validate_*.py` 调用点必须用 `validate_or_revert(..., revert_checkpoint=<pending_checkpoint>)` 包裹
- 禁用 `subprocess.run(...) + sys.exit(1)` 直接报错(等于"不回退")
- 禁用 `validate_*.py` 内部 `sys.exit(2)`(校验脚本应只返回退出码,回退决策由 run.py 决定)

**反例(禁止,通用)**:
```python
# ❌ run.py 内直接调 validate_*,失败只 exit(1)
result = subprocess.run(["python3", "validate_topology.py", "--input", v3])
if result.returncode != 0:
    print("校验失败")
    sys.exit(1)
```

**正例(强制,通用)**:
```python
# ✅ run.py 调 validate_or_revert,失败自动写错误报告 + 回退
from state_machine_helpers import validate_or_revert  # 或本地实现

ok = validate_or_revert(
    middle_dir=middle,
    validator_script=Path("scripts/validate_topology.py"),
    validate_args=["--input", str(v3_path), "--v2", str(v2_path), "--subsystem", subsys],
    state=state,
    revert_checkpoint="step7_pending",  # 回退目标
)
if not ok:
    sys.exit(1)  # validate_or_revert 内部已写错误报告 + 回退
```

**框架自检**:`scripts/commands/skill_create.py check-completeness` 强制:
- `grep -E "validate_or_revert" scripts/run.py` 必须 ≥ 1 命中
- `grep -E "subprocess.*validate_.*\\.py" scripts/run.py` 不应有裸调用(必须包裹 validate_or_revert)
- 0 命中裸调 → 触发 FAIL + 提示"必须用 validate_or_revert 包裹"

## LLM 断点通用契约

### 任务文件格式(写入 → 退出 → 等 CC 推理 → 读响应)

```json
{
  "task_id": "<字母或 step 名>",
  "task_type": "<推理任务类型,自由字符串>",
  "prompt_template": "references/step{N}-rules.md",
  "response_expected": "<响应文件路径>",
  "context": { /* 任意上下文数据 */ }
}
```

### 响应文件格式

由 `references/step{N}-rules.md` 顶部的 JSON Schema 约束(每个 Skill 自己的 Schema)。

### `--resume` 协议

```bash
python3 ${SKILL_DIR}/scripts/run.py \
  --resume \
  --llm-response <响应文件路径> \
  <其他原始参数>
```

run.py 必须:
1. 从 `run_state.json` 读 checkpoint
2. 根据 checkpoint 决定从哪个步骤恢复
3. 加载 `--llm-response` 文件,按 checkpoint 对应的 `_handle_llm_X_resume()` 处理
4. 推进 checkpoint 到下一状态

## 反模式(禁止)

- ❌ 状态字段名用业务特定命名(如 `flow_type_new_count` 而非通用 `checkpoint`)
- ❌ 状态文件路径硬编码绝对路径
- ❌ 校验失败直接 `sys.exit(1)` 不回退
- ❌ `--resume` 不支持任意 checkpoint
- ❌ LLM 响应校验失败不写错误报告

## 检查清单

- [ ] run.py 支持 `--resume` + `--llm-response` 参数
- [ ] 含 `run_state.json` 持久化文件
- [ ] 至少 3 个 checkpoint 状态(init + N×done + pending)
- [ ] 任意 validate_*.py 失败可回退到对应 pending
- [ ] 校验失败时写结构化错误报告(含 hint)