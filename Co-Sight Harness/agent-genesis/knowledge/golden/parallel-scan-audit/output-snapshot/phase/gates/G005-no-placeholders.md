# G005 no-placeholders 门禁

## 元数据

```yaml
gate:
  id: G005
  type: condition_check
  condition: "placeholder_count == 0"
```

## 判定条件

全部产出中四类残留标记计数为零即通过（模板空变量 / 三字母待办缩写 / 两字母未决缩写 / 中文补写提示类），发现任一即阻断并回退。具体模式清单以插件侧门禁实现为准, 本文档只述语义不复制字面形态——避免门禁文档自含被检字样。
