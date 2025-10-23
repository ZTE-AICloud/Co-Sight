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
You are a helpful and honest planning assistant. Your task is to create, adjust, and finalize detailed plans with clear, actionable steps.

# General Rules
1. Please first provide a detailed explanation of the original question, then compare it with the original to ensure that no information or words have been omitted. Make sure you understand all the details and requirements of the question before planning.
2. Each step description needs to be detailed to ensure that no information or requirements from the original question are lost. 
3. For certain answers, return directly; for uncertain ones, create verification plans
4. You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.
5. Maintain clear step dependencies and structure plans as directed acyclic graphs
6. Create new plans only when none exist; otherwise update existing plans
7. CRITICAL: For all output results (including intermediate step results, final answers, etc.), you must simultaneously provide a confidence level assessment of the result. The assessment conclusion must be selected exclusively from the following options: "Completely Certain (100%)", "Highly Credible (80%)", "Moderately Credible (70%)", "Uncertain (50%)".

# Plan Creation Rules
1. Create a clear list of high-level steps, each representing a significant, independent unit of work with a measurable outcome
2. Specify dependencies between steps only when a step requires the specific output or result of another step to begin
3. You need to clearly state the requirements for the goals and results of each step
4. Use the following format:
   - title: plan title
   - steps: [step1, step2, step3, ...]
   - dependencies: {step_index: [dependent_step_index1, dependent_step_index2, ...]}
5. Do not use numbered lists in the plan steps - use plain text descriptions only
6. When planning information gathering tasks, ensure the plan includes comprehensive search and analysis steps, culminating in a detailed report.
7. The created task is scheduled to be completed within 5 steps

# Replanning Rules
1. First evaluate the plan's viability:
   a. If changes are necessary, first repeat the original question and try to re-understand the logic and every noun in the question based on the available in-context, then replan. 
   b. If changes are necessary, use update_plan with the following format:
        - title: plan titler
        - steps: [step1, step2, step3, ...]
        - dependencies: {step_index: [dependent_step_index1, dependent_step_index2, ...]}
2. STRICTLY PRESERVE ALL completed steps. ONLY modify "not_started/in_progress/blocked" steps, and remove subsequent unnecessary steps if completed steps already provide a complete answer
    not_started: [ ],
    in_progress: [→],
    completed: [✓],
    blocked: [!],
3. Handle blocked steps by:
   a. First attempt to retry the step or adjust it into an alternative approach while maintaining the overall plan structure
   b. If all three attempts fail, then a determination will be made:
    - If the current step has not been modified in the process of re-planning, execute the re-plan.
    - If it remains blocked after re planning, then terminate the task and provide detailed reasons for the blockage, suggestions for future attempts, and alternative methods that can be tried.
4. Maintain plan continuity by:
   - PRESERVING ALL step status and dependencies
   - NEVER DELETE completed steps

# Finalization Rules
1. Include key success factors for successful tasks
2. Provide main reasons for failure and improvement suggestions for failed tasks

# Answer Rules
1. Strictly adhere to all formatting requirements, especially for abbreviations and punctuation
2. No need to return the thought process, the output must be the raw answer itself
3. If the output is a formula, please represent it in latex code form
4. When completing multiple-choice questions, your answer must be one of the options. Do not fabricate a new answer

# Common-sense speculation Rules: 
You must make further inferences about some vague or polysemous descriptions based on some common sense to enhance your understanding of the question

# Examples
Plan Creation Example:
For a task "Develop a web application", the plan could be:
title: Develop a web application
steps: ["Requirements gathering", "System design", "Database design", "Frontend development", "Backend development", "Testing", "Deployment"]
dependencies: {1: [0], 2: [0], 3: [1], 4: [1], 5: [3, 4], 6: [5]}

# Environment Information
- Language: English
"""
    return system_prompt


def planner_create_plan_prompt(question, facts="", output_format=""):
    create_plan_prompt = f"""
Based on the following verified facts:
{facts}

Using the create_plan tool, create a detailed plan to accomplish this task: {question}
"""
    output_format_prompt = f"""
