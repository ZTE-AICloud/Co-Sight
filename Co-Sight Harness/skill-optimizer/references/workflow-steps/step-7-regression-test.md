# Step 7: Regression Test(回归测试)— self_check 5 项检查 + 落盘

> **对应 debug-pro Step 7**:写测试验证修复有效。
>
> **能力边界**:LLM 在 self_check 阶段也只能做**静态逻辑检查**,**不是真实运行**:
> - ✅ 可检查:`risk_evidence` 是否引用了 result_diff_report.md 的真实行号
> - ✅ 可检查:每条 mod 是否都有 `non_target_cases_risk` / `cost_benefit` 字段值
> - ❌ 不可验证:mod 应用后 case 真实分数是否提升(由下一轮 orchestrator 评测)

## 目标
落盘 optimization_summary.md 前,用 5 项静态检查验证 mod 的"形式合规性"。

## 必做动作(self_check 静态检查,落盘前必输出)

### 真实 self_check 结构(6 项 + 1 知识库记录)

```json
{
  "self_check": {
    "code_friendly": {
      "extract_to_script_count": N,
      "pass": true/false
    },
    "progressive_disclosure": {
      "has_common_md": bool,
      "common_md_chars": N,
      "pass": true/false
    },
    "token_reduction": {
      "total_after_chars": N,
      "orig_chars": N,
      "ratio": float,
      "pass": true/false
    },
    "files_outside_skill_md": {
      "scripts_count": N,
      "common_md_created": bool,
      "pass": true/false
    },
    "trade_off_check": {
      "all_mods_have_non_target_cases_risk": bool,
      "high_risk_mods_excluded": bool,
      "pass": true/false
    },
    "per_case_failure_diagnosis": {
      "all_unpass_cases_diagnosed": bool,
      "risk_evidence_includes_column": bool,
      "risk_evidence_cites_diff_report": bool,
      "no_freestyle_evaluations": bool,
      "pass": true/false
    },
    "knowledge_used": {
      "explored_paths": ["/path/to/consume_lib/..."],
      "insights": ["本轮方法论提炼 1", "..."]
    },
    "overall_pass": true/false
  }
}
```

### 6 项的 debug-pro 类比

| self_check 字段 | debug-pro 回归测试类比 | LLM 能力 |
|---|----|---|
| `code_friendly` | 单元测试:extract_to_script 抽取(可读、可回归) | ✅ 静态 |
| `progressive_disclosure` | 集成测试:common.md 拆分(避免膨胀) | ✅ 静态 |
| `token_reduction` | 性能测试:ratio ≤ 1.3 才 pass(框架计算,不凭印象) | ✅ 静态 |
| `files_outside_skill_md` | 集成测试:scripts/templates/references 改动量 | ✅ 静态 |
| `trade_off_check` | 单元测试:每条 mod 的 trade-off 字段完整性 | ✅ 静态 |
| `per_case_failure_diagnosis` | 单元测试:per-case 失分诊断 + result_diff_report.md 引用 | ✅ 静态 |
| `knowledge_used` | 集成测试:consume_lib 探查记录 + 提炼 | ✅ 静态 |

## 落盘位置

`{{ round_dir }}/candidate_{{ cand_id }}/optimization_summary.md`:

```markdown
# Round {{ round_num }} Candidate {{ cand_id }} 优化摘要

## 修改文件清单 / 覆盖 gaps / Token&时间预估 / net_impact 总和 / 多假设对比 / _read_audit 引用
## _provenance: single_pass_optimize LLM
## self_check (6 项 JSON + knowledge_used)
```

## 硬约束

- **`overall_pass: false` → 回到 Step 3 重写**(对应 debug-pro 假说错则回退)
- `token_reduction.pass` 必须由 `ratio ≤ 1.3` 计算得出,禁止凭印象写 true
- `overall_pass` 必须 6 项中所有 `pass` 全部为 true 才算 PASS
- 落盘后**真实运行验证**留给下一轮 orchestrator 跑评测,产物 → 下一轮 `result_diff_report.md` → 下一轮 Step 5 可回头看本轮 mod 是否生效(LLM 不需要自己读评测 raw 产物)

## 失败处理

`overall_pass = false` → 触发 REWORK(框架层追加 `attempt_block` 让 LLM 修正 + 重做 Step 3-7,最多 `max_attempts=2`)。