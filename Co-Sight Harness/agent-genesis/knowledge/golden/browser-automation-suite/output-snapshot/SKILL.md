---
name: browser-automation-suite
description: |
  托管浏览器并行研究套件。对一批目标（公司/站点/线索）做扇出式深度研究：
  搜索发现 → 去重 → 每目标一个子代理并行研究（各自产出单文件）→ 汇聚脚本
  合并为打分报告 + 表格。支持深度档位（quick/deep/deeper）平衡规模与质量。
  需要用户自备托管浏览器服务 API key 与 CLI。
  Use when the user wants to: research a list of targets at scale, build a scored
  target list, run parallel web research with per-target evidence files.
license: MIT
version: "1.0.0"
compatibility: 需托管浏览器 CLI 与用户提供的 API key（环境变量注入）；子代理仅 Bash
---

# 托管浏览器并行研究套件

对目标清单做 **扇出研究 + 汇聚合并**：每个目标由独立子代理研究并产出单文件证据档，
最后由确定性脚本合并为打分总报告。全程证据锚定，禁无据推断。

## 凭据契约（用户提供， 外部集成位）

- 用户自备托管浏览器服务的 **API key**（环境变量注入， 如 `HOSTED_BROWSER_API_KEY`）
  与官方 CLI。skill 不内置任何凭据； 首次运行引导用户完成 CLI 权限批准。
- 定时/回调形态： 同一流水线可部署为服务端点（webhook 触发或定时触发）,
  凭据与执行环境由用户在部署侧提供。

## 流水线（5 步， 禁跳步禁换序）

1. **计划（Plan）**: 与用户确认研究维度与深度档位（quick/deep/deeper）。
2. **发现（Discover）**: 用搜索 API 拉候选清单 → 去重脚本产出最终目标清单。
3. **扇出（Fan-out）**: 每目标派一个子代理并行研究， 写 `{OUTPUT_DIR}/{target-slug}.md`
   （格式见 `references/research-file-format.md`）。子代理只用 Bash, 单调用批量 heredoc
   写文件以最小化权限打扰。
4. **合成（Synthesize）**: `node scripts/compile-report.mjs {OUTPUT_DIR}` 合并全部
   单目标文件 → 打分总表 + 逐目标详情 + CSV。
5. **交付**: 总报告 + CSV + 每目标证据文件一并交给用户。

## 反幻觉规则（主代理与子代理同受约束）

- 目标描述**必须**引用页面抽取输出中的具体字段（TITLE / META / HEADINGS / BODY 的
  原句或转述）; 抽取不到就写 `Unknown`, 禁从视觉风格臆断业务。
- 描述为 `Unknown` 的目标, 打分封顶并在理由里注明证据不足。
- 禁让用户侧画像污染目标描述（不知道就写 Unknown, 禁模式匹配脑补）。

## 工具约束

- 网页搜索一律走托管浏览器搜索命令; 页面抽取一律走抽取脚本, 禁手工拼管道
  （裸管道会丢 meta 字段且不解析 JSON 信封）。
- 子代理禁读发现阶段的原始批量 JSON——经去重脚本拿清单即可。
- 全部路径用字面绝对路径（禁 `~`/`$HOME`, 会触发 shell 展开批准）。

## 失败处理

- 单目标研究失败不阻塞整批： 该目标文件标注失败原因, 汇聚照常, 报告里如实列缺失。
- 抽取连续失败的源， 降档重试一次再标记 Unknown。
