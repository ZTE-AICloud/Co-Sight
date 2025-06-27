### 2. 代码结构说明

**1. `cosight_ui` (前端 - Angular):**

*   **角色:** 提供基于 Web 的用户界面，用于与 Co-Sight 系统交互。用户提交研究任务，实时查看计划执行进度，并访问最终生成的报告和任何相关文件。
*   **关键文件/指标:**
    *   `angular.json`: 标准 Angular 工作区配置文件，定义项目结构、构建和服务选项。
    *   `package.json`: 列出前端依赖项（Angular 库、UI 组件等）以及用于构建和运行前端的脚本。
    *   `src/app/app.module.pc.ts` (及类似的 `*.module.ts` 文件): 定义 Angular 模块，这些模块对组件、指令、管道和服务进行分组。这表明了模块化的应用程序结构。
    *   `src/app/components/`: 可能包含在应用程序不同部分使用的可重用 UI 组件。
    *   `src/app/pages/`: 包含表示应用程序内不同视图或页面的组件（例如，主要研究界面）。
    *   `src/app/service/`: 包含负责与后端 API 通信、管理应用程序状态等任务的 Angular 服务。
    *   `src/app/router-config.ts` (或类似的路由模块): 定义导航路径并将其映射到特定的 Angular 组件，控制给定 URL 显示哪个视图。
    *   `src/index.html`: 引导 Angular 应用程序的主 HTML 页面。
    *   `src/main.pc.ts`: 引导 Angular 应用程序的主 TypeScript 文件。

**2. `cosight_server` (后端 - FastAPI):**

*   **角色:** 后端服务器，处理来自前端的 API 请求，使用核心代理逻辑编排研究任务，并将更新流式传输回客户端。
*   **结构:**
    *   `deep_research/main.py`:
        *   FastAPI 应用程序的主入口点。
        *   初始化 FastAPI 应用程序，加载环境变量，并设置自定义配置。
        *   配置中间件（例如，全局异常处理）。
        *   挂载静态文件目录：
            *   `/cosight`: 提供 Angular 前端应用程序（构建后可能来自 `cosight_ui/dist/cosight_ui` 或 `cosight_server/web`）。
            *   `/{base_api_url}/upload_files`: 提供用户上传的文件。
            *   `/{base_api_url}/work_space`: 提供在特定任务工作区中生成的文件。
        *   包含来自 `routers` 子目录的 API 路由器。
        *   启动 `uvicorn` ASGI 服务器以运行应用程序。
    *   `deep_research/routers/`: 此目录包含定义不同 API 路由组的模块。
        *   `search.py` (`searchRouter`):
            *   定义关键的 `/deep-research/search` 端点。
            *   处理传入的研究查询。
            *   在单独的线程中启动 `CoSight` 任务执行过程。
            *   设置 `asyncio.Queue` 并订阅 `plan_report_event_manager` 以从执行计划接收实时更新。
            *   使用 FastAPI 的 `StreamingResponse` 将这些更新（计划结构、步骤状态、备注、文件链接、最终结果）作为 JSON 对象流发送到客户端。
        *   `user_manager.py` (`userRouter`): 可能处理用户身份验证、注册和配置文件管理。
        *   `websocket_manager.py` (`wsRouter`): 提供 WebSocket 端点，可能用于需要比用于搜索结果的主要 HTTP 流更持久的双向通信的功能。
        *   `common.py` (`commonRouter`): 定义通用或实用程序 API 端点。
        *   `chat_manager.py` (`chatRouter`): 暗示了直接聊天交互的功能，可能与主要研究任务流程分开。
        *   `feedback.py` (`feedbackRouter`): 用户提交反馈的端点。
    *   `deep_research/services/`: 包含服务层逻辑，例如用于国际化的 `i18n_service.py`。
    *   `deep_research/common/`: 特定于服务器 `deep_research` 部分的通用配置或实用程序。
    *   `sdk/`: 似乎是一个软件开发工具包，可能用于以编程方式与 Co-Sight 服务交互或用于共享实用程序。包含 API 结果格式化、缓存和配置管理等通用元素。

