# Co-Sight Code Wiki（开发者文档）

本 Wiki 面向需要二次开发、定位问题、扩展工具/模型能力的开发者，重点解释仓库结构、运行链路、关键对象与依赖关系。

## 快速导航

- [01-项目概览与目录结构](01-%E9%A1%B9%E7%9B%AE%E6%A6%82%E8%A7%88%E4%B8%8E%E7%9B%AE%E5%BD%95%E7%BB%93%E6%9E%84.md)
- [02-整体架构与核心流程](02-%E6%95%B4%E4%BD%93%E6%9E%B6%E6%9E%84%E4%B8%8E%E6%A0%B8%E5%BF%83%E6%B5%81%E7%A8%8B.md)
- [03-模块职责与依赖关系](03-%E6%A8%A1%E5%9D%97%E8%81%8C%E8%B4%A3%E4%B8%8E%E4%BE%9D%E8%B5%96%E5%85%B3%E7%B3%BB.md)
- [04-关键类与关键函数](04-%E5%85%B3%E9%94%AE%E7%B1%BB%E4%B8%8E%E5%85%B3%E9%94%AE%E5%87%BD%E6%95%B0.md)
- [05-Web%E6%9C%8D%E5%8A%A1%E4%B8%8EAPI](05-Web%E6%9C%8D%E5%8A%A1%E4%B8%8EAPI.md)
- [06-%E9%85%8D%E7%BD%AE%E4%B8%8E%E8%BF%90%E8%A1%8C%E6%96%B9%E5%BC%8F](06-%E9%85%8D%E7%BD%AE%E4%B8%8E%E8%BF%90%E8%A1%8C%E6%96%B9%E5%BC%8F.md)
- [07-MCP%E5%B7%A5%E5%85%B7%E6%89%A9%E5%B1%95](07-MCP%E5%B7%A5%E5%85%B7%E6%89%A9%E5%B1%95.md)
- [08-%E6%89%93%E5%8C%85%E4%B8%8E%E5%8F%91%E5%B8%83](08-%E6%89%93%E5%8C%85%E4%B8%8E%E5%8F%91%E5%B8%83.md)
- [09-%E6%9E%B6%E6%9E%84%E5%8F%AF%E8%A7%86%E5%8C%96](09-%E6%9E%B6%E6%9E%84%E5%8F%AF%E8%A7%86%E5%8C%96.md)
- [10-WebSocket%E9%80%9A%E8%AE%AF%E6%8E%A5%E5%8F%A3](10-WebSocket%E9%80%9A%E8%AE%AF%E6%8E%A5%E5%8F%A3.md)

## 入口文件索引

- Web 服务入口：[main.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py)
- 引擎入口（可直接跑示例任务）：[CoSight.py](file:///d:/lingdong/Co-Sight/CoSight.py)
- LLM 装配与分层配置：[llm.py](file:///d:/lingdong/Co-Sight/llm.py)，[config.py](file:///d:/lingdong/Co-Sight/config/config.py)

## 建议阅读顺序

1. [01-项目概览与目录结构](01-%E9%A1%B9%E7%9B%AE%E6%A6%82%E8%A7%88%E4%B8%8E%E7%9B%AE%E5%BD%95%E7%BB%93%E6%9E%84.md)
2. [02-整体架构与核心流程](02-%E6%95%B4%E4%BD%93%E6%9E%B6%E6%9E%84%E4%B8%8E%E6%A0%B8%E5%BF%83%E6%B5%81%E7%A8%8B.md)
3. [04-关键类与关键函数](04-%E5%85%B3%E9%94%AE%E7%B1%BB%E4%B8%8E%E5%85%B3%E9%94%AE%E5%87%BD%E6%95%B0.md)
4. [05-Web服务与API](05-Web%E6%9C%8D%E5%8A%A1%E4%B8%8EAPI.md)
5. [06-配置与运行方式](06-%E9%85%8D%E7%BD%AE%E4%B8%8E%E8%BF%90%E8%A1%8C%E6%96%B9%E5%BC%8F.md)
