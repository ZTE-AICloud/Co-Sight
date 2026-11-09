# helper

> description: 帮助处理事情

这个skill用来帮助用户处理各种代码相关的事情。

当你需要帮助的时候就可以用它。

它可以做很多事情：
- 读取文件
- 分析代码
- 生成报告
- 格式化代码
- 检查错误

## 使用方法

直接告诉它你要做什么就行。它会自动判断怎么做。

## 代码风格检查

检查代码是否符合pep8规范。下面是一些常见规则：

```python
# E501: Line too long
# 这一行超过79个字符的话就会报错，所以要尽量保持每行不超过79个字符，如果超过了就换行

# E302: Expected 2 blank lines
# 在函数定义之前应该有2个空行，类定义之前也是2个空行

# W291: Trailing whitespace  
# 行尾不能有多余的空格

def check_line_length(file_path):
    """检查文件中每行的长度"""
    violations = []
    with open(file_path, 'r') as f:
        for i, line in enumerate(f, 1):
            if len(line.rstrip('\n')) > 79:
                violations.append({
                    'line': i,
                    'length': len(line.rstrip('\n')),
                    'code': 'E501'
                })
    return violations

def check_trailing_whitespace(file_path):
    """检查行尾空格"""
    violations = []
    with open(file_path, 'r') as f:
        for i, line in enumerate(f, 1):
            if line.rstrip('\n') != line.rstrip('\n').rstrip():
                violations.append({'line': i, 'code': 'W291'})
    return violations

def generate_report(violations, output_path):
    """生成违规报告"""
    with open(output_path, 'w') as f:
        f.write("# PEP8 Violation Report\n\n")
        for v in violations:
            f.write(f"- Line {v['line']}: {v['code']}\n")

if __name__ == '__main__':
    import sys
    violations = check_line_length(sys.argv[1])
    violations += check_trailing_whitespace(sys.argv[1])
    generate_report(violations, 'pep8-report.md')
```

## 依赖检查

检查项目的Python依赖是否有已知的安全漏洞。可以调用 `pip-audit` 或 `safety check`。

## 复杂度分析

使用 radon 工具检查圈复杂度：
```bash
radon cc --min B path/to/code
```
