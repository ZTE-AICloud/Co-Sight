---
gate_id: G014
gate_type: deterministic
name: "Skill/Rule Quality"
condition: "all_skills_have_name_and_description AND all_rules_have_extends_line"
blocking: true
retry_count: 1
scope: pipeline
---

## 检查项

接受 stdin JSON:
```json
{
  "skills_dir": "output/agents/{name}/v1/.claude/skills/",
  "rules_dir": "output/agents/{name}/v1/.claude/rules/"
}
```

判定标准:
- [ ] 每个 SKILL.md 的 YAML frontmatter 含 `name:` + `description:` 字段
- [ ] 每个 rule .md 文件含 `> This file extends` 引用行

## 失败行为

列出缺失 frontmatter 字段的 skill 文件名 + 缺失引用行的 rule 文件名。

## 对应缺陷

- RCA #9: rules 原样复制
- RCA #10: skills frontmatter 不一致
