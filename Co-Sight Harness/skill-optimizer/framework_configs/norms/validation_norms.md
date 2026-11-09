# 校验脚本规范

> 适用于所有 `/skill_create` 工作流生成的 `scripts/validate_*.py`。

## 流程类 Skill 必含 3 类校验脚本

| 校验类型 | 脚本名 | 检查项 | 触发时机 |
|---------|--------|--------|---------|
| 拓扑校验 | `validate_topology.py` | 变更组件完整性、anchor 范围、首末行流向、重复消息对、接口占位一致性 | LLM 推理完成后 |
| 内容校验 | `validate_table.py` | 无占位符("待补充"/"业务流待定")、字段完整、必填列非空、**三段式变更描述完整性(若 spec §1.3 产物含 change_desc 字段)** | 表格渲染后 |
| 产物校验 | `validate_output.py` | 文件存在、格式正确、跨文档一致性 | 写入完成后 |

## 反例(禁止)

- ❌ 流程类 Skill 无任何 `validate_*.py` 脚本
- ❌ 校验脚本只检查"文件存在",不检查内容
- ❌ 校验失败时不回退,而是直接报错退出
- ❌ 把所有校验逻辑塞进 `run.py` 主控(应独立)

## 校验失败处理(revision loop)

### 流程类 Skill

```
LLM-B 响应提交
  ↓
validate_topology
  ├─ PASS → continue
  └─ FAIL → 回退到 LLM-B 断点(允许修正后 --resume)
```

### 通用规则

- 校验失败时,**生成结构化错误报告**(JSON 格式,含错误位置)
- 报告写入 `${workspace}/middle_content/{skill_name}/validate_errors.json`
- 用户(或 LLM)根据报告修正后,重新 `--resume`

## CLI 接口规范

所有 `validate_*.py` 必须支持:

```bash
python3 scripts/validate_*.py \
  --input <JSON/MD 文件路径> \
  --output <错误报告输出路径> \
  [--subsystem NAME] \
  [--V2.json]    # 拓扑校验需要 V2 引用
```

退出码:
- `0` = 通过
- `1` = 校验失败(非错误,需修正)
- `2` = 文件不存在
- `3` = 解析失败

## 校验脚本函数粒度强制(治"校验函数堆 main()"反模式)

> **根因复盘**:当前 `/skill_create` 产出(如 `step14_validate_topology.py`)经常把 5 项 C1-C5 拓扑校验全部塞进 `main()` 内联(`# C1 变更组件完整性` ... `# C5` 都是 main 内的代码块),没有独立 `check_*` 函数封装。后果:(1) 单项校验无法独立调用;(2) 单元测试难写;(3) main() 单点堆积。

### 强制规则

每个 `validate_*.py` / 流程中的 `step*_validate*.py` **必须**满足:

| 规则 | 说明 |
|------|------|
| **1. 每个独立校验项抽为 `check_<item_name>()` 函数** | 函数签名:`check_<item>(输入数据) -> List[error_dict]`,返回错误列表(空列表=通过)|
| **2. `main()` 仅负责调度** | main() 只做 argparse → 读输入 → 遍历调用 check_* → 组装错误报告 → 写 `validate_errors.json` → 退出 |
| **3. 支持 `--check <item_name>` 单项验证 CLI** | 仅跑指定校验项,治"无法单点调试"反模式。例:`validate_topology.py --check C1` |
| **4. check_* 必须是纯函数** | 无 IO 副作用(可 mock 输入直接 assert 返回);无 print;无 sys.exit |
| **5. check_* 必须可单测** | `pytest scripts/validate_topology.py::check_change_components_present` 必须能直接跑 |

### 反例(禁止)

```python
# ❌ 把所有 C1-C5 写在 main() 内
def main():
    ...
    if missing_comps: failed.append({"id": "C1", ...})  # C1 内联
    if anchor_viol: failed.append({"id": "C2", ...})     # C2 内联
    # ... C3 C4 C5 都内联
```

### 正例(强制)

```python
# ✅ 每个 C 拆独立 check_* 函数(对标参考答案 V2 validate_topology.py)
def check_change_components_present(v3_rows, change_comps) -> List[str]:
    """C1 校验:所有变更组件必须出现在 V3 行中"""
    ...

def check_anchor_bounds(v3_rows, v2_row_count) -> List[str]:
    """C2 校验:insertions 的 anchor 必须在 [0, v2_row_count] 范围内"""
    ...

def check_first_last_rows(v3_rows, subsystem) -> List[str]:
    """C3 校验:首末行的源/目标不能都在当前子系内"""
    ...

def check_duplicate_pairs(v3_rows) -> List[str]:
    """C4 校验:(src,tgt) 对不能重复"""
    ...

def check_interface_placeholder_consistency(v3_rows) -> List[str]:
    """C5 校验:接口待定 + flow_type=修改 不能共存"""
    ...

CHECK_REGISTRY = {
    "C1": check_change_components_present,
    "C2": check_anchor_bounds,
    "C3": check_first_last_rows,
    "C4": check_duplicate_pairs,
    "C5": check_interface_placeholder_consistency,
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--check", choices=list(CHECK_REGISTRY.keys()),
                        help="仅跑指定校验项(可选,默认跑全部)")
    args = parser.parse_args()
    data = load(args.input)
    failed = []
    items = [args.check] if args.check else CHECK_REGISTRY.keys()
    for item_id in items:
        fn = CHECK_REGISTRY[item_id]
        errs = fn(data["rows"], **data.get("ctx", {}))
        failed.extend({"id": item_id, "errors": errs} for err in errs)
    Path(args.output).write_text(json.dumps({"failed": failed}, ensure_ascii=False, indent=2))
    sys.exit(EXIT_OK if not failed else EXIT_VALIDATION_FAIL)
```