**3. `app` (核心逻辑 - Python):**

*   **角色:** 包含 Co-Sight 系统的核心智能，包括代理框架、任务处理逻辑和工具集成。
*   **结构:**
    *   `CoSight.py`:
        *   定义主要的 `CoSight` 类。此类充当研究任务的主要编排器。
        *   其 `execute()` 方法接受用户查询，初始化一个 `Plan`，然后管理 `TaskPlannerAgent`（用于创建/优化计划）和 `TaskActorAgent`(s)（用于执行计划步骤）之间的交互。
        *   处理就绪计划步骤的并行执行。
    *   `app/cosight/agent/`: 此目录包含与代理相关的代码。
        *   `base/base_agent.py`:
            *   定义 `BaseAgent` 类，它是 `TaskPlannerAgent` 和 `TaskActorAgent` 的父类。
            *   实现与 LLM 交互的核心循环，包括发送提示、接收响应以及处理 LLM 调用工具（函数调用）的请求。
            *   管理与 LLM 的对话历史。
            *   包括基于 LLM 请求执行 Python 函数（工具）的逻辑，支持同步和异步工具函数。
        *   `planner/task_plannr_agent.py`:
            *   定义 `TaskPlannerAgent`。
            *   负责根据用户查询生成初始研究计划，必要时重新规划，并生成最终摘要或报告。
            *   使用针对规划定制的特定提示和工具（例如，`PlanToolkit` 来修改 `Plan` 对象）。
        *   `actor/task_actor_agent.py`:
            *   定义 `TaskActorAgent`。
            *   负责执行由 `TaskPlannerAgent` 生成的计划的各个步骤。
            *   配备了广泛的工具（搜索、文件 I/O、代码执行等）来执行操作。
            *   使用步骤执行的状态和结果更新 `Plan` 对象。
        *   `app/cosight/agent/planner/instance/` 和 `app/cosight/agent/actor/instance/`: 这些目录包含模块（例如，`planner_agent_instance.py`、`actor_agent_instance.py`），这些模块可能提供工厂函数（`create_planner_instance`、`create_actor_instance`）或用于创建特定类型或规划器和执行器代理实例的配置。这允许不同的代理行为或功能。
        *   `app/cosight/agent/.../prompt/`: 包含定义用于指导 LLM 进行规划和执行代理的系统和用户提示的 Python 文件（例如，`planner_prompt.py`、`actor_prompt.py`）。
    *   `app/cosight/llm/`:
        *   `chat_llm.py`: 提供 `ChatLLM` 类，这是一个用于与各种基于聊天的 LLM 交互的抽象层。它处理 API 调用、令牌限制和工具/函数调用参数。
    *   `app/cosight/task/`: 与管理和表示任务相关的组件。
        *   `todolist.py`:
            *   定义关键的 `Plan` 类。此类将研究任务建模为步骤的有向无环图 (DAG)。
            *   它存储步骤、其描述、依赖关系、当前状态（例如，“not_started”、“in_progress”、“completed”、“blocked”）、备注和结果。
            *   包括获取准备执行的步骤、更新计划、标记步骤进度以及格式化计划以供显示或 LLM 使用的方法。
            *   关键的是，它与 `process_text_with_workspace` 集成，以自动查找和链接在步骤备注中提及或由工具创建的任务 `work_space_path` 内的文件。
        *   `plan_report_manager.py`: 使用简单的发布-订阅模式实现事件管理器 (`plan_report_event_manager`)。`CoSight`、代理和 `Plan` 对象使用它来广播有关计划创建、进度和完成的更新。`search.py` 路由器订阅这些事件以将更新流式传输到 UI。
        *   `task_manager.py`: 一个简单的管理器 (`TaskManager`)，用于将 `plan_id` 与其对应的 `Plan` 对象相关联，允许不同组件检索当前计划状态。
        *   `time_record_util.py`: 用于计时函数执行的实用程序，用作装饰器。
    *   `app/cosight/tool/`: 一个丰富的模块集合，每个模块提供 `TaskActorAgent` 可以使用的特定工具（Python 函数）。示例：
        *   `search_toolkit.py`、`deep_search/`、`search_util.py`: 用于各种 Web 搜索功能（Google、Tavily、Baidu、Wikipedia）。
        *   `file_toolkit.py`: 用于在 `work_space_path` 中读取、写入和修改文件。
        *   `code_toolkit.py`: 用于在受控环境（例如，子进程沙箱）中执行 Python 代码片段。
        *   `scrape_website_toolkit.py`、`web_util.py`: 用于获取和处理网页内容。
        *   `image_analysis_toolkit.py`、`video_analysis_toolkit.py`、`audio_toolkit.py`: 用于处理多媒体内容。
        *   `document_processing_toolkit.py`: 用于从文档（PDF、DOCX 等）中提取文本和数据。
        *   `html_visualization_toolkit.py`: 用于生成 HTML 报告，可能带有图表。
        *   `terminate_toolkit.py`: 提供一个 `terminate` 工具，代理可以调用该工具来表示完成或停止执行。
        *   `plan_toolkit.py`: `TaskPlannerAgent` 专门用于创建和更新 `Plan` 对象的工具。
        *   `act_toolkit.py`: `TaskActorAgent` 的工具，例如 `mark_step` 来更新计划。
    *   `app/agent_dispatcher/`: 此目录似乎是更通用的代理框架或 `CoSight` 可能基于或部分使用的早期版本/组件的一部分。它拥有自己的域、应用程序和基础架构层，定义了 `BaseAgent` 使用的 `AgentInstance`。它可能处理代理注册、技能定义和 MCP（多云平台？）工具集成。
    *   `app/common/`: 共享实用程序，如 `logger_util.py`。

