# LLM 断点哨兵协议 v1(2026-07-13 新增)

> **目的**:根治 Skill 脚本中 LLM 断点续跑协议失效(常见 bug:`if ! bash script; then rc=$?; if [[ rc -eq 0 ]]; then exit 0; fi` 是死代码,LLM 等待永远不触发)。
>
> **根因**:`! 0 = 1` 进入 if 分支,但 LLM 等待的 `exit 0` 在这种逻辑下**永远被错误识别**为"正常失败"或被忽略,主控继续跑后续步骤,LLM 响应数据被覆盖丢失。
>
> **本协议**:用专门的退出码 100 作为"LLM 等待"哨兵,主控 if-else 显式检测,绝不出错。

---

## 1. 退出码约定

| 退出码 | 含义 | 谁用 |
|--------|------|------|
| **0** | 正常完成,可继续下一阶段 | stepN_*.sh 正常分支 |
| **1-99** | 业务错误(具体码见各 Skill `references/output-schema.md`) | stepN_*.sh 异常分支 |
| **100** | **LLM 断点等待**(写完任务文件,等 CC 推理后回写响应,再 `--resume`) | stepN_*.sh LLM 等待分支 |
| 101-127 | **框架保留**(未来扩展,禁止业务使用) | — |
| 128+N | 进程被信号 N 终止(如 130=SIGINT) | 系统 |

**关键约束**:
- 步骤脚本 LLM 等待分支 **必须用 `exit 100`,禁止用 `exit 0`**
- 主控 run.sh **必须用 `if-else` 显式检测 `rc -eq 100`**

---

## 2. stepN_*.sh 模板

### 2.1 正常完成分支

```bash
#!/usr/bin/env bash
set -euo pipefail
# ... 实际工作 ...
echo "[stepN] 产出: ${OUT}"
exit 0
```

### 2.2 LLM 等待分支(关键)

```bash
#!/usr/bin/env bash
set -euo pipefail

# ... 步骤前置工作(读 IN, 校验, 准备 task) ...

# === LLM 断点哨兵:写任务文件 + exit 100 ===
jq -n '{...task payload...}' > "$TASK_FILE"
echo "[stepN] LLM 断点: 任务已写 $TASK_FILE"
echo "[stepN] 请 CC 读任务 → 推理 → 写 $RESP_FILE"
echo "[stepN] 然后调: bash scripts/run.sh --resume"
exit 100    # ← 关键!不是 exit 0
```

### 2.3 业务错误分支

```bash
#!/usr/bin/env bash
set -euo pipefail

# ... 校验失败 ...
if [[ "$missing_field" == "true" ]]; then
  echo "[ERROR 9] 字段缺失: $missing_field" >&2
  exit 9    # 业务错误码(见各 Skill output-schema.md)
fi
```

---

## 3. run.sh 主控模板(必读)

```bash
#!/usr/bin/env bash
# run.sh — Skill 主控(LLM 哨兵协议 v1)
set -euo pipefail

# === 必填参数校验 ===
: "${REQ_DIR:?...}"
: "${CASE_NAME:?...}"
# ...

WORK_DIR="${WORK_DIR:-${REQ_DIR}/.skillx_state}"
mkdir -p "$WORK_DIR"

# === 步骤列表 ===
STEP_SCRIPTS=(
  "step1_xxx.sh"
  "step2_xxx.sh"
  # ... 中间 stepN_*.sh ...
  "step12_xxx.sh"
)

# === 主循环(关键:显式 if-else + 100 检测) ===
for script in "${STEP_SCRIPTS[@]}"; do
  script_path="${SCRIPT_DIR}/${script}"
  [[ -x "$script_path" ]] || chmod +x "$script_path" 2>/dev/null || true

  echo "[$(date +%H:%M:%S)] 调用 ${script} ..."
  if bash "$script_path"; then
    # exit 0: 正常完成,继续
    :
  else
    rc=$?
    if [[ $rc -eq 100 ]]; then
      # LLM 断点: 等待响应(--resume 继续)
      echo "[$(date +%H:%M:%S)] ${script} LLM 断点,等待响应(--resume 继续)"
      exit 0
    else
      # 业务错误: 透传退出码
      echo "[$(date +%H:%M:%S)] ${script} 失败,退出码=$rc" >&2
      exit $rc
    fi
  fi
done

echo "[$(date +%H:%M:%S)] === 完成 ==="
```

### 3.1 禁用模式(死代码,会丢响应)

```bash
# ❌ 错误: ! 0 = 1 进入分支,但 LLM 等待 exit 0 永远走不到下面
for script in "${STEP_SCRIPTS[@]}"; do
  if ! bash "$script_path"; then
    rc=$?
    if [[ $rc -eq 0 ]]; then
      echo "等待 LLM..."
      exit 0
    else
      exit $rc
    fi
  fi
done
```

### 3.2 修正版(if-else + 100 检测)

见 §3 模板。**这是唯一正确写法**。

---

## 4. 集成位置

| 层级 | 文件 | 改动 |
|------|------|------|
| 规范 | `framework_configs/llm_checkpoint_sentinel_v1.md`(本文件) | 协议定义 |
| 反模式 | `framework_configs/anti_patterns/skill_anti_patterns.md` §反模式 8 | 记录"exit 0 当 LLM 断点"反模式 |
| 评估 | `framework_configs/static-eval-config.yaml` `dim13_llm_checkpoint_protocol` | 自动检测退出码协议合规 |
| 通用工具 | `scripts/common/llm_checkpoint.sh` | `llm_exit_checkpoint` helper,封装 exit 100 |
| Skill 模板 | `framework_configs/knowledge/skill-script-template.md`(若存在) | run.sh 模板用 if-else + 100 检测 |
| 流程 | `framework_configs/skill-create-guidelines.md` §7.6 | 强制 Step 7 后用 Explore agent 验证协议 |

---

## 5. 验证

每个 Skill 必须能用如下命令验证 LLM 断点协议合规:

```bash
# 1. 静态检查(grep 模式)
grep -rE "exit 0.*LLM|LLM.*exit 0" scripts/ && echo "❌ 有 LLM 断点用 exit 0" || echo "✓"
grep -rE "exit 100" scripts/ && echo "✓ 找到 LLM 哨兵"

# 2. 模拟运行(未设 LLM 响应时,应停等)
export REQ_DIR=/tmp/test CASE_NAME=test SUBSYS_NAME=SPA CONSUMER_LIB=/tmp/cl
bash scripts/run.sh
# 预期: 遇到 LLM 断点退出(run.sh 退 0,但 step 退 100)

# 3. 模拟响应后 --resume
echo '{"results": [...]}' > $REQ_DIR/.skillx_state/llm_response_4.json
bash scripts/run.sh --resume
# 预期: 跳过 LLM 断点(已检测到响应),继续后续
```

---

## 6. 历史与变更

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-07-13 | 初版,基于 04_skill_dir/组件间流程设计/ 的 11 个 bug 中"LLM 断点协议失效"反模式制定 |

**触发 bug 案例**:在 `/skill_create` 阶段 4 生成的 13 个 sh 脚本,`run.sh` 主循环用 `if ! bash; then rc=$?; if [[ rc -eq 0 ]]; then exit 0; fi`,导致 LLM 等待永远不触发,响应数据被覆盖。**本协议根治此类 bug**。