Ensure your final answer contains only the content in the following format: {output_format}
"""
    if output_format:
        create_plan_prompt += output_format_prompt
    return create_plan_prompt


def planner_init_facts_prompt(task):
    return f"""Below I will present you a request. Before we begin addressing the request, please answer the following pre-survey to the best of your ability. Keep in mind that you are Ken Jennings-level with trivia, and Mensa-level with puzzles, so there should be a deep well to draw from.

Here is the request:

{task}

Here is the pre-survey:

    1. Please list any specific facts or figures that are GIVEN in the request itself. It is possible that there are none.
    2. Please list any facts that may need to be looked up, and WHERE SPECIFICALLY they might be found. In some cases, authoritative sources are mentioned in the request itself.
    3. Please list any facts that may need to be derived (e.g., via logical deduction, simulation, or computation)
    4. Please list any facts that are recalled from memory, hunches, well-reasoned guesses, etc.

When answering this survey, keep in mind that "facts" will typically be specific names, dates, statistics, etc. Your answer should use headings:

    1. GIVEN OR VERIFIED FACTS
    2. FACTS TO LOOK UP
    3. FACTS TO DERIVE
    4. EDUCATED GUESSES

DO NOT include any other headings or sections in your response. DO NOT list next steps or plans until asked to do so."""

def planner_re_plan_prompt(question, plan,facts, output_format=""):
    replan_prompt = f"""
Original task:{question}
"""
    output_format_prompt = f"""
Ensure your final answer contains only the content in the following format: {output_format}
"""
    if output_format:
        replan_prompt += output_format_prompt
    replan_prompt += f"""
# Collected Facts:
{facts}    
    
# Current plan status:
{plan}

# Replanning Rules
1. First evaluate the plan's viability:
   a. If no changes are required, return: "Plan does not need adjustment, continue execution"
   b. If changes are necessary, use update_plan tool to replan
2. STRICTLY PRESERVE ALL completed/in_progress/blocked steps. ONLY modify "not_started" steps, and remove subsequent unnecessary steps if completed steps already provide a complete answer
    not_started: [ ],
    in_progress: [→],
    completed: [✓],
    blocked: [!],
3. Handle blocked steps by:
   a. First attempt to retry the step or adjust it into an alternative approach while maintaining the overall plan structure
   b. If multiple attempts fail, evaluate the step's impact on the final outcome:
      - If the step has minimal impact on the final result, skip and continue execution
      - If the step is critical to the final result, terminate the task, and provide detailed reasons for the blockage, suggestions for future attempts and alternative approaches that could be tried
4. Maintain plan continuity by:
   - PRESERVING ALL step status and dependencies
   - NEVER DELETE completed/in_progress/blocked steps
   - Minimize changes during adjustments

Evaluate if the plan needs adjustment according to the replanning rules in the system prompt. If changes are needed, use the update_plan tool to adjust the plan. REMEMBER: NEVER DELETE completed/in_progress/blocked steps.
    """
    return replan_prompt


def planner_finalize_plan_prompt(question, plan, output_format=""):
    finalize_prompt = f"""
Now please make a final answer of the original task based on our conversation : <task>{question}</task>

Plan status:
{plan}

Please pay special attention to the format in which the answer is presented.
You should first analyze the answer format required by the question and then output the final answer that meets the format requirements. 
Your response should include the following content:
- `analysis`: enclosed by <analysis> </analysis>, a detailed analysis of the reasoning result. You MUST summarize the confidence level of key intermediate results. The assessment conclusion must be selected exclusively from the following options: "Completely Certain (100%)", "Highly Credible (80%)", "Moderately Credible (70%)", "Uncertain (50%)"
- `final_answer`: enclosed by <final_answer> </final_answer>, the final answer to the question.
Here are some hint about the final answer:
<hint>
Your final answer must be output exactly in the format specified by the question. Please keep the answer concise:
- Return the answer to the question directly. Do NOT provide any other content, nor include the thinking process or explanations.
- Keep your answers concise and do NOT repeat the questions
</hint>
"""
    return finalize_prompt
