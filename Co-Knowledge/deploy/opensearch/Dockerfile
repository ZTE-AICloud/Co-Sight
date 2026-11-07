# 官方 OpenSearch 2.x + analysis-ik（中文分词）。
#
# 为什么用 OpenSearch：Apache-2.0 许可，规避 Elasticsearch 8.x 的
# Elastic License 2.0 / SSPL 再分发限制（见 docs/opensearch.md）。
#
# 为什么需要自定义镜像：官方镜像不含 IK，standard 分词会把中文切成单字，
# 关键词路只能靠 ``minimum_should_match: 100%`` 兜底（见
# backend/src/retrieval/repository/es_store.py 的注释）。装上 IK 后，
# RKB 启动时探测到插件，新建索引会自动使用 ``ik_smart``。
#
# 构建期不联网：插件包由构建上下文提供（本目录下的 analysis-ik.zip，
# 随仓库分发；离线部署时把已下载的包放到这里即可），构建时校验 SHA-256
# 后离线安装。
ARG OPENSEARCH_VERSION=2.19.6
FROM opensearchproject/opensearch:${OPENSEARCH_VERSION}

# 镜像内保留第三方组件与许可声明（analysis-ik 插件包自身不带 LICENSE 文件）。
COPY THIRD-PARTY-NOTICES.md /usr/share/opensearch/THIRD-PARTY-NOTICES.md

# 固定插件包内容的 SHA-256（2026-10-30 对 2.19.6 实测）。包内容变化时构建会失败，
# 升级插件版本时同步更新此值。analysis-ik 上游为 Apache-2.0，见 THIRD-PARTY-NOTICES.md。
ARG OPENSEARCH_IK_SHA256=d1a4de7335c65d341839015701dd7f42a7ea50029c3b6abaef6a599f6471fff3

# 基础镜像以 opensearch 用户运行，COPY 需同步改属主，否则安装完无法清理临时文件。
COPY --chown=opensearch:opensearch analysis-ik.zip /tmp/opensearch-analysis-ik.zip
RUN echo "${OPENSEARCH_IK_SHA256}  /tmp/opensearch-analysis-ik.zip" | sha256sum -c - \
    && /usr/share/opensearch/bin/opensearch-plugin install --batch file:///tmp/opensearch-analysis-ik.zip \
    && rm -f /tmp/opensearch-analysis-ik.zip
