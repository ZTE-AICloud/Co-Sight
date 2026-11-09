---
name: gate-suite-report
description: >-
  一键执行 agent-genesis 仓库的五套件回归与双机检并产出结构化验证报告。
  当批次 commit 前需要验证门、或方案阶段收官需要"五套件 ALL PASS"证据，
  用户说"跑验证/五套件/收官检查"时触发。无需输入（仓库根自动定位
  tests/gates/ 套件与 scripts/ 机检）；输出 .agent-genesis/verify-report.md
  （总判定 ALL PASS/FAIL + 逐套件结果表 + 失败用例定位）及一行 stdout 总结论。
version: "1.0.0"
---

# gate-suite-report — 五套件回归与双机检报告

一键执行 agent-genesis 仓库的五套件回归测试与双机检脚本，收集每项 PASS/FAIL
状态与失败用例原文，产出固定三段结构的验证报告。本 skill 只负责**顺序执行、
确定性计数与状态汇报**，不重写任何测试逻辑，不对单项结果做主观判定——
PASS/FAIL 一律以脚本 exit code 为唯一依据。

## When to Use

- 批次 commit 前需要验证门（"五套件 ALL PASS"红线）时
- 方案阶段收官需要"五套件 ALL PASS"证据时
- 用户说"跑验证 / 五套件 / 收官检查"时

## 七项验证资产（固定清单与顺序，禁止增删或重排）

| # | 类型 | 路径（仓库根相对） | 角色 |
|---|------|--------------------|------|
| 1 | 套件 | `tests/gates/g028-static-verify.sh` | 阶段二静态验证门 |
| 2 | 套件 | `tests/gates/legacy-compat-verify.sh` | legacy 兼容验证门 |
| 3 | 套件 | `tests/gates/runner-assets-verify.sh` | runner.assets 验证门 |
| 4 | 套件 | `tests/gates/stage1-verify.sh` | 阶段一回归 |
| 5 | 套件 | `tests/gates/stage3-verify.sh` | 阶段三回归（含 2.2/2.3 断言） |
| 6 | 机检 | `scripts/check-gate-registry.sh` | 注册表↔实现↔调用点闭合 |
| 7 | 机检 | `scripts/check-legacy-names.sh` | gate 编号解析规则 |

执行顺序：套件 1→5，然后机检 6→7。

## Execution Steps

### Step 1 — 定位仓库根

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
```

以 `$REPO_ROOT` 拼出七项脚本的绝对路径。若 `git rev-parse` 失败（不在仓库内），
立即停止并向用户报告错误，不产出报告。

### Step 2 — 依序执行七项（不 fail-fast）

对七项逐一执行，**任一项失败或缺失都不中止，必须跑完全部七项**（用户已裁定
收集所有失败，禁止 fail-fast）。每项执行模式：

```bash
RUN_DIR=".agent-genesis/work/gate-suite-report/runs/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN_DIR"
bash "$REPO_ROOT/tests/gates/stage1-verify.sh" 2>&1 | tee "$RUN_DIR/stage1-verify.log"
echo "exit_code=${PIPESTATUS[0]}" >> "$RUN_DIR/stage1-verify.log"
```

- 原始输出（stdout+stderr 合流）tee 落盘到 `$RUN_DIR/<项名>.log`，供事后审查
- exit code 单独追加到日志末尾并记录在内存结果表中
- 七项全部执行完后进入解析阶段

### Step 3 — 确定性计数与失败提取（严禁 LLM 目测计数）

逐项从日志文件解析，**只能用 grep / wc / awk 等确定性文本工具**，严禁凭
肉眼阅读输出估计数量：

```bash
# 统计 ✓（通过）与 ✗（失败）行数
PASS_N=$(grep -c '✓' "$RUN_DIR/<项名>.log" || true)
FAIL_N=$(grep -c '✗' "$RUN_DIR/<项名>.log" || true)
# 提取 ✗ 行原文（失败用例定位素材）
grep '✗' "$RUN_DIR/<项名>.log"
```

机检项（6/7）额外提取 `BAN` / `FAIL` 字样行原文收录进报告。若某类标记行
计数为 0 且 exit code ≠ 0，把该日志尾部 20 行原文收录进失败明细，不省略。

### Step 4 — 缺失脚本 fail-closed

执行前检查脚本文件是否存在。任一脚本缺失：

- 该项 `status = ERROR`（原因注明"脚本缺失"），**不得静默跳过**
- 该项计为失败（fail-closed）：总判定必为 FAIL
- 继续执行其余项

### Step 5 — 聚合总判定

- 项状态判定：`exit code = 0` → PASS；`exit code ≠ 0` → FAIL；脚本缺失 → ERROR
- **总判定 = ALL PASS 当且仅当七项 exit code 全为 0 且无 ERROR**；否则 FAIL

### Step 6 — 产出报告

按 `templates/verify-report.md` 的三段结构组织内容（总判定 / 逐套件结果表 /
失败明细），写入固定路径 `.agent-genesis/verify-report.md`（仓库根相对）：

- 报告头部：ISO 8601 生成时间戳（`date -u +%Y-%m-%dT%H:%M:%SZ`）
- 数据来源段：七项脚本路径 + 各自 exit code + 原始日志落盘路径
- 失败明细：逐条列出 ✗ 行（或 BAN/FAIL 行）原文 + 所属套件，不转述、不概括

### Step 7 — stdout 一行总结论

报告落盘后向 stdout 输出一行总结论，格式：

```
gate-suite-report: ALL PASS (7/7)  或  gate-suite-report: FAIL (pass=5 fail=2 error=0)
```

同时告知报告路径。此为唯一的 stdout 摘要，不额外展开叙述。

## Checklist（完成前逐项核对）

- [ ] 七项全部执行（或标记 ERROR），无静默跳过、无 fail-fast
- [ ] 每项原始输出已 tee 到 `$RUN_DIR/<项名>.log`，exit code 已记录
- [ ] 计数（PASS_N / FAIL_N）全部来自 grep -c，无 LLM 目测计数
- [ ] 失败明细逐条含 ✗（或 BAN/FAIL）行原文与所属套件
- [ ] 报告头部含 ISO 8601 时间戳与数据来源（七项路径 + exit code）
- [ ] 报告已写入 `.agent-genesis/verify-report.md`，结构符合 templates/verify-report.md
- [ ] stdout 输出一行总结论（总判定 + 各状态项数）
- [ ] 总判定规则正确：全 0 且无 ERROR 才 ALL PASS
