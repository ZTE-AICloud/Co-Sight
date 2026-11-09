#!/usr/bin/env bash
# G021: 验证 output/agents/{name}/v1/ 运行时主交付 CLAUDE.md 存在且非空壳
# (交付目录只含运行时面: CLAUDE.md + .claude/ + phase/ + evaluation/ + scripts/;
#  需求契约在 work/clarified-agent-requirements.yaml, 构建计划在 work/build-plan.md)
# 协议: --target <dir> 为 canonical；stdin JSON {"output_dir": ...} 为 fallback
# stdout JSON → exit 0(PASS)/2(FAIL)
set -euo pipefail

OUTPUT_DIR=""
if [[ "${1:-}" == "--target" && -n "${2:-}" ]]; then
  OUTPUT_DIR="$2"
else
  INPUT=$(cat)
  OUTPUT_DIR=$(echo "$INPUT" | jq -r '.output_dir // ""' 2>/dev/null || echo "")
fi

if [[ -z "$OUTPUT_DIR" ]] || [[ "$OUTPUT_DIR" == "null" ]] || [[ ! -d "$OUTPUT_DIR" ]]; then
  echo "{\"gate_id\":\"G021\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"input_error\",\"detail\":\"output_dir 缺失或不是目录: ${OUTPUT_DIR:-<empty>}\"}]}"
  exit 2
fi

FAILURES=()

path="$OUTPUT_DIR/CLAUDE.md"
if [[ ! -f "$path" ]]; then
  FAILURES+=("{\"type\":\"missing_file\",\"path\":\"$path\"}")
else
  size=$(stat -c%s "$path" 2>/dev/null || stat -f%z "$path" 2>/dev/null || echo 0)
  if [[ $size -lt 100 ]]; then
    FAILURES+=("{\"type\":\"file_too_small\",\"path\":\"$path\",\"size\":$size}")
  fi
fi

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  FJSON=$(printf '%s\n' "${FAILURES[@]}" | jq -s .)
  echo "{\"gate_id\":\"G021\",\"verdict\":\"FAIL\",\"failures\":$FJSON}"
  exit 2
fi

echo '{"gate_id":"gate.deliver.completeness","verdict":"PASS","summary":"runtime deliverable CLAUDE.md ready"}'
exit 0
