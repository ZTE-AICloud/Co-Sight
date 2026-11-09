# SOC 标书知识库源目录格式约定

> 本文是 `cosightbot-soc-kb-build` 的源目录（source dir）权威格式约定。构建链按本约定**零兜底**解析：布局或列约定不符即报错，不做猜测式降级。

## 1. 源目录布局

一个知识库 = 一个本地目录，包含两个约定子目录（至少存在一个）：

```
my-kb/
├── 01_Specs_PD/             # 产品规格 / 产品文档（可选）
│   ├── 路由器产品规格.pdf
│   └── 交换机白皮书.docx
└── 02_Historical_Responses/ # 历史应答（可选）
    ├── 某项目标书应答.xlsx
    └── 另一项目应答.csv
```

- `01_Specs_PD/`：产品规格、白皮书、彩页等原始文档。支持 pdf / docx / pptx / xlsx /md / txt / html 及常见图片、压缩包格式（见 `runtime/common/document_types.py` 的`SUPPORTED_SOURCE_EXTS`）。
- `02_Historical_Responses/`：历史项目的标书应答表，xlsx / xlsm / xls / csv，列约定见第 2 节。
- 两个子目录至少存在一个，否则 `add-builtin` 拒绝注册。
- 源目录在构建时是**只读消费**：构建链不会修改、移动或删除源目录中的任何文件。

## 2. 历史应答列约定（02_Historical_Responses）

每个应答文件可以含多个 sheet，解析器会在**前 10 行**内自动定位表头行（命中「需求」别名的行），之后逐行读取应答条目。

| 字段 | 必需 | 列名别名（大小写不敏感） |
|------|:----:|--------------------------|
| 需求（requirement） | ✅ 必需 | 需求 / 需求描述 / 要求 / 需求/要求 / requirement / requirements / demand / requirement description / description |
| 编号（no） | 可选 | 编号 / 序号 / no / no. / number / item / item no / id |
| 合规（compliance） | 可选 | 合规 / 合规性 / 应答 / 应答情况 / compliance / comply |
| 备注（remarks） | 可选 | 备注 / 说明 / 备注/说明 / remarks / remark / note / notes / comment |
| 参考文档（reference_document） | 可选 | 参考文档 / 参考文件 / 参考资料 / reference / reference document / reference doc / ref |

**合规值归一**：构建时归一到 `FC` / `PC` / `NC` / 空——

- `FC`（完全满足）：FC / Complied / Y / Yes / Fully Compliant / 满足 / 完全满足
- `PC`（部分满足）：PC / Partial Complied / Partial / Partially Complied / P / 部分满足
- `NC`（不满足）：NC / Not Complied / N / No / Non-Compliant / 不满足
- 空值或无法识别的值 → 空（不报错）

**零兜底行为**（都是硬错误，构建直接失败）：

- 所有 sheet 的前 10 行都找不到「需求」列 → `ValueError: 未在 X 的任何 sheet 中找到应答表头`
- 表头存在但没有任何有效应答条目（需求列全空）→ 同样报错

**编码**：csv 按 utf-8-sig → gbk → latin-1 顺序尝试；xlsx 系走 pandas/openpyxl。

## 3. 构建产物结构

`cosightbot-soc-kb-build build <kb_id>` 成功后：

```
data/workspace-soc/
├── builder/
│   ├── configs/<kb_id>.json          # 注册配置（add-builtin 写入）
│   └── builds/<kb_id>/               # 构建工作区（lancedb 原始产物）
│       └── lancedb/{pd_spec_vector_library, historical_paradigms}/
├── kbs/<kb_id>/                      # 检索侧服务目录（build 后从 builds 镜像，整体替换）
│   ├── pd_spec_vector_library/       # 产品文档向量库（LlamaIndex/lancedb）
│   └── historical_paradigms/         # 历史应答范式向量库
└── soc_kb_registry.json              # 知识库注册表（build 成功自动写入/更新）
```

- **产物直通**：无任何上传/下载步骤，`kbs/<kb_id>/` 即检索运行时直接读取的目录。
- 重复 `build` 是增量式的（文件指纹命中则跳过）；`--force` 全量重建。
- `remove <kb_id> --confirm` 会清理 config + builds + kbs + 注册表条目，**不触碰源目录**。

## 4. 分享与导入

知识库的**源目录**就是分享单元：把整个 `my-kb/` 目录拷贝给同事（或归档为压缩包），对方解压后执行：

```bash
python .claude/skills/cosightbot-soc-kb-build/scripts/kb_cli.py add-builtin \
  --kb-id my-kb --source-dir /path/to/my-kb
python .claude/skills/cosightbot-soc-kb-build/scripts/kb_cli.py build my-kb
```

即可在本地重建出等价的向量库。构建产物（`data/workspace-soc/`）是机器本地缓存，**不建议**直接拷贝分发——embedding 模型/版本不一致时直接复用产物会得到错误的检索结果。
