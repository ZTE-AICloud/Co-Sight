# OpenSearch 镜像第三方组件声明

本镜像基于 `opensearchproject/opensearch:2.19.6`（Apache-2.0），并安装
`analysis-ik 2.19.6`（Apache-2.0，上游
https://github.com/medcl/elasticsearch-analysis-ik ）。插件包随构建上下文
分发（`analysis-ik.zip`），构建期不联网。

analysis-ik 插件包内随附以下第三方 Java 依赖：
`httpclient-4.5.13`、`httpcore-4.4.13`、`commons-logging-1.2`、`commons-codec-1.11`。
这些 jar 的许可以其包内声明为准。

OpenSearch 的 LICENSE/NOTICE 随基础镜像保留在 `/usr/share/opensearch/`。
仓库根目录的 `THIRD-PARTY-NOTICES.md` 汇总了本项目全部第三方声明。