**4. 根目录文件:**

*   `CoSight.py`: （已在 `app` 下描述，因为它在 `search.py` 中从那里导入，但物理上它在根目录中。为了更清晰的结构，最好将其放在 `app` 目录中）。
*   `llm.py`: 初始化和配置全局 LLM 实例（例如，`llm_for_plan`、`llm_for_act`），然后由应用程序的各个部分（尤其是 `CoSight` 和代理）导入和使用。
*   `Dockerfile`: 定义用于部署 Co-Sight 的 Docker 镜像，指定基础镜像、依赖项以及如何运行应用程序。
*   `.env_template`, `.env`: 模板和实际环境变量配置文件（API 密钥、模型名称等）。
*   `requirements.txt`: 列出后端的 Python 依赖项。
*   `setup.py`: 标准 Python 包安装文件，表明该项目可以作为包安装。
*   `README.md`, `README-zh.md`: 项目文档。

**5. `work_space/` 目录:**

*   **角色:** 此目录在运行时动态使用。对于用户启动的每个研究任务，都会在 `work_space` 内创建一个唯一的子目录（例如，`work_space/work_space_YYYYMMDD_HHMMSS_ffffff`）。
*   **内容:** 这个特定于任务的子目录存储与任务相关的所有工件：
    *   日志（例如，`plan.log` 包含流式计划更新）。
    *   从互联网下载的文件。
    *   由工具创建的文件（例如，文本文件、代码输出、图像、HTML 报告）。
    *   中间数据。
    *   `Plan` 对象的文件跟踪机制将备注和步骤链接到此目录中的文件。

这种结构将关注点分离到 UI、服务器逻辑、核心代理/任务处理和工具中，从而形成一个模块化且可扩展的系统。`app` 目录构成了 Co-Sight 的智能核心。