### 校验脚本自检清单

`scripts/commands/skill_create.py check-completeness` 校验每个 `validate_*.py`:

- [ ] 文件内 `^def check_` 数量 ≥ 校验项数(topology 至少 5 个 check_* / table 至少 3 个)
- [ ] `main()` 函数体 ≤ 30 行(只调度,不长逻辑)
- [ ] argparse 含 `--check` 参数(支持单项验证)
- [ ] check_* 函数无 `print` / `sys.exit` 调用(纯函数判定)

## 三段式 change_desc 强校验(治"LLM 输出格式不规范"反模式)

> **根因**:部分业务模式(flow_design / 子系统流程设计 / 任何含"业务变更描述"的表格)的 LLM 输出字段 `change_desc` 应是三段式(源 + 目标 + 业务接口),但 LLM 经常遗漏某段或用其他格式。原 `validate_table.py` 只检查"无待补充",**未强制段数**。本节补强。

**强制规则**(通用,任何含 change_desc 字段的产物):

| 规则 | 说明 |
|------|------|
| **1. `check_tri_segment_desc` 必须存在** | 校验每行 `change_desc` 含 3 个段落标记:`【源...变更描述】：` + `【目标...变更描述】：` + `【业务接口（业务流）变更描述】：`(标记从 spec §1.3 / 附录 A 推断,允许业务变体但必须 3 段) |
| **2. 段标记允许业务变体** | 框架不绑死"源/目标/接口"具体文字,允许 `【源组件变更】` / `【Src】` 等业务命名;**但 spec 必须在附录 A 明示本 Skill 的 3 段标记前缀** |
| **3. 每段必须有非空内容** | 段标记后到下一段标记前必须有 ≥ 5 个非空字符(避免"【X】：无"/"【X】："空内容) |
| **4. 段标记必须用 `<br>` 或 `\n` 分隔** | 在 Markdown 表格单元格中渲染为换行;不强制换行符,但不允许三段粘连 |

**强制函数模板**(通用,任何 validate_*.py 复用):

```python
def check_tri_segment_desc(
    rows: list,
    seg_markers: list[str],  # 从 spec 附录 A 读取的 3 段标记列表
    sep_regex: str = r"<br>|\n",  # 段间分隔符
) -> List[str]:
    """强校验每行 change_desc 含 3 段(每段非空 + 段标记正确)。

    Args:
        rows: V3 表行列表,每行 dict 含 "变更描述" / "change_desc" 等字段
        seg_markers: 3 段标记列表,例 ["【源...变更描述】：", "【目标...变更描述】：", "【业务接口（业务流）变更描述】："]
        sep_regex: 段间分隔符(默认 <br> 或 \\n)

    Returns:
        错误列表(空列表=通过),每个错误 = "{row_index}: {reason}"
    """
    import re
    errors = []
    for i, row in enumerate(rows):
        desc = row.get("变更描述") or row.get("change_desc") or ""
        if not desc:
            errors.append(f"row {i}: change_desc 为空")
            continue
        # 检查 3 段标记全部出现(各 1 次)
        for marker in seg_markers:
            count = desc.count(marker)
            if count != 1:
                errors.append(f"row {i}: 段标记 {marker!r} 出现 {count} 次(期望 1 次)")
        # 检查每段非空
        parts = re.split(sep_regex, desc)
        for marker, part in zip(seg_markers, parts):
            content = part.replace(marker, "").strip()
            if len(content) < 5:
                errors.append(f"row {i}: 段 {marker!r} 内容过短({len(content)} 字符,期望 ≥ 5)")
    return errors
```

**反例(禁止,通用)**:
- ❌ 校验脚本只 `if "待补充" in desc: failed.append(...)`,不检查三段式 — 不通过
- ❌ 校验脚本硬编码 3 段标记为中文具体文字,不从 spec 附录 A 推断 — 不通过(耦合业务)
- ❌ 校验脚本允许段标记出现 0 次或多次 — 不通过

**正例(强制,通用)**:
- ✅ `seg_markers` 从 spec 附录 A 推断(允许业务变体)
- ✅ 校验报告含 row_index + 错误类型(便于 LLM 修正响应)
- ✅ 与 revision loop 集成(失败 → 回退到 LLM pending)

