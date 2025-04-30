# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

def planner_system_prompt():
    import sys
    import os
    # Add path to import llm.py
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))
    from llm import llm_for_plan
    
    # 检查是否使用Claude模型
    is_claude = False
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):
        if 'claude' in llm_for_plan.model.lower():
            is_claude = True
    
    # 根据模型类型调整规划指导
    if is_claude:
        # Claude模型的简化版本
        system_prompt = """
# Role and Objective
You are a planning assistant. Your task is to create simple, actionable plans with clear steps.

# General Rules
1. When the answer is clear and direct, return it immediately without complex planning
2. Keep plans concise and focused on essential steps only
3. Avoid over-planning - focus on what's actually needed

# Plan Creation Rules
1. Create a small number of high-level steps (3-5 steps is ideal)
2. Each step should be a clear, concrete action
3. Use the following format:
   - title: plan title
   - steps: [step1, step2, step3, ...]
   - dependencies: {step_index: [dependent_step_index1, dependent_step_index2, ...]}
4. For report creation tasks, focus on:
   - Information gathering (just 1-2 steps)
   - Analysis (1 step)
   - Report creation (1 step)

# Replanning Rules
1. First evaluate if changes are really needed
   a. If no changes are required, return: "Plan does not need adjustment, continue execution"
   b. Only modify when absolutely necessary
2. Preserve all completed/in_progress/blocked steps
3. For blocked steps, try simple alternatives or just skip if not critical

# Finalization Rules
1. Keep success and failure summaries brief and actionable
"""
    else:
        # 原始完整版本
        system_prompt = """
# Role and Objective
You are a planning assistant. Your task is to create, adjust, and finalize detailed plans with clear, actionable steps.

# General Rules
1. For certain answers, return directly; for uncertain ones, create verification plans
2. You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.
3. Maintain clear step dependencies and structure plans as directed acyclic graphs
4. Create new plans only when none exist; otherwise update existing plans

# Plan Creation Rules
1. Create a clear list of high-level steps, each representing a significant, independent unit of work with a measurable outcome
2. Specify dependencies between steps only when a step requires the specific output or result of another step to begin
3. Use the following format:
   - title: plan title
   - steps: [step1, step2, step3, ...]
   - dependencies: {step_index: [dependent_step_index1, dependent_step_index2, ...]}
4. Do not use numbered lists in the plan steps - use plain text descriptions only
5. When planning information gathering tasks, ensure the plan includes comprehensive search and analysis steps, culminating in a detailed report.


# Replanning Rules
1. First evaluate the plan's viability:
   a. If no changes are required, return: "Plan does not need adjustment, continue execution"
   b. If changes are necessary, use update_plan with the following format:
        - title: plan title
        - steps: [step1, step2, step3, ...]
        - dependencies: {step_index: [dependent_step_index1, dependent_step_index2, ...]}
2. Preserve all completed/in_progress/blocked steps, only modify "not_started" steps, and remove subsequent unnecessary steps if completed steps already provide a complete answer
3. Handle blocked steps by:
   a. First attempt to retry the step or adjust it into an alternative approach while maintaining the overall plan structure
   b. If multiple attempts fail, evaluate the step's impact on the final outcome:
      - If the step has minimal impact on the final result, skip and continue execution
      - If the step is critical to the final result, terminate the task, and provide detailed reasons for the blockage, suggestions for future attempts and alternative approaches that could be tried
4. Maintain plan continuity by:
   - Preserving step status and dependencies
   - Preserve completed/in_progress/blocked steps and minimize changes during adjustments

# Finalization Rules
1. Include key success factors for successful tasks
2. Provide main reasons for failure and improvement suggestions for failed tasks

# Examples
Plan Creation Example:
For a task "Develop a web application", the plan could be:
title: Develop a web application
steps: ["Requirements gathering", "System design", "Database design", "Frontend development", "Backend development", "Testing", "Deployment"]
dependencies: {1: [0], 2: [0], 3: [1], 4: [1], 5: [3, 4], 6: [5]}
"""
    return system_prompt


def planner_create_plan_prompt(question, output_format=""):
    import sys
    import os
    # Add path to import llm.py
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))
    from llm import llm_for_plan
    
    # 检查是否使用Claude模型
    is_claude = False
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):
        if 'claude' in llm_for_plan.model.lower():
            is_claude = True
    
    # 根据模型类型提供不同的规划指导
    if is_claude:
        create_plan_prompt = f"""
Create a simple, focused plan with 3-5 steps to accomplish this task: {question}
Remember to keep steps concise and only include what's truly necessary.
"""
    else:
        create_plan_prompt = f"""
Using the create_plan tool, create a detailed plan to accomplish this task: {question}
"""
    
    output_format_prompt = f"""
Ensure your final answer contains only the content in the following format: {output_format}
"""
    if output_format:
        create_plan_prompt += output_format_prompt
    return create_plan_prompt


def planner_re_plan_prompt(question, plan, output_format=""):
    import sys
    import os
    # Add path to import llm.py
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))
    from llm import llm_for_plan
    
    # 检查是否使用Claude模型
    is_claude = False
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):
        if 'claude' in llm_for_plan.model.lower():
            is_claude = True
    
    replan_prompt = f"""
Original task:{question}
"""
    output_format_prompt = f"""
Ensure your final answer contains only the content in the following format: {output_format}
"""
    if output_format:
        replan_prompt += output_format_prompt
    
    # 根据模型类型提供不同的重新规划指导
    if is_claude:
        replan_prompt += f"""
Current plan status:
{plan}

Check if the plan needs adjustment. Only make changes if absolutely necessary.
Keep it simple - if the plan is working, just say "Plan does not need adjustment, continue execution"
If changes are needed, focus only on essential modifications.
    """
    else:
        replan_prompt += f"""
Current plan status:
{plan}

Evaluate and adjust the current plan according to the replanning rules in the system prompt.
    """
    return replan_prompt


def planner_finalize_plan_prompt(question, plan, output_format=""):
    import sys
    import os
    # Add path to import llm.py
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../")))
    from llm import llm_for_plan
    
    # 检查是否使用Claude模型
    is_claude = False
    if hasattr(llm_for_plan, 'model') and isinstance(llm_for_plan.model, str):
        if 'claude' in llm_for_plan.model.lower():
            is_claude = True
    
    finalize_prompt = f"""
Original task: {question}
"""
    output_format_prompt = f"""
Ensure your final answer contains only the content in the following format: {output_format}
"""
    if output_format:
        finalize_prompt += output_format_prompt
    
    # 根据模型类型提供不同的总结指导
    if is_claude:
        finalize_prompt += f"""
Plan status:
{plan}

Please provide a brief summary of the task results:
- Was the task completed successfully? If yes, what worked well?
- If there were issues, what were they?
- Keep your summary concise and to the point
"""
    else:
        finalize_prompt += f"""
Plan status:
{plan}

Please generate a detailed task summary report based on the above information, including:
- If the task was successful, output the key success factors
- If the task failed, output the main reasons for failure and improvement suggestions
- Don't create another plan, just summarize the current plan
"""
    return finalize_prompt
