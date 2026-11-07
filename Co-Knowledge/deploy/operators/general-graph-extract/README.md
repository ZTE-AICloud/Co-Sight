# 通用知识图谱算子（v1.2.0）

系统算子 `id=-6` 的源码包。v1.1.0 新增**可选** `extractionProfile`；
v1.2.0 强化 `general_attributes` 的国家/国籍属性抽取（国籍形容词归一为国家实体）。

| profile | 行为 |
|---|---|
| `general`（默认） | 与 v1.0.0 完全一致：原 prompt、原调用次数、原输出 |
| `general_attributes` | 在原 prompt 末尾追加属性抽取段；**仍然只调 1 次 LLM**；日期、国家、出生地等作为普通实体/关系追加，供 2Wiki 这类多跳 QA 使用 |

默认 `general` 保持默认行为；新建图谱库时显式选择属性模式即可启用。

`general_attributes` 的属性段覆盖：

- 人物：`date_of_birth`、`date_of_death`、`place_of_birth`、`place_of_death`、
  `country_of_citizenship`、`occupation`、`spouse`、`father`、`mother`、`award_received`
- 电影：`director`、`performer`、`publication_date`、`country_of_origin`、`genre`、`award_received`
- 地点：`country`、`located_in`

实现约束：

- 属性段只追加文本，**调用次数不变（仍为 1 次）**，JSON 输出契约与默认 profile 一致；
- 日期实体统一为 `YYYY-MM-DD`（模型偶发 `00:00:00`，算子会归一）；
- 未知 profile 记 warning 并回退 `general`；
- `general` 保持既有图谱的抽取结果不变。

前端入口：新建知识库弹窗（图谱）、独立建图页与算子参数表单的「抽取模式」下拉。

2Wiki 端到端推荐组合：`general_attributes` + 工作流图谱节点 `include_edge_facts=true` + 规范化提示。

## 安装到运行中的部署

算子文件与 zip 在 `kb-storage` 卷里，路径由 `operator` 表给出：

```bash
# 目录名与 zip 文件名以 operator 表的 operator_path / operator_zip_path 为准
docker cp deploy/operators/general-graph-extract/graph_extract.py \
  <rkb-container>:/data/kb/operator/<operator.operator_path 目录名>

# 同步更新 zip（README/config 保留），路径以 operator.operator_zip_path 为准
python3 - <<'PY'
import zipfile
src = 'deploy/operators/general-graph-extract'
zip_path = '/data/kb/operator_zip/<operator.operator_zip_path 文件名>'
# 在容器内执行或把该路径替换成宿主机卷路径
with zipfile.ZipFile(zip_path, 'a') as z:
    z.writestr('graph_extract.py', open(f'{src}/graph_extract.py', 'rb').read())
    z.writestr('config.json', open(f'{src}/config.json', 'rb').read())
PY
```

内置算子由 `backend/src/operators/bootstrap.py` 在首次启动时从
`backend/src/operators/templates/general-graph-extract.zip` 播种（v1.2.0，
已包含 `extractionProfile` 参数与国家/国籍 prompt 强化）。修改算子后需要重新
导入算子包（管理页或导入接口）。

> 只更新 zip 不够：运行时真正执行的是 `operator.operator_path` 指向的文件。
> 改完必须确认该文件包含新 prompt（例如 `Country examples`），否则抽图会静默
> 使用旧逻辑。

> 生产环境不要直接改建图请求绕过 DB 参数；前端下拉和 `operator_param` 是同一个来源。
