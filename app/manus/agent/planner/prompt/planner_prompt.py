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
6. The created task is scheduled to be completed within 5 steps


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
    replan_prompt = f"""
Original task:{question}
"""
    output_format_prompt = f"""
Ensure your final answer contains only the content in the following format: {output_format}
"""
    if output_format:
        replan_prompt += output_format_prompt
    replan_prompt += f"""
Current plan status:
{plan}

Evaluate and adjust the current plan according to the replanning rules in the system prompt.
    """
    return replan_prompt


def planner_finalize_plan_prompt(question, plan, output_format=""):
    finalize_prompt = f"""
Now please make a final answer of the original task based on our conversation : <task>{question}</task>

Plan status:
{plan}

Now please make a final answer of the original task based on our conversation : <task>{question}</task>

Plan status:
{plan}

Please pay special attention to the format in which the answer is presented.
You should first analyze the answer format required by the question and then output the final answer that meets the format requirements. 
Your response should include the following content:
- `analysis`: enclosed by <analysis> </analysis>, a detailed analysis of the reasoning result.
- `final_answer`: enclosed by <final_answer> </final_answer>, the final answer to the question.
Here are some hint about the final answer:
<hint>
Your final answer must be output exactly in the format specified by the question. It should be a number OR as few words as possible OR a comma separated list of numbers and/or strings:
- If you are asked for a number, don't use comma to write your number neither use units such as $ or percent sign unless specified otherwise. 
- If you are asked for a string, don't use articles, neither abbreviations (e.g. for cities), and write the digits in plain text unless specified otherwise. 
- If you are asked for a comma separated list, apply the above rules depending of whether the element to be put in the list is a number or a string.
1. Directly return the answer to the question without answering any other content
2. Return only your answer, which should be a number, or a short phrase with as few words as possible, or a comma separated list of numbers and/or strings.
</hint>
"""
    return finalize_prompt
