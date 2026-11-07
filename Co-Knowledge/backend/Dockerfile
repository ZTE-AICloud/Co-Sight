# ============================================================================
# rag-knowledge-base · 默认部署镜像
#
#   - 基础镜像 python:3.11.18-slim（**钉死 patch 版本**；升级 = 显式改这行 + 重跑全量回归）
#   - 依赖走 requirements.lock（全量 pin，全部来自公开 PyPI）
#   - 监听 8091（KNOWLEDGE_BASE_PORT 可覆盖），路由前缀 /api/co-knowledge/v1
#   - 配置全部经环境变量注入（见 deploy/docker-compose.yml 与 deploy/.env.example）
# ============================================================================

FROM python:3.11.18-slim

WORKDIR /app

# 所有 Python 包与入口（main.py / app.py / startup.py 与各领域包）都在 /app/src 下，
# 因此**只有一个 import 根**。
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    DEV_MODE=false

COPY requirements.lock ./
# pip 源经 build ARG 注入，**默认留空**（使用官方 PyPI）。
# 离线或使用镜像源时：
#     docker build --build-arg PIP_INDEX_URL=... --build-arg PIP_TRUSTED_HOST=...
# 不要在这里写死任何私有源地址。
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
# 受限容器里 pip 的 rich 进度条会额外起线程，线程配额不足时报
# "RuntimeError: can't start new thread"（E2E 栈重建实测）。关掉进度条与版本检查。
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_PROGRESS_BAR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

# 数据目录（运行时可被 STORAGE_MAIN_PATH / PLUGIN_PVC_PATH / ZEDX_PVC_PATH 覆盖）
# /data/rkb/tmp 是 MinIO 模式下的本地 scratch（对象物化、清洗中间件）
RUN mkdir -p /data/rkb/plugins/sourcefile /data/rkb/plugins/zedx /data/rkb/logs /data/rkb/tmp

EXPOSE 8091

CMD ["python3", "src/main.py"]
