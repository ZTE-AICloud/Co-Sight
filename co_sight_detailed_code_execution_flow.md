### 6. 详细代码流程说明

此部分在前述“代码运行流程分析”中已详细阐述，涵盖了从用户请求到最终结果呈现的整个链路，包括了关键类如 `CoSight`, `TaskPlannerAgent`, `TaskActorAgent`, `BaseAgent`, `Plan` 的交互，以及它们如何通过 `search.py` 中的流式响应机制与前端UI通信。重点包括：

*   **提示构建:** `TaskPlannerAgent` 和 `TaskActorAgent` 如何使用 `planner_prompt.py` 和 `actor_prompt.py` 中的模板构建特定的提示，以指导 LLM 进行规划和执行。
*   **工具调用机制:** `BaseAgent` 如何处理 LLM 的工具调用请求：LLM 返回需要调用的函数名和参数，`BaseAgent` 查找并执行对应的 Python 工具函数 (来自 `app/cosight/tool/` 下的各个 `Toolkit`)，然后将工具的输出返回给 LLM 继续处理。
*   **`Plan.get_ready_steps()` 的作用:** 此方法是驱动 `CoSight.execute()` 中主执行循环的核心，它根据步骤依赖和当前状态动态决定哪些步骤可以并行或串行执行。
*   **`Plan.mark_step()` 和 `process_text_with_workspace()`:** 这组功能如何协同工作以更新步骤状态、记录备注，并通过扫描工作区和备注内容自动发现和链接相关文件 (如搜索结果、生成报告等)，这些文件信息存储在 `Plan.step_files` 中，最终可供前端展示。
*   **事件机制 (`plan_report_event_manager`):** `CoSight`、代理和 `Plan` 对象如何通过发布事件 (`plan_created`, `plan_updated`, `plan_process`, `plan_result`) 来解耦组件，并允许 `search.py` 中的回调函数 (`append_create_plan`) 捕获这些更新，通过 `asyncio.Queue` 将其推送给 FastAPI 的 `StreamingResponse`，从而实现对前端UI的实时更新。

**详细补充：**

**1. 请求入口与流式响应 (`search.py`)**

*   当用户在UI提交查询，请求到达 `search.py` 中的 `search` FastAPI端点。
*   `search` 函数的核心职责是启动后台任务并建立一个流式响应通道。
*   **工作空间创建**: `os.path.join(work_space_path, f'work_space_{timestamp}')` 创建一个唯一的目录。`os.environ['WORKSPACE_PATH']` 被设置为此路径，确保后续所有文件操作（如工具保存文件、日志记录）都发生在此隔离的环境中。
*   **`run_manus` 线程**:
    *   `CoSight(llm_for_plan, ..., work_space_path=work_space_path_time)`: `CoSight` 实例在初始化时接收到这个特定于任务的工作空间路径。
    *   `plan_report_event_manager.subscribe(...)`: 通过 `append_create_plan` 回调，将 `CoSight` 执行过程中产生的计划更新事件连接到 `plan_queue`。
    *   `append_create_plan(data)`:
        *   如果 `data` 是 `Plan` 对象，会先转换为字典。
        *   使用 `json.dumps` 序列化数据。
        *   写入 `plan.log` 文件。
        *   `asyncio.run_coroutine_threadsafe(plan_queue.put(plan_dict), main_loop)`: 这是关键的线程安全操作，将数据从 `run_manus` 的同步线程发送到 FastAPI 的异步事件循环中的 `plan_queue`。
*   **`generate_stream_response` 与 `generator_func`**:
    *   `generator_func` 使用 `await asyncio.wait_for(plan_queue.get(), timeout=60.0)` 从队列中异步获取数据。
    *   每次获取到数据（代表计划的一个状态更新），`generate_stream_response` 将其包装成特定格式的 JSON 字符串（`{"contentType": "lui-message-manus-step", ...}`）并 `yield` 出去。FastAPI 将这些 `yield` 的数据块作为流式响应体的一部分发送给客户端。

**2. 规划阶段 (`CoSight` -> `TaskPlannerAgent` -> `BaseAgent`)**

*   `CoSight.execute()`:
    *   `self.plan = Plan(...)`: 创建 `Plan` 实例，此实例将贯穿整个任务生命周期。
    *   `TaskPlannerAgent.__init__(...)`:
        *   `PlanToolkit(self.plan)`: `PlanToolkit` 持有对当前 `Plan` 对象的引用，因此其工具方法可以直接修改这个共享的计划状态。
        *   其 `self.functions` 字典映射工具名（如 "create_plan"）到 `PlanToolkit` 的方法。
*   `TaskPlannerAgent.create_plan()`:
    *   `planner_system_prompt(question)` 和 `planner_create_plan_prompt(question, output_format)` 用于构建发送给LLM的初始消息列表 `self.history`。