**框架自检**:`scripts/commands/skill_create.py check-completeness` 强制:
- 任何 `validate_*.py` 若 spec §1.3 产物含 `change_desc` / `变更描述` 字段 → 文件内必须含 `def check_tri_segment_desc`
- 该函数签名必须接收 `seg_markers: list[str]` 参数(不绑死具体文字)
- 0 命中 → FAIL + 提示"必须实现 check_tri_segment_desc"

## scripts 数估算公式(治"scripts 数超上限"反模式)

skill-create-guidelines.md §11 规定 `scripts 数 ≤ spec 步骤数 + 1`,但反 #2 又强制流程类 Skill 必含 3 类 validate 脚本,产生矛盾。本节给出**精确公式**:

```
scripts 数 = N_step + N_validate + N_helper + 1_run
其中:
  N_step    = spec §4 步骤数(impl 阶段 1:1 对应,**但有合并规则,见下**)
  N_validate = 3(流程类 Skill 必含 validate_topology / validate_table / validate_output)
  N_helper   = 0(严禁 _helper_* / lib_* / utils.*;工具函数就近内联到 run.py 或对应 step)
```

**约束**:
- N_step + N_validate + 1 ≤ 上限
- spec 步骤数 15 → scripts 上限 = 15 + 3 + 1 = 19
- spec 步骤数 11 → scripts 上限 = 11 + 3 + 1 = 15

> **判定**:若实际 scripts 数 > 上限,优先把简单 step(step 行数 < 50)内联到 run.py;否则触发"过度拆分"反模式。

### 渲染类 step 强制合并规则(治"step8_render_table + step9_render_diagram + step10_render_detail 拆为 3 个脚本"反模式)

> **根因**:spec 阶段常把"渲染"拆为多步(渲染表 / 渲染时序图 / 渲染详细变更),scaffolder 机械按 spec 1:1 拆出 3 个 step 脚本,每个都 < 100 行 + 单纯 IO + 共享同一输入数据,过度拆分。**渲染类 step 共享同一上游产物(最终表),无业务逻辑差异,应合并**。

**强制规则**(通用,任何"渲染"性质的 spec 步骤):

| 规则 | 说明 |
|------|------|
| **1. 渲染类 step 必须合并** | spec 步骤标题含"渲染"/"render"/"生成产物"且输入数据相同 + 共享同一上游产物的,必须合并为 1 个 `step{N}_render.py`(N 是合并后第一步的步骤号) |
| **2. 合并判定清单** | 满足下列**全部**条件 → 必须合并:(a) 步骤标题含"渲染"/"render"/"生成 X 产物";(b) 共享同一上游产物(如 V3_final.json);(c) 单步骤行数估 < 80 行;(d) 无独立 LLM 断点(都是纯 IO) |
| **3. 合并后函数拆分** | 1 个 step 脚本内可含 3 个 `render_<item>()` 函数(表格/时序图/详细描述),main() 顺序调用并写同一个产物文件;不强制 1 个函数,但禁止为每个 render_<item> 单独建脚本 |
| **4. 命名约定** | 合并后脚本名 = `step{N_first}_render.py`,函数名 = `render_table()` / `render_diagram()` / `render_detail()`;LLM 契约文件不受影响(本就 0 个断点) |

**反例(禁止,通用)**:
```text
❌ spec 步骤 8(渲染表)→ scripts/step8_render_table.py  (60 行,纯 IO)
❌ spec 步骤 9(渲染时序图)→ scripts/step9_render_diagram.py  (90 行,纯 IO,共享 step8 的 V3_final.json)
❌ spec 步骤 10(渲染详细描述)→ scripts/step10_render_detail.py  (100 行,纯 IO,共享 step8 的 V3_final.json)
→ 3 个脚本,250 行,共享同一上游
```

**正例(强制,通用)**:
```text
✅ spec 步骤 8+9+10 合并 → scripts/step8_render.py  (180 行,内含 render_table / render_diagram / render_detail 3 函数)
→ 1 个脚本,180 行,共享同一上游
```

**其他可合并场景**(通用,凡是"共享同一上游 + 无独立 LLM 断点 + 单步骤 < 80 行"的连续步骤):
- 步骤 12(写回原文档)+ 步骤 13(最终产物校验 + 打印)→ 合并为 `step12_finalize.py`(无 LLM + 共享 state)
- 步骤 N(校验)+ 步骤 N+1(校验)→ 合并为 1 个 `validate_*.py`(已规定)
- 步骤 X(读 A 文件)+ 步骤 X+1(读 B 文件,同一 A 类资源)→ 合并为 `stepX_read_inputs.py`

**框架自检**:`scripts/commands/skill_create.py check-completeness` 强制:
- 任何生成 `stepN_render_table.py` + `stepM_render_diagram.py` + `stepK_render_detail.py` (N/M/K 连续且 M=N+1, K=N+2) → 触发 REWORK + 提示"渲染类 step 必须合并为 step{N}_render.py"
- 0 命中反例 → PASS