### Co-Sight 重点技术说明

1.  **大型语言模型 (LLM) 的集成与应用:**
    *   **核心驱动力**: LLM 是 Co-Sight 进行自然语言理解、任务规划、工具选择、内容生成和总结的核心。
    *   **多 LLM 配置**: 系统设计上支持为不同阶段（规划 `llm_for_plan`、行动 `llm_for_act`、工具决策 `llm_for_tool`、视觉 `llm_for_vision`）配置不同的 LLM 实例，允许针对性优化。
    *   **Prompt Engineering**: 通过精心设计的系统提示和用户提示 (位于 `app/cosight/agent/.../prompt/` 目录) 来引导 LLM 的行为，确保其按预期执行任务和使用工具。
    *   **Function Calling / Tool Usage**: `BaseAgent` 中的 `create_with_tools` 方法利用了现代 LLM 的函数调用（或工具使用）能力。LLM 可以决定调用哪个预定义的工具，并提供参数，系统再执行相应的 Python 函数，并将结果返回给 LLM。这是实现自主性的关键。

2.  **Agent-Based 架构 (代理模式):**
    *   **`TaskPlannerAgent`**: 扮演“项目经理”的角色，负责高级规划和最终报告的整合。
    *   **`TaskActorAgent`**: 扮演“执行者”的角色，负责具体任务步骤的实施。
    *   **`BaseAgent`**: 提供了代理与 LLM 交互的通用框架，封装了消息历史管理、工具调用等通用逻辑。
    *   这种分工使得复杂任务可以被有效分解和管理。

3.  **动态任务规划与管理 (`todolist.Plan`):**
    *   **有向无环图 (DAG)**: `Plan` 对象将任务表示为步骤的 DAG，通过 `dependencies` 属性定义执行顺序。
    *   **状态机**: 每个步骤都有明确的状态（`not_started`, `in_progress`, `completed`, `blocked`），驱动任务的执行流程。
    *   **动态调整**: 架构支持（尽管 `re_plan` 当前被注释）在执行过程中修改计划，增加了系统的灵活性和鲁棒性。
    *   **文件自动追踪**: `process_text_with_workspace` 自动关联工作区文件与计划步骤，方便结果追溯和展示。

4.  **模块化工具集 (`app/cosight/tool/`):**
    *   提供了一系列可插拔的工具，赋予 `TaskActorAgent` 执行多样化操作的能力，如网络搜索、文件读写、代码执行、数据提取等。
    *   这种设计使得系统易于扩展新功能，只需添加新的工具模块并让 LLM 知道如何使用它们。

5.  **异步与并发处理:**
    *   **FastAPI**: 后端采用 FastAPI 框架，天然支持异步操作，适合 I/O 密集型任务（如等待 LLM 响应、外部 API 调用）。
    *   **`StreamingResponse`**: 用于向客户端实时推送计划更新，提升用户体验。
    *   **`asyncio.Queue`**: 在同步的后台任务线程 (`run_manus`) 和 FastAPI 的异步事件循环之间安全地传递数据。
    *   **`ThreadPoolExecutor`**: 在 `CoSight.execute_steps()` 中用于并发执行多个独立的 `TaskActorAgent.act()` 调用，加快整体任务处理速度。

6.  **事件驱动的 UI 更新 (`plan_report_event_manager`):**
    *   一个简单的发布/订阅事件管理器，用于解耦计划状态变更的产生方（如 `Plan` 对象、Agents）和消费方（如 `search.py` 中的流式响应逻辑）。
    *   当计划状态发生重要变化时，发布事件，订阅者（主要是 `search.py`）接收到事件后将更新推送到前端。

7.  **工作区隔离 (`work_space/`):**
    *   为每个任务创建独立的子目录，确保了文件操作的隔离性，避免了任务间的干扰，也方便了结果的组织和清理。

这些技术和流程共同构成了 Co-Sight 作为一个能够自主执行复杂研究任务并生成报告的智能系统的基础。
