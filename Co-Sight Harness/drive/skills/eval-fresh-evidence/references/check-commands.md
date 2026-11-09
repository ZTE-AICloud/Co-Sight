# Check Commands (L0 + L1)

L0/L1 是确定性 shell 检查。每次执行必须 fresh 跑命令并 capture 输出。

## L0 规则检查

```bash
# 1. 文件存在
ls -d .drive/<plan_dir>/artifacts/plan-001-T*/ 2>/dev/null | wc -l

# 2. YAML 格式 valid
for f in $(find .drive/<plan_dir> -name "*.yaml"); do
    python3 -c "import yaml; yaml.safe_load(open('$f'))" || echo "FAIL: $f"
done

# 3. JSON 格式 valid
for f in $(find .drive/<plan_dir> -name "*.json"); do
    python3 -c "import json; json.load(open('$f'))" || echo "FAIL: $f"
done

# 4. executeState.json frontmatter 完整
grep -E "^(workflow|mode|complexity|active_stage):" .drive/<plan_dir>/executeState.json
```

L0 结果：PASS（全过）/ FAIL（任一失败，附具体命令输出）

## L1 Lint/格式

按项目语言选工具：

```bash
# Markdown 格式
if command -v markdownlint >/dev/null; then
    markdownlint .drive/<plan_dir>/**/*.md 2>&1
fi

# Python 项目
if [[ -f pyproject.toml ]]; then
    ruff check . 2>&1
    mypy . 2>&1
fi

# TypeScript/JavaScript 项目
if [[ -f package.json ]]; then
    npx eslint . 2>&1
    npx tsc --noEmit 2>&1
fi

# Go
if [[ -f go.mod ]]; then
    go vet ./... 2>&1
fi
```

L1 结果：PASS / FAIL（附 fresh 输出）