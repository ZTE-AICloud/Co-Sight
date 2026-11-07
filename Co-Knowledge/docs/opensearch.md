# 为什么使用 OpenSearch

## 1. 选型

OpenSearch 是 Linux 基金会下的 **Apache-2.0** 项目，适合随本项目一起分发与自部署。
它提供与 Elasticsearch 7.10 对齐的 REST API，本项目的关键词检索只用到通用端点
（`_search` / `_bulk` / `_mapping` / `_cat` / `_reindex` / `_doc`），不依赖特定厂商的
Java / Python 客户端，接入与替换成本可控。

中文检索依赖 `analysis-ik` 分词插件，OpenSearch 生态有对应的 2.19.6 版本，
可以随镜像一起构建并固定校验。

## 2. 版本与组件

| 项 | 当前值 |
|---|---|
| 许可 | **Apache-2.0** |
| 基础镜像 | `opensearchproject/opensearch` |
| 自建镜像 tag | `ragstudio/opensearch:2.19.6-ik` |
| Dockerfile | `deploy/opensearch/Dockerfile` |
| compose 服务名 | `opensearch` |
| 数据卷 | `osdata` |

应用侧只读 `RKB_ES_*` 变量（变量名保持稳定），连接主机名默认 `opensearch`。

## 3. 中文分词

官方 OpenSearch 镜像不含 `analysis-ik`，`standard` 分词会把中文切成单字。
`deploy/opensearch/Dockerfile` 在官方镜像上安装 **analysis-ik 2.19.6**，并在构建时
校验插件包的 SHA-256；应用启动时通过 `_cat/plugins` 探测：

- 探测到 IK → 新索引的 `text` 字段使用 `ik_smart`；
- 探测不到 → 回落到 `minimum_should_match("100%")`（逐字全匹配）。

回退分支用于未安装 IK 的镜像；代价是长自然语言查询可能漏召回。

analysis-ik 上游为 Apache-2.0；插件包内随附的第三方 Java 依赖与许可声明见
[`THIRD-PARTY-NOTICES.md`](../THIRD-PARTY-NOTICES.md)。

## 4. 索引是派生数据

OpenSearch 里只有索引，**唯一事实源是 PostgreSQL**（切片正文在 chunk 表、向量在
向量表）。因此：

- 换搜索引擎、升级 mapping、重建 IK 索引，都从 PG 重建即可；
- 新建部署无需额外步骤：空库启动后导入文档时自动建索引；
- 已有部署重建索引用 `tools/rag-metrics/reindex_es.py --kb-id <kbId> --apply`。

索引结构（每个文档库一个 `doc_<kbId>`，扁平 7 字段，`_id = node_id`，
`dynamic: strict`）见 [`database-schema.md`](database-schema.md)。
