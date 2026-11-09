# G005 no-placeholders 门禁

## 元数据

```yaml
gate:
  id: G005
  type: condition_check
  condition: "placeholder_count == 0"
  blocking: true
  retry_count: 3
```

## 判定条件

`placeholder_count == 0` —— 全部产出中四类残留标记计数为零即通过，发现任一即阻断并回退。

## 残留标记类别（语义描述）

| 类别 | 说明 |
|------|------|
| 待办类三字母缩写 | 以 T 起头的待办标记及其变体 |
| 未决类缩写 | 未决/待确认类英文缩写 |
| 空模板变量 | 双花括号包裹的未渲染变量形态 |
| 中文补写提示 | "待"字起头的补写占位用语 |

> 具体模式清单以插件侧门禁实现（`scripts/gates/g005-no-placeholders.sh`）为唯一权威。
> 本文档只述语义、不复制字面形态——门禁文档自含被检字样会被本门禁拦截（自指矛盾,
> 2026-10-15 修复: 模板物化产物曾因此必然 FAIL, 见 fast-lane-implementation FA 首战发现）。

## 扫描范围

全部产物文件（md/json），逐文件扫描上述四类；命中即计入 `placeholder_count`。
