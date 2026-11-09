# 输出模板

## 成功时输出

```
✅ workflow.yaml 已生成（写入 {file_path}）

📋 摘要：
- {N} 个阶段：{stages 列表}
- 回跳规则：{回跳点} → {回跳目标}（最多 {N} 次）
- complexity_rules：{支持的复杂度档位}

🔍 校验结果：ok

下一步：
- 运行 /drive "{intent}" 开始执行
- 或用 Read 工具查看生成的 workflow.yaml
```

## 失败时输出

```
❌ workflow.yaml 生成失败（未写入文件）

🔍 校验失败：
- 错误类型：{reason}
- 错误详情：{details.message}

可能的原因：
- {根据 reason 给出具体建议}

请调整后再次生成。
```

## 增量更新输出

```
✅ workflow.yaml 已更新（写入 {file_path}）

📝 变更：
- {修改前} → {修改后}
- 备份在：{bak_file}

🔍 校验结果：ok

下一步：...
```

## 用户取消时输出

```
❌ 用户取消，workflow.yaml 未写入。

备份（如果创建了）保留在：{bak_file}
```