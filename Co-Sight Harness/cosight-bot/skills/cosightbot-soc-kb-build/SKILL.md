---
name: cosightbot-soc-kb-build
description: >
  SOC 标书知识库构建：注册本地源目录（01_Specs_PD 产品文档 + 02_Historical_Responses
  历史应答）、构建向量库（产物直通本地 kbs/）、查看/删除知识库。
  在用户要求"构建标书知识库/注册知识库源目录/重建 SOC 知识库/删除标书知识库"时触发。
  输入为本地源目录路径，输出为构建结果 JSON；构建是分钟级长任务，一律后台执行。
---

# cosightbot-soc-kb-build —— SOC 知识库注册与构建

## When to Activate

- 用户说"构建标书知识库 / 注册知识库 / 把 xx 目录做成 SOC 知识库"
- 用户说"重建 / 更新标书知识库"
- 用户问"有哪些标书知识库 / 知识库状态"
- 用户说"删除标书知识库"

**Not for**：个人资料检索知识库（由本插件的个人知识管理智能体 pkm-expert / cosightbot-material / cosightbot-retrieve 承担）；应答流水线（→ cosightbot-soc-extract / soc-respond / soc-review / soc-fill）。

## 源目录约定（必须先满足）

```
my-kb/
├── 01_Specs_PD/             # 产品规格/文档（pdf/docx/pptx/xlsx/md/txt/html...）
└── 02_Historical_Responses/ # 历史应答（xlsx/csv，列约定见 docs/soc-kb-format.md）
```

至少存在一个子目录才可注册；完整约定见 `docs/soc-kb-format.md`。

## 执行入口

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-kb-build/scripts/kb_cli.py <子命令>
```

| 子命令 | 用法 | 说明 |
|---|---|---|
| `add-builtin` | `--kb-id X [--name N] --source-dir DIR` | 注册本地源目录（重复注册拒绝） |
| `build <kb_id>` | `[--force] [--skip-vision]` | 构建向量库：产物直落 `数据根/workspace-soc/kbs/<kb_id>/`，成功后自动写注册表；`--force` 全量重建；`--skip-vision` 跳过图片识别加速 |
| `list` | | 已注册 KB + 就绪状态 |
| `status <kb_id>` | | 构建/就绪详情 |
| `remove <kb_id> [--confirm]` | | 两阶段删除（不带 --confirm 先探测返回清理清单，用户确认后再带 --confirm 执行） |

## 环境自检（preflight）

脚本返回 **exit 3** + `{"hint": "please_run_install", ...}` 时：执行`python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`（幂等、非交互），装完按 `数据根目录下的 .env` 模板引导用户配置环境变量（embedding 必需；LLM 必需——构建链的图片识别/章节处理依赖）。**不得绕过**（S-05）。

## 构建的执行方式（重要）

- 构建是**分钟级长任务**（大目录首次构建可能数十分钟）：**一律后台执行**（Bash run_in_background），启动后立即告知用户「已开始构建知识库 <kb_id>，完成后我会汇报」。
- 构建子进程前台同步执行，进度行实时写入任务输出文件；用户中途问进度时读取输出文件尾部回答。
- 构建成功后产物**直通**：`kbs/<kb_id>/{pd_spec_vector_library, historical_paradigms}/` +注册表条目，无需任何上传/下载步骤。
- 构建失败（非零退出 / `ok:false`）：如实报告错误，不得声称成功（S-02/S-05）。

## LLM 与 embedding 依赖

- embedding 服务（`COSIGHTBOT_EMBEDDING_API_URL/KEY`）：**必需**，向量入库与检索都依赖。
- LLM（`OPENAI_*` 主配置，未配时回退会话继承的 `ANTHROPIC_*`）：构建链必需（图片多模态识别/章节处理）；缺失时 build 直接报错引导配置（不降级）。
- 历史应答 xlsx 解析是**确定性** pandas 解析（无 LLM 参与），列约定不符即报错（零兜底）。

## 进度汇报话术

1. 「已注册知识库源目录，开始构建（大目录可能需要几分钟）」
2. 「已开始构建知识库 <kb_id>，完成后我会汇报」（后台执行时）
3. 「知识库构建完成：<kb_id>，可以开始应答」

## 检查清单

- [ ] 源目录布局校验通过（01_Specs_PD/ 或 02_Historical_Responses/ 至少一个）
- [ ] 构建走了后台执行并告知用户
- [ ] 构建成功后确认 kbs/<kb_id>/ 产物与注册表条目（可用 list 验证）
- [ ] remove 走了两阶段（先探测、用户确认后 --confirm）
- [ ] preflight 失败时执行了 install.py 而非绕过