*   `BaseAgent.execute()`:
    *   `self.llm.create_with_tools(messages, self.tools)`: `self.tools` 是根据 `AgentInstance` 中的技能（skills）通过 `convert_skill_to_tool` 转换得到的符合LLM函数调用规范的JSON Schema列表。`ChatLLM.create_with_tools` 方法负责与LLM API交互，发送消息历史和工具定义。
    *   LLM返回的响应中若包含 `tool_calls`，`_execute_tool_call` 会被调用。
    *   `function_to_call = self.functions[function_name]` 查找到 `PlanToolkit.create_plan`。
    *   `PlanToolkit.create_plan` 调用 `self.plan.update(title, steps, dependencies)`。
        *   `Plan.update()`: 更新计划的各个属性。`self.dependencies` 会被重置并根据LLM的输出更新。
        *   **事件发布**: 逻辑上，在 `Plan.update` 内部或其调用者（`PlanToolkit`）在成功更新计划后，应调用 `plan_report_event_manager.publish("plan_created", self.plan)` 或 `"plan_updated"`。

**3. 执行阶段 (`CoSight` -> `TaskActorAgent` -> `BaseAgent`)**

*   `CoSight.execute()` 的主循环:
    *   `self.plan.get_ready_steps()`:
        *   `Plan.get_ready_steps()`: 遍历 `self.steps` 列表（注意，`self.dependencies` 的键是步骤索引，值是依赖的步骤索引列表）。它检查每个步骤 `i` 的依赖 `dep_idx` 是否满足 `self.step_statuses[self.steps[dep_idx]] != "not_started"`，并且步骤 `i` 本身的状态是 `"not_started"`。
*   `CoSight.execute_steps()`: 并发执行就绪步骤。
*   `TaskActorAgent.__init__(...)`:
    *   初始化各种工具包，如 `FileToolkit(self.work_space_path)`，确保工具操作在正确的任务工作区内。
    *   `actor_system_prompt_zh/en(self.work_space_path)`: 系统提示告知LLM其角色、可用工具和工作目录。
*   `TaskActorAgent.act(question, step_index)`:
    *   `self.plan.mark_step(step_index, step_status="in_progress")`: 更新计划状态并触发 `plan_process` 事件。
    *   `actor_execute_task_prompt_zh/en(question, step_index, self.plan, self.work_space_path)`: 构造用户提示，包含全局问题、当前步骤描述 (来自 `self.plan.steps[step_index]`)、整个计划的当前状态 (`self.plan.format()`) 以及工作区路径。这为LLM提供了充分的上下文。
*   `BaseAgent.execute()` (由 `TaskActorAgent` 调用):
    *   LLM根据提示和可用工具（如`search_google`, `file_saver`, `execute_code`, `mark_step`）决定执行哪个工具。
    *   例如，调用 `file_saver("results.txt", "content")`:
        *   `FileToolkit.file_saver` 方法被执行，它使用 `self.work_space_path` (在 `FileToolkit` 初始化时传入) 来构造完整路径并保存文件。
    *   当LLM最终决定调用 `mark_step` 工具时 (例如 `mark_step(step_status="completed", step_notes="已将分析结果保存到 report.md")`):
        *   `ActToolkit.mark_step` 被调用。
        *   `self.plan.mark_step(step_index, "completed", "已将分析结果保存到 report.md")`:
            *   `Plan.mark_step` 更新状态和备注。
            *   `step_notes, file_path_info = process_text_with_workspace(step_notes, self.work_space_path)`:
                *   `process_text_with_workspace` 调用 `extract_and_replace_paths`。
                *   `extract_and_replace_paths` 使用正则表达式 (`path_file_pattern`, `quoted_file_pattern`) 匹配 `step_notes` 中的文件名或路径。
                *   同时，它会 `os.listdir(workspace_path)` 和 `os.walk(workspace_path)` 来查找工作区中实际存在的文件。
                *   所有找到或匹配的文件名和相对路径（相对于 `work_space_path` 的上一级目录名，例如 `work_space_XYZ/report.md`）被收集到 `result_list` 中，该列表赋值给 `self.step_files[self.steps[step_index]]`。
            *   再次触发 `plan_process` 事件，UI会收到更新，包括可点击的文件链接。

**4. 最终化 (`CoSight` -> `TaskPlannerAgent`)**

*   `TaskPlannerAgent.finalize_plan()`:
    *   `planner_finalize_plan_prompt(question, self.plan.format(), output_format)`: 提示LLM基于整个已执行的计划 (`self.plan.format()` 提供了所有步骤、状态和备注) 来生成最终报告。
    *   `self.llm.chat_to_llm(self.history)`: 直接与LLM对话获取最终文本，不涉及工具调用。
    *   `self.plan.set_plan_result(result)` 和 `plan_report_event_manager.publish("plan_result", self.plan)` 将最终结果存入计划并通知UI。

这个流程强调了状态管理 (`Plan` 对象)、事件驱动的UI更新、LLM通过工具与环境交互（文件系统、网络搜索）以及上下文（通过精心设计的提示）在整个任务执行中的重要性。 `work_space_path` 的正确传递和使用是确保多任务隔离和工具正确操作的关键。
