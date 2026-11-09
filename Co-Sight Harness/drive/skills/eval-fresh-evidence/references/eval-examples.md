# Evaluation Examples

> Reference: evidence 格式示例 + verdict 计算示例。
> 操作规则见 `skills/eval-fresh-evidence/SKILL.md`。

## AC Evidence 完整示例

```yaml
- ac_id: AC01
  description: "5G NR 协议解析器能解析 RRC Connection Request 消息"
  status: VERIFIED
  confidence: 0.92
  evidence:
    test_file: "tests/test_rrc_parser.py::test_parse_rrc_connection_request"
    test_output: |
      $ pytest tests/test_rrc_parser.py::test_parse_rrc_connection_request -v
      ============================= test session starts ==============================
      tests/test_rrc_parser.py::test_parse_rrc_connection_request PASSED     [100%]
      ============================== 1 passed in 0.12s ===============================
    artifact: ".drive/<plan_dir>/artifacts/plan-001-T002/output.json"
    artifact_quote: |
      {
        "message_type": "RRCConnectionRequest",
        "fields": {
          "ue-Identity": "0011223344556677",
          "establishmentCause": "mo-Signalling"
        },
        "parsed_at": "2026-06-18T14:35:22Z"
      }
  five_axis:
    accuracy: 5
    completeness: 4
    clarity: 5
    actionability: 5
    conciseness: 5
  notes: "Completeness 扣 1 分因为只测了 Request，没测 Reestablishment。"
```

## Verdict 示例

### PASS 情况

```yaml
verdict: PASS
l0_pass: true
l1_pass: true
l2_summary:
  verified: 5
  partial: 0
  missing: 0
  avg_confidence: 0.90
```

### INCOMPLETE 情况

```yaml
verdict: INCOMPLETE
l0_pass: true
l1_pass: true
l2_summary:
  verified: 3
  partial: 2
  missing: 0
  avg_confidence: 0.65
```
