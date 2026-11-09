# Coding Style — AgentGenesis 编码规范

## Skill 目录结构（Anthropic 规范）
```
skills/{skill-name}/
├── SKILL.md              # Skill 定义入口（L2 加载）
├── references/           # 参考文档（L3 按需加载）
├── scripts/              # 可执行脚本（独立运行，不依赖 LLM 上下文）
└── templates/            # 输入/输出模板
```

## 渐进式加载
- L1: name + description（Agent 启动时加载）
- L2: SKILL.md body（匹配触发时加载）
- L3: references/ 下文件（SKILL.md 显式引用时才 Read）

## 描述公式（SF-6）
`「做什么」+「何时触发」+「接收什么输入」+「产出什么输出」`

## 文件组织
- 多个小文件 > 少量大文件
- 200-400 行典型，800 行上限
- 按功能/领域组织，非按类型
- SKILL.md ≤ 300 行

## 禁止
- 禁止 SKILL.md 内联 >100 行的参考文档或代码块
- 禁止全量重写——增量修改，范围 ≤ 2 个章节
- 禁止姐妹 Skill 结构对齐（Skill 是独立功能单元）
