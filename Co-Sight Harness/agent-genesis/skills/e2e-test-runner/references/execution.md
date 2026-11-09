# E2E-Test-Runner 执行契约

> L3 参考文档。SKILL.md 的 Mode A/B 入口只负责路由，本文件是 `scripts/run_e2e.py` 的完整执行细节。
> 阅读时机: 实现或修改 run_e2e.py、编写 Pipeline 侧的 suite.yaml、排查自检报告异常时。

## CLI 契约

```
python3 skills/e2e-test-runner/scripts/run_e2e.py \
    [--config <suite.yaml>]     # 默认 skills/e2e-test-runner/task/suite.yaml
    [--ids TC-X,TC-Y]           # 按用例 ID 过滤（原生支持，无需改写 suite）
    [--domain C]                # 按域过滤（A-K）
    [--keep-runs N]             # work/e2e-test-ci/ 下保留的 run-* 目录数（默认 5）
```

- `--task-file` 为隐藏兼容参数（映射到 `--config`），仅供旧 `run-e2e.sh` 使用。
- `AGENTGENESIS_TARGET=<dir>` 环境变量可覆盖 suite 内的 `target_path`（自检命令层用它把
  `target_path: "."` 锁定为执行命令时的 `$PWD`）。

## 路径解析

- `REPO_ROOT` = 引擎脚本上两级（`scripts/` → `e2e-test-runner/` → 仓库根），不依赖 cwd。
- suite 内 `target_path` / `sources` 的相对路径一律以 `REPO_ROOT` 为基准解析。
- spawn `claude -p` 的 cwd = 解析后的 target_path；自检时即 `$PWD`（V7 隔离约定）。

## Suite 加载与过滤

1. 读 suite.yaml → `sources`（相对 REPO_ROOT 的 golden-cases 路径列表）逐个加载并合并。
2. 合并后应用 `filter.ids` / `filter.domain` / `--ids` / `--domain`，命中为空则报错退出（exit 非 0）。
3. `target_path` 读出后仅作默认 spawn cwd；`AGENTGENESIS_TARGET` 优先。

## 单用例执行

对每个用例：写 prompt → `Popen(["claude","-p",...,"--output-format","json"], cwd=target_path)` →
增量读 stdout（超时仍能回收已写部分）→ 解析 JSON result → 判定。

### 阶段检测（三级）

| 级 | 信号 | 来源 |
|----|------|------|
| 1 | orchestrator-state.yaml（v0.17 状态机） | `.agent-genesis/work/{name}/orchestrator-state.yaml` 的 `current_step` → `_STEP_PHASE_MAP`（21 条 step→phase 映射）；`pipeline_status=DONE/COMPLETED` → DONE |
| 2 | progress-state.yaml（legacy） | 解析失败或缺失时回退，`current_state` + `phase_history` 长度 |
| 3 | 输出文本升级 | PLAN_MODE（审批话术）等关键词命中的级别高于状态文件读数时升级 |

### 行为评测

- `behavior-rules.yaml` 按 `case_id` 精确匹配规则（text_contains / text_regex /
  artifact_exists / phase_contains，pass_when any|all）。
- 无 case 专属规则 → 域级模板（`domain_assessment_templates`）→ 全局模板兜底。
- 引擎只产出阶段/证据 JSON；schema 形状的 `e2e-results/<case>/result.json` 由
  product-tester SubAgent 物化（两路分层，C4 由 e2e-results 结果文件形态契约承载）。

## 报告与清理治理

- 报告写 `work/e2e-test-ci/run-<ts>/` + `latest` 软链更新（C3 冻结路径，不可改）。
- **V6b 轮转**: 报告生成后，按目录名排序删超龄 `run-*`（`--keep-runs 0` = 全删）。
  只动自检报告目录，不碰 `e2e-results/` 结构与单 run 内部布局。
- **V6c 副作用清单**: 跑前对 `work/`、`.agent-genesis/work/`、`output/` 做快照，跑后 diff
  出"非报告新增"，写入 report.json `side_effects` + report.md 专段；报告目录自身被排除。
- **V6d 清理指引**: report.md 末尾与命令输出给出
  `git clean -nfd .agent-genesis output`（先 dry-run，用户手动执行）。被测会话副作用
  **永不自动删除**——可能是用户想保留的产物。
- **V7 可追溯**: report 头记录实际执行 cwd，副作用落点可回溯。
