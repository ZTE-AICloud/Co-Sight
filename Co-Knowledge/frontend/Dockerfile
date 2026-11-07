# ============================================================================
# web · 默认部署镜像
#   - 多阶段：node:22.23.3-alpine 构建 Vue 产物 → nginx:1.27.5-alpine 静态 + 反代
#   - 两个基础镜像都**钉死 patch 版本**；升级 = 显式改这两行 + 重跑全量回归
#   - 同域反代 /api/co-knowledge/v1 → rag-knowledge-base
#   - 支持子路径部署（BASE_URL=/co-knowledge/），默认根路径
# ============================================================================

FROM node:22.23.3-alpine AS build
WORKDIR /app
COPY . .
# npm 源经 build ARG 注入，**默认留空**（使用 .npmrc 里的官方 registry）。
# 内网或使用镜像源时：
#     docker build --build-arg NPM_REGISTRY=https://...
# 不要在这里写死任何私有源地址。
ARG NPM_REGISTRY=
RUN npm ci ${NPM_REGISTRY:+--registry=$NPM_REGISTRY}
# 部署路径：同时决定 publicPath（vue.config.js）与路由 history base（main.js）。
# 默认根路径；子路径部署传 --build-arg BASE_URL=/co-knowledge/（末尾斜杠必填）。
# 不在这里写死具体前缀。
ARG BASE_URL=/
ENV BASE_URL=${BASE_URL}
RUN npm run build

FROM nginx:1.27.5-alpine
RUN mkdir -p /etc/nginx/snippets
ARG BASE_URL=/
COPY nginx.conf /etc/nginx/conf.d/default.conf.template
COPY nginx-sse-proxy.conf /etc/nginx/snippets/rkb-sse-proxy.conf
COPY --from=build /app/dist /tmp/dist
# 分发许可与第三方声明（显式复制，不依赖 dist 构建产物）。
COPY LICENSE /usr/share/nginx/html/LICENSE
COPY THIRD-PARTY-NOTICES.md /usr/share/nginx/html/THIRD-PARTY-NOTICES.md
# 规范化 base（补首尾斜杠）→ 渲染 nginx 的 SPA location → 按路径放置静态文件。
# 根路径：文件放 /usr/share/nginx/html/；子路径：放 /usr/share/nginx/html/<base>/，
# 这样 nginx 的 root + try_files 不用 alias 也能命中。
RUN set -eu; \
    base="${BASE_URL}"; \
    case "$base" in /*) ;; *) base="/${base}" ;; esac; \
    case "$base" in */) ;; *) base="${base}/" ;; esac; \
    sed "s|__WEB_BASE__|${base}|g" /etc/nginx/conf.d/default.conf.template \
        > /etc/nginx/conf.d/default.conf; \
    rm -f /etc/nginx/conf.d/default.conf.template; \
    if [ "$base" = "/" ]; then \
        : > /etc/nginx/snippets/web-base-redirect.conf; \
        cp -a /tmp/dist/. /usr/share/nginx/html/; \
    else \
        mkdir -p "/usr/share/nginx/html${base}"; \
        cp -a /tmp/dist/. "/usr/share/nginx/html${base}"; \
        printf 'location = / { return 302 %s; }\nlocation = %s { return 301 %s; }\n' \
            "$base" "${base%/}" "$base" > /etc/nginx/snippets/web-base-redirect.conf; \
    fi; \
    rm -rf /tmp/dist
EXPOSE 80
