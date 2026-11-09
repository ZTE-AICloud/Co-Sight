# Full CI/CD Pipeline Manager

> description: 管理 CI/CD 全流程

## Phase 1: 代码检查 (Lines 10-100)

### 1.1 Lint 检查
执行 ESLint、Pylint、RuboCop 等 Lint 工具，收集所有 Lint 报告。

### 1.2 类型检查
执行 TypeScript 类型检查、Python mypy 检查、Ruby Sorbet 检查。收集类型错误并按文件分组。

### 1.3 格式化检查
检查代码格式是否符合 Prettier/Black/RuboCop 规范。不合规文件列表输出到 lint-errors.txt。

### 1.4 安全检查
使用 Bandit、Brakeman、npm audit 扫描安全漏洞。严重级别 >= HIGH 的安全问题阻断 CI。

### 1.5 许可证检查
扫描依赖许可证，检测是否有 GPL 等传染性许可证的依赖。

### 1.6 代码复杂度检查
使用 radon/rails-best-practices 检查圈复杂度。超过 C 级的函数标记为需重构。

## Phase 2: 测试 (Lines 105-250)

### 2.1 单元测试
执行全量单元测试。收集覆盖率数据。

### 2.2 集成测试
启动 Docker Compose 环境，执行集成测试。

### 2.3 E2E 测试
使用 Playwright/Cypress 执行端到端测试。测试关键用户路径。

### 2.4 性能测试
使用 k6 执行负载测试。P95 延迟超过 500ms 标记为性能回归。

### 2.5 契约测试
执行 Pact 契约测试。验证 Producer 和 Consumer 之间的接口兼容性。

### 2.6 迁移测试
在 staging 数据库上执行迁移脚本。验证迁移可逆（up/down 均成功）。

## Phase 3: 构建 (Lines 255-350)

### 3.1 前端构建
执行 webpack/vite 生产构建。输出到 dist/ 目录。

### 3.2 后端构建
编译后端代码，打包依赖。生成可部署的 .jar/.whl/.gem 文件。

### 3.3 Docker 镜像构建
构建多阶段 Docker 镜像。标记版本号和 latest 标签。

### 3.4 静态资源上传
上传静态资源到 CDN。生成 manifest.json 记录资源版本映射。

### 3.5 文档构建
使用 Sphinx/JSDoc/YARD 生成 API 文档。部署到内部文档站点。

## Phase 4: 部署 (Lines 355-520)

### 4.1 Staging 部署
使用 Helm/Kustomize 部署到 Staging 集群。等待所有 Pod Ready。

### 4.2 Staging 冒烟测试
对 Staging 执行核心路径冒烟测试：登录、首页加载、核心 API 调用。

### 4.3 Canary 部署
在 Production 集群部署 Canary 实例（10% 流量）。监控错误率和延迟。

### 4.4 Canary 验证
对比 Canary 和 Stable 实例的指标。错误率增加 >5% 则自动回滚。

### 4.5 全量部署
Canary 验证通过后，滚动更新全量 Production。每批更新 25% 实例。

### 4.6 健康检查
部署完成后，对每个实例执行健康检查端点。连续 3 次失败则标记部署失败。

### 4.7 数据库迁移（仅当有变更时）
执行 `rails db:migrate` 或 Alembic 升级。先在 Staging DB 上预演。

### 4.8 缓存预热
部署后预热 Redis 缓存。预加载热门数据。

### 4.9 Feature Flag 更新
根据部署环境更新 Feature Flag 配置。关闭灰度功能的 Flag。

### 4.10 DNS/路由更新
更新负载均衡路由规则，下线旧版本实例。

## Phase 5: 监控与通知 (Lines 525-600)

### 5.1 部署监控
在 Datadog/Grafana 中标记部署事件。设置部署后 30 分钟告警窗口。

### 5.2 错误追踪
关联 Sentry/Rollbar 中的错误率变化。新错误类型立即通知。

### 5.3 通知
发送部署结果到 Slack #deployments 频道。包含版本号、变更 commit、部署耗时。

### 5.4 日志归档
将构建和部署日志上传到 S3 归档。保留 90 天。

### 5.5 回滚准备（如部署失败）
如健康检查或冒烟测试失败，执行以下步骤：
  - 触发 Helm rollback
  - 恢复 Feature Flag 原值
  - 通知 #incidents 频道
  - 创建 Postmortem 文档草稿

## Phase 6: 清理 (Lines 605-650)

### 6.1 清理临时文件
删除构建过程中产生的所有临时文件。

### 6.2 清理旧镜像
清理本地缓存的旧版本 Docker 镜像，释放磁盘空间。

### 6.3 清理 Staging
销毁 Staging 环境中本次部署创建的临时资源（测试数据库、临时 Bucket 等）。

### 6.4 更新部署日志
将本次部署的完整日志更新到内部 Wiki/Confluence。
